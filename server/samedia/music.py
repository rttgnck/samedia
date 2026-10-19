"""Music: tracks found in the media folders, grouped into albums and artists, with artwork.

Tags are read with ffprobe; files without tags are named from their folders
(Artist/Album/01 - Title.mp3), or, with an AcoustID key, by their sound. Album art comes from
the album's folder (cover.jpg...), from inside the files, or from the Cover Art Archive (found
through MusicBrainz, which needs no key).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import db
from .config import VERSION, config

log = logging.getLogger("samedia.music")

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".aiff", ".aif",
              ".ape", ".wv", ".alac", ".mka"}
COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartsmall")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_DISC_DIR = re.compile(r"^(cd|dis[ck])\s*[-_.]?\s*\d+$", re.I)
_TRACK_FILE = re.compile(r"^(?:(\d{1,2})[-.](?=\d))?(\d{1,3})[\s._-]+(?:(.+?)\s+-\s+)?(.+)$")
USER_AGENT = f"Samedia/{VERSION} ( https://github.com/rttgnck/samedia )"
_mb_lock = threading.Lock()
_mb_last = 0.0


def make_id(prefix: str, key: str) -> str:
    return prefix + hashlib.sha1(key.encode()).hexdigest()[:15]


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def sort_name(s: str | None) -> str:
    s = (s or "").strip()
    return re.sub(r"^(the|a|an)\s+", "", s, flags=re.I).lower()


def _int(v) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


# ── reading files ─────────────────────────────────────────────────────

def read_tags(path: Path) -> dict:
    """Tags and stream details of one audio file (ffprobe)."""
    try:
        out = subprocess.run([config.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                              str(path)], capture_output=True, text=True, timeout=60).stdout
        info = json.loads(out or "{}")
    except (subprocess.SubprocessError, ValueError, OSError):
        info = {}
    fmt = info.get("format") or {}
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    streams = info.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    for k, v in (audio.get("tags") or {}).items():          # Ogg/Opus keep tags on the stream
        tags.setdefault(k.lower(), v)
    pic = any(s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic") for s in streams)
    return {
        "title": tags.get("title"), "artist": tags.get("artist"),
        "album_artist": tags.get("album_artist") or tags.get("albumartist") or tags.get("album artist"),
        "album": tags.get("album"), "track": _int(tags.get("track") or tags.get("tracknumber")),
        "disc": _int(tags.get("disc") or tags.get("discnumber")), "year": _int(tags.get("date") or tags.get("year")),
        "genre": (tags.get("genre") or "").split(";")[0].strip() or None,
        "compilation": str(tags.get("compilation") or "") in ("1", "true"),
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "codec": audio.get("codec_name"), "bitrate": _int(fmt.get("bit_rate")),
        "sample_rate": _int(audio.get("sample_rate")), "channels": audio.get("channels"), "embedded_art": pic,
    }


def album_dir(path: Path) -> Path:
    """The album's folder (CD1/CD2 folders belong to the one above)."""
    d = path.parent
    return d.parent if _DISC_DIR.match(d.name) else d


def from_path(path: Path, root: Path) -> dict:
    """What the folders and file name say: Artist/Album/01 - Title (or 1-01 Artist - Title)."""
    adir = album_dir(path)
    out: dict = {}
    m = _TRACK_FILE.match(path.stem)
    if m:
        out["disc"] = int(m.group(1)) if m.group(1) else None
        out["track"] = int(m.group(2))
        out["title"] = m.group(4).strip()
        if m.group(3):
            out["artist"] = m.group(3).strip()
    else:
        out["title"] = path.stem.replace("_", " ").strip()
    if _DISC_DIR.match(path.parent.name) and not out.get("disc"):
        out["disc"] = _int(re.sub(r"\D", " ", path.parent.name))
    if adir != root:
        name = adir.name
        ym = re.search(r"[\(\[](\d{4})[\)\]]", name)
        if ym:
            out["year"] = int(ym.group(1))
        name = re.sub(r"\s*[\(\[]\d{4}[\)\]]\s*", " ", name).strip()
        if " - " in name and adir.parent == root:          # "Artist - Album"
            artist, name = name.split(" - ", 1)
            out.setdefault("artist", artist.strip())
        out["album"] = name
        if adir.parent != root and adir.parent != adir:
            out.setdefault("artist", adir.parent.name)
    return out


def folder_art(directory: Path) -> Path | None:
    try:
        images = [p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")]
    except OSError:
        return None
    for name in COVER_NAMES:
        for p in images:
            if p.stem.lower() == name:
                return p
    return images[0] if len(images) == 1 else None


# ── scanning ──────────────────────────────────────────────────────────

def walk(root: Path, videos_too: bool) -> list[Path]:
    """Audio files under root. In an "auto" folder (videos_too), only those in folders without
    videos: a movie's soundtrack sample isn't music."""
    from . import naming
    found = []
    import os
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if d.lower() not in naming.IGNORED_DIRS and not d.startswith(".")]
        names = [n for n in filenames if not n.startswith(".")]
        if videos_too and any(Path(n).suffix.lower() in naming.VIDEO_EXTS for n in names):
            continue
        found.extend(Path(dirpath) / n for n in names if Path(n).suffix.lower() in AUDIO_EXTS)
    return found


def index_track(root: Path, path: Path, st) -> None:
    tags = read_tags(path)
    guess = from_path(path, root)
    tagged = bool(tags.get("title") and (tags.get("artist") or tags.get("album_artist")))
    values = {k: tags.get(k) or guess.get(k) for k in ("title", "artist", "album", "track", "disc", "year")}
    old = db.one("SELECT added_at, id_checked_at FROM music_tracks WHERE path=?", (str(path),))
    db.upsert("music_tracks", {
        "id": make_id("t", str(path)), "path": str(path), "root": str(root), "size": st.st_size, "mtime": st.st_mtime,
        **values, "album_artist": tags.get("album_artist"), "genre": tags.get("genre"),
        "compilation": int(tags.get("compilation") or False),
        "sort_title": sort_name(values["title"]), "duration": tags.get("duration"), "codec": tags.get("codec"),
        "bitrate": tags.get("bitrate"), "sample_rate": tags.get("sample_rate"), "channels": tags.get("channels"),
        "embedded_art": int(tags.get("embedded_art") or False), "tagged": int(tagged),
        "id_checked_at": old["id_checked_at"] if old else None,
        "added_at": old["added_at"] if old else time.time(),
    })


def scan(roots: list[tuple[Path, str]], status: dict | None = None) -> int:
    """Index new and changed audio files under the (folder, kind) pairs; drop vanished ones."""
    files: list[tuple[Path, Path]] = []
    reachable = []
    for root, kind in roots:
        if kind in ("movies", "shows") or not root.is_dir():
            continue
        reachable.append(str(root))
        files.extend((root, f) for f in walk(root, videos_too=kind == "auto"))
    known = {r["path"]: r for r in db.query("SELECT path, size, mtime FROM music_tracks")}
    changed = 0
    for root, f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        row = known.get(str(f))
        if row and row["size"] == st.st_size and abs(row["mtime"] - st.st_mtime) < 1:
            continue
        if status is not None:
            status["current"] = str(f)
        try:
            index_track(root, f, st)
            changed += 1
        except Exception:
            log.exception("failed to read %s", f)
    present = {str(f) for _, f in files}
    gone = [p for p, _ in known.items() if p not in present and any(p.startswith(r) for r in reachable)]
    # folders no longer in the list (or set to movies/shows) take their music with them
    in_use = [str(r) for r, k in roots if k not in ("movies", "shows")]
    gone += [r["path"] for r in db.query("SELECT path FROM music_tracks")
             if not any(r["path"].startswith(p) for p in in_use)]
    for p in set(gone):
        db.execute("DELETE FROM music_tracks WHERE path=?", (p,))
    refresh_albums()
    if changed or gone:
        log.info("music: %d new or changed, %d removed, %d tracks", changed, len(set(gone)),
                 db.one("SELECT COUNT(*) AS n FROM music_tracks")["n"])
    return changed


def refresh_albums() -> None:
    """Albums and artists from the tracks (keeps artwork already found)."""
    tracks = db.query("SELECT id, path, title, artist, album_artist, album, year, genre, duration, added_at, "
                      "compilation FROM music_tracks")
    groups: dict[str, list[dict]] = {}
    for t in tracks:
        key = norm(t["album"]) + "|" + str(album_dir(Path(t["path"])))
        groups.setdefault(key, []).append(t)
    albums, artists, updates = {}, {}, []
    for key, ts in groups.items():
        named = [t["album_artist"] for t in ts if t["album_artist"]]
        performers = {norm(t["artist"]) for t in ts if t["artist"]}
        if named:
            artist = max(set(named), key=named.count)
        elif len(performers) == 1 and not any(t["compilation"] for t in ts):
            artist = ts[0]["artist"]
        else:
            artist = "Various Artists" if len(performers) > 1 else (ts[0]["artist"] or "Unknown Artist")
        artist = artist or "Unknown Artist"
        aid = make_id("a", key)
        rid = make_id("r", norm(artist))
        years = [t["year"] for t in ts if t["year"]]
        genres = [t["genre"] for t in ts if t["genre"]]
        albums[aid] = {"id": aid, "title": ts[0]["album"] or "Unknown Album", "sort_title": sort_name(ts[0]["album"]),
                       "artist": artist, "artist_id": rid, "year": max(set(years), key=years.count) if years else None,
                       "genre": max(set(genres), key=genres.count) if genres else None, "track_count": len(ts),
                       "duration": sum(t["duration"] or 0 for t in ts), "added_at": min(t["added_at"] for t in ts),
                       "dir": str(album_dir(Path(ts[0]["path"])))}
        a = artists.setdefault(rid, {"id": rid, "name": artist, "sort_name": sort_name(artist), "album_count": 0,
                                     "track_count": 0, "added_at": albums[aid]["added_at"]})
        a["album_count"] += 1
        a["track_count"] += len(ts)
        updates.extend((aid, rid, t["id"]) for t in ts)
    db.many("UPDATE music_tracks SET album_id=?, artist_id=? WHERE id=?", updates)
    old = {r["id"]: r for r in db.query("SELECT id, art, art_checked_at, mbid FROM music_albums")}
    for aid, a in albums.items():
        prev = old.get(aid) or {}
        db.upsert("music_albums", {**a, "art": prev.get("art"), "art_checked_at": prev.get("art_checked_at"),
                                   "mbid": prev.get("mbid")})
    for aid in set(old) - set(albums):
        db.execute("DELETE FROM music_albums WHERE id=?", (aid,))
    db.execute("DELETE FROM music_artists")
    for a in artists.values():
        db.upsert("music_artists", a)


# ── artwork and names from the internet ───────────────────────────────

def _get_json(url: str, timeout: float = 12) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as exc:  # noqa: BLE001 - offline, rate limited...
        log.info("lookup failed: %s", exc.__class__.__name__)
        return None


def _musicbrainz(path: str, **params) -> dict | None:
    """MusicBrainz allows one request a second."""
    global _mb_last
    with _mb_lock:
        wait = 1.1 - (time.monotonic() - _mb_last)
        if wait > 0:
            time.sleep(wait)
        _mb_last = time.monotonic()
    return _get_json(f"https://musicbrainz.org/ws/2/{path}?" + urllib.parse.urlencode({**params, "fmt": "json"}))


def cover_art_url(artist: str, album: str) -> tuple[str | None, str | None]:
    """(Cover Art Archive front image, release-group id) for an album, if MusicBrainz knows it."""
    q = f'releasegroup:"{album}"' + (f' AND artist:"{artist}"' if artist and artist != "Various Artists" else "")
    found = _musicbrainz("release-group", query=q, limit=3) or {}
    for rg in found.get("release-groups") or []:
        if int(rg.get("score") or 0) < 85:
            continue
        mbid = rg["id"]
        url = f"https://coverartarchive.org/release-group/{mbid}/front-500"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
            urllib.request.urlopen(req, timeout=12).close()
            return url, mbid
        except Exception:  # noqa: BLE001 - no art for this one
            return None, mbid
    return None, None


def find_album_art(limit: int = 200) -> int:
    """Artwork for albums that have none yet: folder image, then the files', then the archive."""
    done = 0
    rows = db.query("SELECT * FROM music_albums WHERE art IS NULL AND (art_checked_at IS NULL OR art_checked_at < ?) "
                    "ORDER BY added_at DESC LIMIT ?", (time.time() - 14 * 86400, limit))
    for a in rows:
        art = None
        img = folder_art(Path(a["dir"])) if a.get("dir") else None
        if img:
            art = f"file:{img}"
        else:
            t = db.one("SELECT path FROM music_tracks WHERE album_id=? AND embedded_art=1 LIMIT 1", (a["id"],))
            if t:
                art = f"embedded:{t['path']}"
        mbid = a.get("mbid")
        if not art and a["title"] != "Unknown Album":
            url, mbid = cover_art_url(a["artist"], a["title"])
            art = f"url:{url}" if url else None
        db.execute("UPDATE music_albums SET art=?, mbid=COALESCE(?, mbid), art_checked_at=? WHERE id=?",
                   (art, mbid, time.time(), a["id"]))
        done += 1
    return done


def identify_untagged(limit: int = 100) -> int:
    """Name files that carry no tags by their sound (AcoustID; needs a key and fpcalc)."""
    if not config.acoustid_key or not shutil.which("fpcalc"):
        return 0
    named = 0
    rows = db.query("SELECT id, path, duration FROM music_tracks WHERE tagged=0 AND id_checked_at IS NULL LIMIT ?",
                    (limit,))
    for t in rows:
        db.execute("UPDATE music_tracks SET id_checked_at=? WHERE id=?", (time.time(), t["id"]))
        try:
            fp = json.loads(subprocess.run(["fpcalc", "-json", t["path"]], capture_output=True, text=True,
                                           timeout=60).stdout or "{}")
        except (subprocess.SubprocessError, ValueError, OSError):
            continue
        if not fp.get("fingerprint"):
            continue
        body = urllib.parse.urlencode({"client": config.acoustid_key, "meta": "recordings releasegroups",
                                       "duration": int(fp.get("duration") or t["duration"] or 0),
                                       "fingerprint": fp["fingerprint"]}).encode()
        try:
            req = urllib.request.Request("https://api.acoustid.org/v2/lookup", data=body,
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.load(r)
        except Exception:  # noqa: BLE001
            continue
        best = max((x for x in res.get("results") or [] if x.get("recordings")), key=lambda x: x.get("score", 0),
                   default=None)
        if not best or best.get("score", 0) < 0.8:
            continue
        rec = best["recordings"][0]
        artist = " & ".join(a["name"] for a in rec.get("artists") or []) or None
        album = (rec.get("releasegroups") or [{}])[0].get("title")
        db.execute("UPDATE music_tracks SET title=COALESCE(?, title), artist=COALESCE(?, artist), "
                   "album=COALESCE(?, album), sort_title=? WHERE id=?",
                   (rec.get("title"), artist, album, sort_name(rec.get("title")), t["id"]))
        named += 1
        time.sleep(0.4)
    if named:
        refresh_albums()
    return named


def enrich() -> None:
    try:
        identify_untagged()
        find_album_art()
    except Exception:  # noqa: BLE001 - never stop the scanner
        log.exception("music lookups failed")


# ── what the apps see ─────────────────────────────────────────────────

def track_out(t: dict) -> dict:
    return {"id": t["id"], "kind": "track", "title": t["title"], "artist": t["artist"], "album": t["album"],
            "album_id": t["album_id"], "artist_id": t["artist_id"], "track": t["track"], "disc": t["disc"],
            "year": t["year"], "duration": t["duration"], "codec": t["codec"],
            "art": f"/api/v1/music/art/{t['album_id']}" if t.get("album_id") else None}


def album_out(a: dict) -> dict:
    return {"id": a["id"], "kind": "album", "title": a["title"], "artist": a["artist"], "artist_id": a["artist_id"],
            "year": a["year"], "genre": a["genre"], "track_count": a["track_count"], "duration": a["duration"],
            "added_at": a["added_at"], "art": f"/api/v1/music/art/{a['id']}"}


def artist_out(a: dict) -> dict:
    return {"id": a["id"], "kind": "artist", "name": a["name"], "album_count": a["album_count"],
            "track_count": a["track_count"], "art": f"/api/v1/music/art/{a['id']}"}


class Allowed:
    """What a screen may play: everything, or (a locked screen) the approved albums and artists."""

    def __init__(self, lock: dict | None):
        self.all = not (lock and lock.get("music_only"))
        self.albums = set((lock or {}).get("albums") or [])
        self.artists = set((lock or {}).get("artists") or [])

    def where(self, alias: str = "") -> tuple[str, list]:
        """SQL condition on music_albums (alias.) rows."""
        if self.all:
            return "1=1", []
        a = alias + "." if alias else ""
        ids, artists = list(self.albums), list(self.artists)
        marks = lambda xs: ",".join("?" * len(xs)) or "NULL"
        return f"({a}id IN ({marks(ids)}) OR {a}artist_id IN ({marks(artists)}))", ids + artists

    def album(self, album_id: str) -> bool:
        if self.all:
            return True
        row = db.one("SELECT artist_id FROM music_albums WHERE id=?", (album_id,))
        return bool(row) and (album_id in self.albums or row["artist_id"] in self.artists)


SORTS = {"title": "sort_title", "added": "added_at DESC", "year": "year DESC, sort_title", "artist": "artist, year"}


def albums(allowed: Allowed, sort: str = "title", artist_id: str | None = None, limit: int = 5000) -> list[dict]:
    cond, params = allowed.where()
    if artist_id:
        cond += " AND artist_id=?"
        params.append(artist_id)
    rows = db.query(f"SELECT * FROM music_albums WHERE {cond} ORDER BY {SORTS.get(sort, 'sort_title')} LIMIT ?",
                    params + [limit])
    return [album_out(a) for a in rows]


def artists(allowed: Allowed) -> list[dict]:
    if allowed.all:
        rows = db.query("SELECT * FROM music_artists ORDER BY sort_name")
    else:
        cond, params = allowed.where()
        rows = db.query(f"SELECT * FROM music_artists WHERE id IN (SELECT artist_id FROM music_albums WHERE {cond}) "
                        "ORDER BY sort_name", params)
    return [artist_out(a) for a in rows]


def album_detail(allowed: Allowed, album_id: str) -> dict | None:
    a = db.one("SELECT * FROM music_albums WHERE id=?", (album_id,))
    if not a or not allowed.album(album_id):
        return None
    tracks = db.query("SELECT * FROM music_tracks WHERE album_id=? ORDER BY COALESCE(disc, 1), track, sort_title",
                      (album_id,))
    return {**album_out(a), "tracks": [track_out(t) for t in tracks]}


def artist_detail(allowed: Allowed, artist_id: str) -> dict | None:
    a = db.one("SELECT * FROM music_artists WHERE id=?", (artist_id,))
    if not a:
        return None
    alb = albums(allowed, "year", artist_id)
    if not alb:
        return None
    return {**artist_out(a), "albums": alb}


def tracks(allowed: Allowed, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    rows = {t["id"]: t for t in db.query(f"SELECT * FROM music_tracks WHERE id IN ({','.join('?' * len(ids))})", ids)}
    return [track_out(rows[i]) for i in ids if i in rows and allowed.album(rows[i]["album_id"])]


def search(allowed: Allowed, q: str) -> dict:
    like = f"%{q.strip()}%"
    cond, params = allowed.where("al")
    alb = db.query(f"SELECT al.* FROM music_albums al WHERE {cond} AND (al.title LIKE ? OR al.artist LIKE ?) "
                   "ORDER BY al.sort_title LIMIT 30", params + [like, like])
    trk = db.query(f"SELECT t.* FROM music_tracks t JOIN music_albums al ON al.id=t.album_id WHERE {cond} "
                   "AND t.title LIKE ? ORDER BY t.sort_title LIMIT 50", params + [like])
    arts = [a for a in artists(allowed) if q.strip().lower() in (a["name"] or "").lower()][:20]
    return {"artists": arts, "albums": [album_out(a) for a in alb], "tracks": [track_out(t) for t in trk]}


def home(allowed: Allowed, profile_id: str) -> dict:
    cond, params = allowed.where("al")
    recent = db.query(f"SELECT al.* FROM music_albums al WHERE {cond} ORDER BY al.added_at DESC LIMIT 30", params)
    played = db.query(
        f"SELECT al.*, MAX(h.at) AS last FROM music_history h JOIN music_tracks t ON t.id=h.track_id "
        f"JOIN music_albums al ON al.id=t.album_id WHERE h.profile_id=? AND {cond} GROUP BY al.id "
        "ORDER BY last DESC LIMIT 20", [profile_id] + params)
    shuffle = db.query(f"SELECT al.* FROM music_albums al WHERE {cond} ORDER BY RANDOM() LIMIT 20", params)
    shelves = []
    if played:
        shelves.append({"id": "played", "title": "Recently Played", "items": [album_out(a) for a in played]})
    if recent:
        shelves.append({"id": "recent", "title": "Recently Added", "items": [album_out(a) for a in recent]})
    if shuffle:
        shelves.append({"id": "rediscover", "title": "Rediscover", "items": [album_out(a) for a in shuffle]})
    return {"shelves": shelves, "stats": stats()}


def played(profile_id: str, track_id: str) -> None:
    db.execute("INSERT INTO music_history (profile_id, track_id, at) VALUES (?, ?, ?)", (profile_id, track_id, time.time()))
    db.execute("DELETE FROM music_history WHERE profile_id=? AND at < (SELECT MIN(at) FROM (SELECT at FROM music_history "
               "WHERE profile_id=? ORDER BY at DESC LIMIT 500))", (profile_id, profile_id))


def stats() -> dict:
    return {k: db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
            for k, t in (("tracks", "music_tracks"), ("albums", "music_albums"), ("artists", "music_artists"))}


def art_ref(owner_id: str) -> str | None:
    """Artwork reference for an album, or for an artist (its newest album's)."""
    if owner_id.startswith("a"):
        row = db.one("SELECT art FROM music_albums WHERE id=?", (owner_id,))
        return row and row["art"]
    row = db.one("SELECT art FROM music_albums WHERE artist_id=? AND art IS NOT NULL ORDER BY year DESC LIMIT 1",
                 (owner_id,))
    return row and row["art"]
