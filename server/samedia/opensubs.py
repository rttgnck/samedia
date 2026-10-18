"""Foreign-parts subtitles from OpenSubtitles.com, for films whose files have none.

Only used when an API key is set (admin page). Searches with foreign_parts_only=only, prefers a
subtitle made for this very file (OpenSubtitles' file hash), then the most downloaded one.
Results are cached next to the extracted subtitles, and so is "there is none", so each film is
looked up once (again after NONE_DAYS). Downloads count against the account's daily quota
(5 a day without a login), searches don't.
"""

from __future__ import annotations

import json
import logging
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import db
from .config import VERSION, config

log = logging.getLogger("samedia.opensubtitles")

API = "https://api.opensubtitles.com/api/v1"
TIMEOUT = 4
NONE_DAYS = 14
_token: tuple[str, float] | None = None
_down_until = 0.0          # after a failure, playback doesn't wait on OpenSubtitles for a while


def configured() -> bool:
    return bool(config.opensubtitles_key) and time.time() >= _down_until


def _unreachable(exc: Exception) -> None:
    global _down_until
    _down_until = time.time() + 600
    log.warning("OpenSubtitles unreachable, not asking again for 10 minutes: %s", exc)


def _request(method: str, path: str, params: dict | None = None, body: dict | None = None, auth: bool = False):
    url = API + path
    if params:
        # OpenSubtitles wants the parameters sorted and lower-case, or it redirects
        url += "?" + urllib.parse.urlencode(sorted((k, str(v).lower()) for k, v in params.items()))
    headers = {"Api-Key": config.opensubtitles_key, "User-Agent": f"Samedia v{VERSION}",
               "Accept": "application/json", "Content-Type": "application/json"}
    if auth and (token := _login()):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def _login() -> str | None:
    """A login token when an account is set (more downloads a day than without)."""
    global _token
    if not (config.opensubtitles_user and config.opensubtitles_password):
        return None
    if _token and _token[1] > time.time():
        return _token[0]
    try:
        reply = _request("POST", "/login", body={"username": config.opensubtitles_user,
                                                 "password": config.opensubtitles_password})
        _token = (reply["token"], time.time() + 20 * 3600)
        return _token[0]
    except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
        log.warning("OpenSubtitles login failed: %s", exc)
        _token = None
        return None


def moviehash(path: Path) -> str | None:
    """OpenSubtitles' file hash: size + the 64-bit sums of the first and last 64 KB."""
    try:
        size = path.stat().st_size
        if size < 131072:
            return None
        h = size
        with open(path, "rb") as f:
            for offset in (0, size - 65536):
                f.seek(offset)
                h += sum(struct.unpack("<8192Q", f.read(65536)))
        return f"{h & 0xFFFFFFFFFFFFFFFF:016x}"
    except (OSError, struct.error):
        return None


def _query(item: dict) -> dict:
    """How to find this film or episode: TMDB ids when known, else title and year."""
    raw = db.one("SELECT tmdb_id, show_id, season, episode, year FROM items WHERE id=?", (item["id"],)) or {}
    item = {**raw, **{k: v for k, v in item.items() if v is not None}}
    if item.get("kind") == "episode":
        show = db.one("SELECT tmdb_id, title FROM shows WHERE id=?", (item.get("show_id"),)) or {}
        q = {"season_number": item.get("season"), "episode_number": item.get("episode")}
        if show.get("tmdb_id"):
            q["parent_tmdb_id"] = show["tmdb_id"]
        else:
            q["query"] = show.get("title") or item["title"]
        return {k: v for k, v in q.items() if v is not None}
    if item.get("tmdb_id"):
        return {"tmdb_id": item["tmdb_id"]}
    q = {"query": item["title"], "type": "movie"}
    if item.get("year"):
        q["year"] = item["year"]
    return q


def _cache(item_id: str, language: str) -> tuple[Path, Path]:
    from .subtitles import cache_dir
    folder = cache_dir(item_id)
    return folder / f"opensubtitles-forced-{language}.srt", folder / f"opensubtitles-forced-{language}.none"


def cached(item_id: str, language: str = "en") -> Path | None:
    path, _ = _cache(item_id, language)
    return path if path.exists() else None


def forced_subtitle(item: dict, language: str = "en") -> Path | None:
    """A foreign-parts subtitle file for the item in `language`, or None (cached either way)."""
    path, none = _cache(item["id"], language)
    if path.exists():
        return path
    if none.exists() and time.time() - none.stat().st_mtime < NONE_DAYS * 86400:
        return None
    params = {**_query(item), "foreign_parts_only": "only", "languages": language}
    file_hash = moviehash(Path(item["path"])) if item.get("path") else None
    if file_hash:
        params["moviehash"] = file_hash
    try:
        found = _request("GET", "/subtitles", params=params).get("data") or []
    except urllib.error.HTTPError as exc:
        log.warning("OpenSubtitles search failed for %s: %s", item.get("title"), exc)
        return None
    except (urllib.error.URLError, ValueError, OSError) as exc:
        _unreachable(exc)
        return None
    candidates = [r["attributes"] for r in found
                  if r.get("attributes", {}).get("foreign_parts_only") and r["attributes"].get("files")]
    if not candidates:
        none.parent.mkdir(parents=True, exist_ok=True)
        none.touch()
        log.info("OpenSubtitles: no foreign-parts subtitles for %s", item.get("title"))
        return None
    best = max(candidates, key=lambda a: (bool(a.get("moviehash_match")), not a.get("hearing_impaired"),
                                          a.get("download_count") or 0))
    try:
        link = _request("POST", "/download", body={"file_id": best["files"][0]["file_id"]}, auth=True)["link"]
        with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": f"Samedia v{VERSION}"}),
                                    timeout=TIMEOUT * 2) as resp:
            data = resp.read()
    except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
        # e.g. the day's download quota is used up: try again another time
        log.warning("OpenSubtitles download failed for %s: %s", item.get("title"), exc)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    log.info("OpenSubtitles: foreign-parts subtitles for %s (%s, %s)", item.get("title"),
             best.get("release") or "?", "made for this file" if best.get("moviehash_match") else "matched by title")
    return path


def track(item_id: str, language: str) -> dict:
    """The downloaded subtitle as an entry of a playback decision's subtitle_tracks."""
    from .playback import lang_name
    return {"id": f"o-{language}", "source": "opensubtitles", "format": "text",
            "label": f"{lang_name(language) or language} (Foreign parts) · OpenSubtitles",
            "language": language, "forced": True, "forced_reason": "opensubtitles", "default": False,
            "frames": None, "supported": True, "url": f"/api/v1/subs/{item_id}/o-{language}"}
