"""Samedia server: HTTP API for the Samsung TV app + a small web admin page."""

import asyncio
import hashlib
import hmac
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import art, db, library, playback, subtitles
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
            "pin_required": bool(config.pin)}


@app.post("/api/v1/auth")
def pair(body: PairBody):
    if config.pin and not hmac.compare_digest(body.pin.strip(), config.pin):
        raise HTTPException(status_code=401, detail="Wrong PIN")
    return {"token": access_token() if config.pin else ""}


api = Depends(require_auth)


# ── browse ──────────────────────────────────────────────────────────

@app.get("/api/v1/home", dependencies=[api])
def home():
    return library.home()


@app.get("/api/v1/movies", dependencies=[api])
def movies(sort: str = "title", genre: str | None = None, unwatched: bool = False,
           offset: int = 0, limit: int = Query(5000, le=5000)):
    return {"items": library.movies(sort, genre, unwatched, offset, limit), "genres": library.genres("movie")}


@app.get("/api/v1/shows", dependencies=[api])
def shows(sort: str = "title", genre: str | None = None, offset: int = 0, limit: int = Query(5000, le=5000)):
    return {"items": library.shows(sort, genre, offset, limit), "genres": library.genres("show")}


@app.get("/api/v1/shows/{show_id}", dependencies=[api])
def show(show_id: str):
    detail = library.show_detail(show_id)
    if not detail:
        raise HTTPException(404, "Show not found")
    return detail


@app.get("/api/v1/items/{item_id}", dependencies=[api])
def item(item_id: str):
    row = library.get_item(item_id)
    if not row:
        raise HTTPException(404, "Item not found")
    out = library.item_summary(row)
    media = row.get("media") or {}
    out["media"] = {"container": media.get("container"), "video": media.get("video"), "bitrate": media.get("bitrate")}
    out["audio_tracks"] = playback.decide(row, None)["audio_tracks"]
    out["subtitle_tracks"] = playback.subtitle_tracks(row)
    out["next"] = library.next_episode(row)
    out["file"] = Path(row["path"]).name
    return out


@app.get("/api/v1/search", dependencies=[api])
def search(q: str = Query(..., min_length=1, max_length=100)):
    return library.search(q)


# ── playback ────────────────────────────────────────────────────────

class PlaybackBody(BaseModel):
    capabilities: dict | None = None
    audio_index: int | None = None
    start: float = 0
    force: str | None = None           # None | "remux" | "transcode"
    prefer_audio_lang: str | None = None
    session: str | None = None


@app.post("/api/v1/items/{item_id}/playback", dependencies=[api])
def start_playback(item_id: str, body: PlaybackBody):
    row = library.get_item(item_id)
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
def stream_direct(item_id: str, request: Request):
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
def progress(item_id: str, body: ProgressBody):
    if not db.one("SELECT id FROM items WHERE id=?", (item_id,)):
        raise HTTPException(404)
    p = db.save_progress(item_id, max(body.position, 0), body.duration)
    return {"position": p["position"], "watched": bool(p["watched"])}


class WatchedBody(BaseModel):
    watched: bool


@app.post("/api/v1/items/{item_id}/watched", dependencies=[api])
def watched(item_id: str, body: WatchedBody):
    if not db.one("SELECT id FROM items WHERE id=?", (item_id,)):
        raise HTTPException(404)
    db.set_watched(item_id, body.watched)
    return {"watched": body.watched}


@app.post("/api/v1/shows/{show_id}/watched", dependencies=[api])
def show_watched(show_id: str, body: WatchedBody, season: int | None = None):
    sql, params = "SELECT id FROM items WHERE show_id=?", [show_id]
    if season is not None:
        sql += " AND season=?"
        params.append(season)
    for r in db.query(sql, params):
        db.set_watched(r["id"], body.watched)
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


# ── artwork ─────────────────────────────────────────────────────────

@app.get("/api/v1/art/{owner_id}/{kind}", dependencies=[api])
async def artwork(owner_id: str, kind: str, w: int = Query(400, ge=50, le=1920)):
    if kind not in ("poster", "backdrop", "thumb"):
        raise HTTPException(404)
    table = "shows" if owner_id.startswith("s") else "items"
    if kind == "thumb" and table == "shows":
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


@app.get("/api/v1/admin/settings", dependencies=[api])
def get_settings():
    return {k: getattr(config, k) for k in EDITABLE}


@app.put("/api/v1/admin/settings", dependencies=[api])
def put_settings(body: dict):
    unknown = set(body) - set(EDITABLE)
    if unknown:
        raise HTTPException(400, f"Unknown settings: {', '.join(sorted(unknown))}")
    apply_overrides(body)
    for k in body:
        db.save_setting(k, getattr(config, k))
    return get_settings()


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
