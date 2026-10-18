"""Samedia server: HTTP API for the Samsung TV app + a small web admin page."""

import asyncio
import hashlib
import hmac
import logging
import os
import json
import re
import time
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import art, db, frames, library, playback, subtitles
from .config import API_VERSION, EDITABLE, VERSION, apply_overrides, config
from .scanner import scanner

logging.basicConfig(level=os.environ.get("SAMEDIA_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("samedia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    apply_overrides(db.load_settings())
    config.secret()  # create on first boot
    if os.environ.get("SAMEDIA_NO_SCAN") != "1":
        scanner.start_background()
    yield


app = FastAPI(title="Samedia", version=VERSION, lifespan=lifespan)
# The TV app is a packaged web app (origin file:// / app://), so it needs permissive CORS.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"])


# ── auth ────────────────────────────────────────────────────────────

def access_token() -> str:
    return hmac.new(config.secret().encode(), f"samedia:{config.pin}".encode(), hashlib.sha256).hexdigest()[:40]


def require_auth(request: Request, t: str | None = Query(None)) -> None:
    if not config.pin:
        return
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else t
    if not token or not hmac.compare_digest(token, access_token()):
        raise HTTPException(status_code=401, detail="PIN required")


class PairBody(BaseModel):
    pin: str


@app.get("/api/v1/info")
def info():
    return {"name": config.server_name, "app": "samedia", "version": VERSION, "api": API_VERSION,
            "pin_required": bool(config.pin), "features": ["profiles", "hidden", "collections", "bookmarks", "frames", "devices", "avatars"]}


@app.post("/api/v1/auth")
def pair(body: PairBody):
    if config.pin and not hmac.compare_digest(body.pin.strip(), config.pin):
        raise HTTPException(status_code=401, detail="Wrong PIN")
    return {"token": access_token() if config.pin else ""}


api = Depends(require_auth)

_PROFILE_ID = re.compile(r"^[a-z0-9]{1,32}$")
_DEVICE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_DEVICE_SEEN_EVERY = 60  # seconds between last-seen updates


def current_device(request: Request) -> dict | None:
    """The TV making the request (X-Samedia-Device), registered on first contact."""
    did = request.headers.get("x-samedia-device") or ""
    if not _DEVICE_ID.match(did):
        return None
    now = time.time()
    row = db.one("SELECT * FROM devices WHERE id=?", (did,))
    model = urllib.parse.unquote(request.headers.get("x-samedia-device-name") or "")[:80] or None
    if not row:
        default = db.load_settings().get("new_device_profiles")   # None = all profiles
        db.upsert("devices", {"id": did, "name": None, "model": model, "profiles": default,
                              "created_at": now, "last_seen": now})
        row = db.one("SELECT * FROM devices WHERE id=?", (did,))
    elif now - row["last_seen"] > _DEVICE_SEEN_EVERY or (model and model != row["model"]):
        db.execute("UPDATE devices SET last_seen=?, model=COALESCE(?, model) WHERE id=?", (now, model, did))
    return row


def allowed_profiles(device: dict | None) -> list[dict]:
    """Profiles this TV may show (all when the TV is unknown or unrestricted)."""
    rows = db.query("SELECT * FROM profiles ORDER BY created_at")
    allowed = device and device.get("profiles")
    if allowed is None or allowed is False:
        return rows
    picked = [r for r in rows if r["id"] in allowed]
    return picked or rows[:1]


def viewer(request: Request, profile: str | None = Query(None)) -> library.Viewer:
    """The profile the TV is browsing as (X-Samedia-Profile header), limited to the profiles
    this TV may show; anything else falls back to the TV's first allowed profile."""
    pid = request.headers.get("x-samedia-profile") or profile or db.DEFAULT_PROFILE
    options = allowed_profiles(current_device(request))
    row = next((p for p in options if p["id"] == pid), None) if _PROFILE_ID.match(pid) else None
    row = row or options[0]
    return library.Viewer(profile_id=row["id"], kids=bool(row["kids"]))


Me = Depends(viewer)


# ── browse ──────────────────────────────────────────────────────────

@app.get("/api/v1/home", dependencies=[api])
def home(v: library.Viewer = Me):
    return library.home(v)


@app.get("/api/v1/movies", dependencies=[api])
def movies(sort: str = "title", genre: str | None = None, unwatched: bool = False, group: bool = False,
           offset: int = 0, limit: int = Query(5000, le=5000), v: library.Viewer = Me):
    return {"items": library.movies(v, sort, genre, unwatched, offset, limit, group=group),
            "genres": library.genres(v, "movie")}


@app.get("/api/v1/shows", dependencies=[api])
def shows(sort: str = "title", genre: str | None = None, offset: int = 0, limit: int = Query(5000, le=5000),
          v: library.Viewer = Me):
    return {"items": library.shows(v, sort, genre, offset, limit), "genres": library.genres(v, "show")}


@app.get("/api/v1/shows/{show_id}", dependencies=[api])
def show(show_id: str, v: library.Viewer = Me):
    detail = library.show_detail(v, show_id)
    if not detail:
        raise HTTPException(404, "Show not found")
    return detail


@app.get("/api/v1/collections/{collection_id}", dependencies=[api])
def collection(collection_id: str, v: library.Viewer = Me):
    detail = library.collection_detail(v, collection_id)
    if not detail:
        raise HTTPException(404, "Collection not found")
    return detail


@app.get("/api/v1/items/{item_id}", dependencies=[api])
def item(item_id: str, v: library.Viewer = Me):
    row = library.get_item(item_id, v)
    if not row:
        raise HTTPException(404, "Item not found")
    out = library.item_summary(row)
    out.update(library.item_detail_extras(row))
    media = row.get("media") or {}
    out["media"] = {"container": media.get("container"), "video": media.get("video"), "bitrate": media.get("bitrate")}
    out["audio_tracks"] = playback.decide(row, None)["audio_tracks"]
    out["subtitle_tracks"] = playback.subtitle_tracks(row)
    out["next"] = library.next_episode(v, row)
    out["bookmarks"] = library.bookmarks_for(v, item_id)
    out["file"] = Path(row["path"]).name
    return out


@app.get("/api/v1/search", dependencies=[api])
def search(q: str = Query(..., min_length=1, max_length=100), v: library.Viewer = Me):
    return library.search(v, q)


# ── profiles ────────────────────────────────────────────────────────

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ProfileBody(BaseModel):
    name: str | None = None
    color: str | None = None
    kids: bool | None = None
    avatar: str | None = None     # one of db.AVATARS, "" = just the initial


def _profile_out(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "color": r["color"], "kids": bool(r["kids"]), "avatar": r.get("avatar")}


@app.get("/api/v1/avatars", dependencies=[api])
def list_avatars():
    return {"avatars": list(db.AVATARS)}


class AvatarBody(BaseModel):
    avatar: str     # one of db.AVATARS, "" = just the initial


@app.post("/api/v1/profiles/{profile_id}/avatar", dependencies=[api])
def set_avatar(profile_id: str, body: AvatarBody, request: Request):
    """Picture chosen on a TV: only for profiles that TV is allowed to show."""
    if profile_id not in {p["id"] for p in allowed_profiles(current_device(request))}:
        raise HTTPException(403, "This TV can't change that profile")
    if body.avatar and body.avatar not in db.AVATARS:
        raise HTTPException(400, "Unknown avatar")
    db.execute("UPDATE profiles SET avatar=? WHERE id=?", (body.avatar or None, profile_id))
    return _profile_out(db.one("SELECT * FROM profiles WHERE id=?", (profile_id,)))


@app.get("/api/v1/profiles", dependencies=[api])
def list_profiles(request: Request, all: bool = False):
    """Profiles for this TV (all=true: every profile, for the admin page)."""
    rows = db.query("SELECT * FROM profiles ORDER BY created_at") if all else allowed_profiles(current_device(request))
    return {"profiles": [_profile_out(r) for r in rows]}


def _clean_profile(body: ProfileBody) -> dict:
    out = {}
    if body.name is not None:
        name = body.name.strip()[:24]
        if not name:
            raise HTTPException(400, "Name is required")
        out["name"] = name
    if body.color is not None:
        if not _COLOR.match(body.color):
            raise HTTPException(400, "Color must be #RRGGBB")
        out["color"] = body.color
    if body.kids is not None:
        out["kids"] = int(body.kids)
    if body.avatar is not None:
        if body.avatar and body.avatar not in db.AVATARS:
            raise HTTPException(400, "Unknown avatar")
        out["avatar"] = body.avatar or None
    return out


@app.post("/api/v1/profiles", dependencies=[api])
def create_profile(body: ProfileBody):
    values = _clean_profile(body)
    if "name" not in values:
        raise HTTPException(400, "Name is required")
    if db.one("SELECT COUNT(*) AS n FROM profiles")["n"] >= 12:
        raise HTTPException(400, "Too many profiles")
    pid = uuid.uuid4().hex[:12]
    db.upsert("profiles", {"id": pid, "color": "#5b8cff", "kids": 0, "avatar": db.next_avatar(), **values,
                           "created_at": time.time()})
    return _profile_out(db.one("SELECT * FROM profiles WHERE id=?", (pid,)))


@app.put("/api/v1/profiles/{profile_id}", dependencies=[api])
def update_profile(profile_id: str, body: ProfileBody):
    if not db.one("SELECT id FROM profiles WHERE id=?", (profile_id,)):
        raise HTTPException(404, "Profile not found")
    values = _clean_profile(body)
    if values:
        db.execute(f"UPDATE profiles SET {', '.join(f'{k}=?' for k in values)} WHERE id=?",
                   (*values.values(), profile_id))
    return _profile_out(db.one("SELECT * FROM profiles WHERE id=?", (profile_id,)))


@app.delete("/api/v1/profiles/{profile_id}", dependencies=[api])
def delete_profile(profile_id: str):
    if not db.one("SELECT id FROM profiles WHERE id=?", (profile_id,)):
        raise HTTPException(404, "Profile not found")
    if db.one("SELECT COUNT(*) AS n FROM profiles")["n"] <= 1:
        raise HTTPException(400, "The last profile can't be deleted")
    # Never let a restricted TV (e.g. a child's room with only Kids) fall open to every profile
    for d in db.query("SELECT * FROM devices WHERE profiles IS NOT NULL"):
        if d["profiles"] == [profile_id]:
            raise HTTPException(400, f"It's the only profile on the TV \"{_device_out(d)['name']}\" — "
                                     "pick another profile for that TV first")
    if db.load_settings().get("new_device_profiles") == [profile_id]:
        raise HTTPException(400, "It's the only profile new TVs get — change \"New TVs offer\" first")
    db.execute("DELETE FROM progress WHERE profile_id=?", (profile_id,))
    db.execute("DELETE FROM hidden WHERE profile_id=?", (profile_id,))
    db.execute("DELETE FROM bookmarks WHERE profile_id=?", (profile_id,))
    db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    # Drop it from TVs' allowed lists (none of them is left empty: checked above)
    for d in db.query("SELECT id, profiles FROM devices WHERE profiles IS NOT NULL"):
        if profile_id in d["profiles"]:
            rest = [p for p in d["profiles"] if p != profile_id]
            db.execute("UPDATE devices SET profiles=? WHERE id=?", (json.dumps(rest), d["id"]))
    default = db.load_settings().get("new_device_profiles")
    if default and profile_id in default:
        db.save_setting("new_device_profiles", [p for p in default if p != profile_id])
    return {"ok": True}


# ── TVs (admin) ─────────────────────────────────────────────────────

def _device_out(r: dict) -> dict:
    return {"id": r["id"], "name": r.get("name") or r.get("model") or "TV", "custom_name": r.get("name"),
            "model": r.get("model"), "profiles": r.get("profiles"), "last_seen": r["last_seen"]}


class DeviceBody(BaseModel):
    name: str | None = None
    profiles: list[str] | None = None     # None = all profiles
    all_profiles: bool | None = None       # explicit "all" (since None also means "not sent")


def _valid_profile_list(ids: list[str]) -> list[str]:
    known = {r["id"] for r in db.query("SELECT id FROM profiles")}
    ids = [i for i in dict.fromkeys(ids) if i in known]
    if not ids:
        raise HTTPException(400, "Pick at least one profile (or all)")
    return ids


@app.get("/api/v1/admin/devices", dependencies=[api])
def list_devices():
    return {"devices": [_device_out(r) for r in db.query("SELECT * FROM devices ORDER BY last_seen DESC")],
            "new_device_profiles": db.load_settings().get("new_device_profiles")}


@app.put("/api/v1/admin/devices/{device_id}", dependencies=[api])
def update_device(device_id: str, body: DeviceBody):
    if not db.one("SELECT id FROM devices WHERE id=?", (device_id,)):
        raise HTTPException(404, "TV not found")
    if body.name is not None:
        db.execute("UPDATE devices SET name=? WHERE id=?", (body.name.strip()[:60] or None, device_id))
    if body.all_profiles:
        db.execute("UPDATE devices SET profiles=NULL WHERE id=?", (device_id,))
    elif body.profiles is not None:
        db.execute("UPDATE devices SET profiles=? WHERE id=?", (json.dumps(_valid_profile_list(body.profiles)), device_id))
    return _device_out(db.one("SELECT * FROM devices WHERE id=?", (device_id,)))


@app.delete("/api/v1/admin/devices/{device_id}", dependencies=[api])
def forget_device(device_id: str):
    db.execute("DELETE FROM devices WHERE id=?", (device_id,))
    return {"ok": True}


@app.put("/api/v1/admin/new-device-profiles", dependencies=[api])
def set_new_device_profiles(body: DeviceBody):
    value = None if body.all_profiles or body.profiles is None else _valid_profile_list(body.profiles)
    db.save_setting("new_device_profiles", value)
    return {"new_device_profiles": value}


# ── bookmarks ───────────────────────────────────────────────────────

class BookmarkBody(BaseModel):
    position: float
    label: str | None = None


@app.get("/api/v1/items/{item_id}/bookmarks", dependencies=[api])
def list_bookmarks(item_id: str, v: library.Viewer = Me):
    return {"bookmarks": library.bookmarks_for(v, item_id)}


@app.post("/api/v1/items/{item_id}/bookmarks", dependencies=[api])
def add_bookmark(item_id: str, body: BookmarkBody, v: library.Viewer = Me):
    row = db.one("SELECT id, duration FROM items WHERE id=?", (item_id,))
    if not row:
        raise HTTPException(404, "Item not found")
    position = max(0.0, body.position)
    if row["duration"]:
        position = min(position, row["duration"])
    # One bookmark per few seconds: pressing twice doesn't make duplicates
    near = db.one("SELECT id FROM bookmarks WHERE profile_id=? AND item_id=? AND ABS(position - ?) < 3",
                  (v.profile_id, item_id, position))
    if near:
        return {"bookmark": library._bookmark_out(db.one("SELECT * FROM bookmarks WHERE id=?", (near["id"],))),
                "bookmarks": library.bookmarks_for(v, item_id)}
    if db.one("SELECT COUNT(*) AS n FROM bookmarks WHERE profile_id=? AND item_id=?", (v.profile_id, item_id))["n"] >= 100:
        raise HTTPException(400, "Too many bookmarks for this title")
    bid = uuid.uuid4().hex[:12]
    label = (body.label or "").strip()[:80] or None
    db.execute("INSERT INTO bookmarks (id, profile_id, item_id, position, label, created_at) VALUES (?, ?, ?, ?, ?, ?)",
               (bid, v.profile_id, item_id, position, label, time.time()))
    return {"bookmark": library._bookmark_out(db.one("SELECT * FROM bookmarks WHERE id=?", (bid,))),
            "bookmarks": library.bookmarks_for(v, item_id)}


class BookmarkUpdate(BaseModel):
    label: str | None = None


@app.put("/api/v1/bookmarks/{bookmark_id}", dependencies=[api])
def rename_bookmark(bookmark_id: str, body: BookmarkUpdate, v: library.Viewer = Me):
    if not db.one("SELECT id FROM bookmarks WHERE id=? AND profile_id=?", (bookmark_id, v.profile_id)):
        raise HTTPException(404, "Bookmark not found")
    db.execute("UPDATE bookmarks SET label=? WHERE id=?", ((body.label or "").strip()[:80] or None, bookmark_id))
    return library._bookmark_out(db.one("SELECT * FROM bookmarks WHERE id=?", (bookmark_id,)))


@app.delete("/api/v1/bookmarks/{bookmark_id}", dependencies=[api])
def delete_bookmark(bookmark_id: str, v: library.Viewer = Me):
    db.execute("DELETE FROM bookmarks WHERE id=? AND profile_id=?", (bookmark_id, v.profile_id))
    return {"ok": True}


@app.get("/api/v1/bookmarks", dependencies=[api])
def all_bookmarks(v: library.Viewer = Me):
    return {"items": library.bookmarked_items(v, 200)}


# ── hidden titles ───────────────────────────────────────────────────

class HideBody(BaseModel):
    id: str


@app.get("/api/v1/hidden", dependencies=[api])
def list_hidden(v: library.Viewer = Me):
    return {"items": library.hidden(v)}


@app.post("/api/v1/hidden", dependencies=[api])
def hide(body: HideBody, v: library.Viewer = Me):
    if not library.target_kind(body.id):
        raise HTTPException(404, "Nothing to hide with that id")
    db.execute("INSERT OR IGNORE INTO hidden (profile_id, target_id, created_at) VALUES (?, ?, ?)",
               (v.profile_id, body.id, time.time()))
    return {"hidden": True}


@app.delete("/api/v1/hidden/{target_id}", dependencies=[api])
def unhide(target_id: str, v: library.Viewer = Me):
    db.execute("DELETE FROM hidden WHERE profile_id=? AND target_id=?", (v.profile_id, target_id))
    return {"hidden": False}


# ── playback ────────────────────────────────────────────────────────

class PlaybackBody(BaseModel):
    capabilities: dict | None = None
    audio_index: int | None = None
    start: float = 0
    force: str | None = None           # None | "remux" | "transcode"
    prefer_audio_lang: str | None = None
    session: str | None = None


@app.post("/api/v1/items/{item_id}/playback", dependencies=[api])
def start_playback(item_id: str, body: PlaybackBody, v: library.Viewer = Me):
    row = library.get_item(item_id, v)
    if not row:
        raise HTTPException(404, "Item not found")
    if not row.get("media"):
        raise HTTPException(422, "This file could not be read (ffprobe failed).")
    if body.force not in (None, "remux", "transcode"):
        raise HTTPException(400, "force must be remux or transcode")
    session = re.sub(r"[^A-Za-z0-9_-]", "", body.session or "")[:40] or uuid.uuid4().hex[:12]
    decision = playback.decide(row, body.capabilities, audio_index=body.audio_index, start=max(body.start, 0),
                               force=body.force, prefer_lang=body.prefer_audio_lang, session=session)
    decision["session"] = session
    # Warm the subtitle cache so tracks are ready by the time the user opens the menu.
    if any(s["format"] in ("text", "pgs") for s in row["media"].get("subtitles", [])):
        subtitles.extract_in_background(item_id, Path(row["path"]), row["media"])
    log.info("play %s (%s): %s %s", row["title"], item_id, decision["mode"], decision["reasons"])
    return decision


_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


@app.api_route("/api/v1/stream/{item_id}/direct", methods=["GET", "HEAD"], dependencies=[api])
@app.api_route("/api/v1/stream/{item_id}/direct.{ext}", methods=["GET", "HEAD"], dependencies=[api])
def stream_direct(item_id: str, request: Request, ext: str = ""):
    """The original file, with Range support. The extension in the URL is only for the TV."""
    row = library.get_item(item_id)
    if not row:
        raise HTTPException(404)
    path = Path(row["path"])
    try:
        size = path.stat().st_size
    except OSError:
        raise HTTPException(404, "File is not reachable (disk unplugged?)")
    mime = playback.MIME.get((row.get("media") or {}).get("container"), "application/octet-stream")
    headers = {"Accept-Ranges": "bytes", "Content-Type": mime}

    start, end, status = 0, size - 1, 200
    if m := _RANGE.match(request.headers.get("range", "")):
        a, b = m.groups()
        if a:
            start, end = int(a), int(b) if b else size - 1
        elif b:  # suffix range: last N bytes
            start = max(size - int(b), 0)
        end = min(end, size - 1)
        if start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(end - start + 1)
    if request.method == "HEAD":
        return Response(status_code=status, headers=headers)

    def reader(chunk=1024 * 1024):
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(reader(), status_code=status, headers=headers, media_type=mime)


@app.get("/api/v1/stream/{item_id}/remux", dependencies=[api])
async def stream_remux(item_id: str, start: float = 0, audio: int = -1, acodec: str = "copy",
                       vcodec: str = "copy", session: str = "default"):
    row = library.get_item(item_id)
    if not row or not row.get("media"):
        raise HTTPException(404)
    if acodec not in ("copy", "eac3") or vcodec not in ("copy", "h264"):
        raise HTTPException(400, "bad codec")
    if audio >= 0 and audio not in {a["index"] for a in row["media"].get("audio", [])}:
        raise HTTPException(400, "bad audio index")
    session = re.sub(r"[^A-Za-z0-9_-]", "", session)[:40] or "default"
    cmd = playback.build_ffmpeg_cmd(row, max(start, 0), audio, acodec, vcodec)
    return StreamingResponse(playback.stream_ffmpeg(session, cmd), media_type=playback.MIME["ts"],
                             headers={"Cache-Control": "no-store"})


class ProgressBody(BaseModel):
    position: float
    duration: float | None = None


@app.post("/api/v1/items/{item_id}/progress", dependencies=[api])
def progress(item_id: str, body: ProgressBody, v: library.Viewer = Me):
    if not db.one("SELECT id FROM items WHERE id=?", (item_id,)):
        raise HTTPException(404)
    p = db.save_progress(v.profile_id, item_id, max(body.position, 0), body.duration)
    return {"position": p["position"], "watched": bool(p["watched"])}


class WatchedBody(BaseModel):
    watched: bool


@app.post("/api/v1/items/{item_id}/watched", dependencies=[api])
def watched(item_id: str, body: WatchedBody, v: library.Viewer = Me):
    if not db.one("SELECT id FROM items WHERE id=?", (item_id,)):
        raise HTTPException(404)
    db.set_watched(v.profile_id, item_id, body.watched)
    return {"watched": body.watched}


@app.post("/api/v1/shows/{show_id}/watched", dependencies=[api])
def show_watched(show_id: str, body: WatchedBody, season: int | None = None, v: library.Viewer = Me):
    sql, params = "SELECT id FROM items WHERE show_id=?", [show_id]
    if season is not None:
        sql += " AND season=?"
        params.append(season)
    for r in db.query(sql, params):
        db.set_watched(v.profile_id, r["id"], body.watched)
    return {"watched": body.watched}


# ── subtitles ───────────────────────────────────────────────────────

@app.get("/api/v1/subs/{item_id}/{track}", dependencies=[api])
async def subtitle(item_id: str, track: str, wait: float = Query(25, le=60)):
    row = library.get_item(item_id)
    if not row:
        raise HTTPException(404)
    if track.startswith("x") and track[1:].isdigit():
        side = (row.get("sidecar_subs") or [])
        i = int(track[1:])
        if i >= len(side):
            raise HTTPException(404)
        f = Path(row["path"]).parent / side[i]["file"]
        if side[i]["format"] == "pgs":
            return FileResponse(f, media_type="application/octet-stream")
        vtt = await run_in_threadpool(subtitles.sidecar_as_vtt, item_id, f)
        return FileResponse(vtt, media_type="text/vtt; charset=utf-8")

    if not (track.startswith("e") and track[1:].isdigit()):
        raise HTTPException(404)
    index = int(track[1:])
    stream = next((s for s in (row.get("media") or {}).get("subtitles", []) if s["index"] == index), None)
    if not stream or stream["format"] not in ("text", "pgs"):
        raise HTTPException(404, "Unsupported subtitle track")
    path = subtitles.embedded_path(item_id, stream)
    if path is None:
        subtitles.extract_in_background(item_id, Path(row["path"]), row["media"])
        waited = 0.0
        while path is None and waited < wait:
            await asyncio.sleep(0.5)
            waited += 0.5
            path = subtitles.embedded_path(item_id, stream)
        if path is None:
            # Large remuxes take a while to read; the TV retries on 202.
            return JSONResponse({"status": "extracting"}, status_code=202)
    media_type = "application/octet-stream" if stream["format"] == "pgs" else "text/vtt; charset=utf-8"
    return FileResponse(path, media_type=media_type)


# ── scrubbing preview frames ────────────────────────────────────────

@app.get("/api/v1/items/{item_id}/frame", dependencies=[api])
async def preview_frame(item_id: str, t: float = Query(..., ge=0), w: int = Query(320, ge=100, le=480)):
    row = library.get_item(item_id)
    if not row or not row.get("media"):
        raise HTTPException(404)
    path = await run_in_threadpool(frames.frame, item_id, row["path"], t, w, row.get("duration"))
    if path is None:
        raise HTTPException(404, "No frame")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


# ── artwork ─────────────────────────────────────────────────────────

@app.get("/api/v1/art/{owner_id}/{kind}", dependencies=[api])
async def artwork(owner_id: str, kind: str, w: int = Query(400, ge=50, le=1920)):
    if kind not in ("poster", "backdrop", "thumb"):
        raise HTTPException(404)
    table = {"s": "shows", "c": "collections"}.get(owner_id[:1], "items")
    if kind == "thumb" and table != "items":
        raise HTTPException(404)
    row = db.one(f"SELECT {kind} AS ref FROM {table} WHERE id=?", (owner_id,))
    if not row or not row["ref"]:
        raise HTTPException(404)
    path = await run_in_threadpool(art.resolve, row["ref"], w)
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


# ── admin ───────────────────────────────────────────────────────────

@app.get("/api/v1/admin/status", dependencies=[api])
def admin_status():
    roots = [{"path": r, "reachable": Path(r).is_dir()} for r in config.media_roots]
    return {"scan": scanner.status, "stats": library.stats(), "roots": roots,
            "streams": playback.active_sessions(), "version": VERSION}


_MASK = "••••"


def _masked(key: str) -> str:
    return f"{_MASK}{key[-4:]}" if key else ""


@app.get("/api/v1/admin/settings", dependencies=[api])
def get_settings():
    out = {k: getattr(config, k) for k in EDITABLE}
    # Never send the saved TMDB key back out; the admin page shows its last 4 characters
    out["tmdb_key"] = _masked(config.tmdb_key)
    return out


@app.put("/api/v1/admin/settings", dependencies=[api])
def put_settings(body: dict):
    unknown = set(body) - set(EDITABLE)
    if unknown:
        raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")
    if str(body.get("tmdb_key", "")).startswith(_MASK):
        body.pop("tmdb_key")            # the masked value came back unchanged
    old_key = config.tmdb_key
    apply_overrides(body)
    for k in body:
        db.save_setting(k, getattr(config, k))
    if config.tmdb_key != old_key and config.tmdb_key:
        _refresh_metadata()
    return get_settings()


def _refresh_metadata() -> bool:
    """Re-fetch TMDB details for the whole library on the next (immediate) scan."""
    db.execute("UPDATE items SET meta_at=NULL")
    db.execute("UPDATE shows SET meta_at=NULL")
    return scanner.request_scan()


@app.post("/api/v1/admin/refresh-metadata", dependencies=[api])
def admin_refresh_metadata():
    if not config.tmdb_key:
        raise HTTPException(400, "Set a TMDB key first")
    return {"started": _refresh_metadata()}


@app.post("/api/v1/admin/scan", dependencies=[api])
def admin_scan():
    return {"started": scanner.request_scan()}


@app.get("/healthz")
def healthz():
    return {"ok": True}


_web = Path(__file__).parent / "web"
app.mount("/", StaticFiles(directory=_web, html=True), name="web")


def run() -> None:
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port, log_level="info", proxy_headers=True)


if __name__ == "__main__":
    run()
