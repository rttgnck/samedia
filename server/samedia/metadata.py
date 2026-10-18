"""Metadata sources: Kodi .nfo files, local artwork, and (optionally) TMDB.

Artwork is stored as a reference string:
    file:/abs/path/poster.jpg   local image next to the media
    tmdb:/abcdef.jpg            TMDB image path, downloaded on first request
"""

import json
import logging
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import config

log = logging.getLogger("samedia.metadata")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


# ── NFO ─────────────────────────────────────────────────────────────

def _text(root: ET.Element, tag: str) -> str | None:
    el = root.find(tag)
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def read_nfo(path: Path) -> dict:
    """Parse a Kodi movie / tvshow / episodedetails NFO. Returns only the fields found."""
    try:
        raw = path.read_bytes()
        # Some NFOs have a trailing IMDb URL after the XML; cut at the closing tag.
        text = raw.decode("utf-8", errors="replace")
        for closing in ("</movie>", "</tvshow>", "</episodedetails>"):
            idx = text.find(closing)
            if idx != -1:
                text = text[: idx + len(closing)]
                break
        root = ET.fromstring(text)
    except (OSError, ET.ParseError):
        return {}

    out: dict = {}
    if title := _text(root, "title"):
        out["title"] = title
    for tag in ("year", "premiered", "aired"):
        if (val := _text(root, tag)) and val[:4].isdigit():
            out["year"] = int(val[:4])
            break
    if plot := _text(root, "plot") or _text(root, "outline"):
        out["plot"] = plot
    rating = _text(root, "rating") or _text(root, "ratings/rating/value")
    if rating:
        try:
            out["rating"] = round(float(rating), 1)
        except ValueError:
            pass
    genres = [g.text.strip() for g in root.findall("genre") if g.text and g.text.strip()]
    if genres:
        out["genres"] = genres
    for uid in root.findall("uniqueid"):
        if uid.get("type") == "tmdb" and uid.text and uid.text.strip().isdigit():
            out["tmdb_id"] = int(uid.text.strip())
    if "tmdb_id" not in out and (tmdb := _text(root, "tmdbid")) and tmdb.isdigit():
        out["tmdb_id"] = int(tmdb)
    return out


def movie_nfo(video: Path) -> dict:
    for candidate in (video.with_suffix(".nfo"), video.parent / "movie.nfo"):
        if candidate.exists():
            return read_nfo(candidate)
    return {}


def episode_nfo(video: Path) -> dict:
    nfo = video.with_suffix(".nfo")
    return read_nfo(nfo) if nfo.exists() else {}


def show_nfo(show_dir: Path) -> dict:
    nfo = show_dir / "tvshow.nfo"
    return read_nfo(nfo) if nfo.exists() else {}


# ── local artwork ───────────────────────────────────────────────────

def _find_image(folder: Path, names: list[str]) -> str | None:
    try:
        existing = {p.name.lower(): p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS}
    except OSError:
        return None
    for name in names:
        for ext in IMAGE_EXTS:
            if (p := existing.get(f"{name}{ext}".lower())) is not None:
                return f"file:{p}"
    return None


def movie_art(video: Path, folder_is_exclusive: bool) -> dict:
    base = video.stem
    poster_names = [f"{base}-poster", f"{base}"]
    fanart_names = [f"{base}-fanart", f"{base}-backdrop"]
    if folder_is_exclusive:
        poster_names += ["poster", "folder", "cover", "movie"]
        fanart_names += ["fanart", "backdrop", "background"]
    return {"poster": _find_image(video.parent, poster_names),
            "backdrop": _find_image(video.parent, fanart_names)}


def episode_art(video: Path) -> dict:
    return {"thumb": _find_image(video.parent, [f"{video.stem}-thumb", video.stem])}


def show_art(show_dir: Path) -> dict:
    if not show_dir.exists():
        return {"poster": None, "backdrop": None}
    return {"poster": _find_image(show_dir, ["poster", "folder", "cover", "show"]),
            "backdrop": _find_image(show_dir, ["fanart", "backdrop", "background"])}


# ── TMDB ────────────────────────────────────────────────────────────

class Tmdb:
    BASE = "https://api.themoviedb.org/3"

    def __init__(self) -> None:
        self._season_cache: dict[tuple[int, int], dict] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(config.tmdb_key)

    def _get(self, path: str, **params) -> dict | None:
        key = config.tmdb_key
        headers = {"Accept": "application/json"}
        if len(key) > 40:          # v4 read access token
            headers["Authorization"] = f"Bearer {key}"
        else:                      # v3 API key
            params["api_key"] = key
        url = f"{self.BASE}{path}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
                return json.loads(r.read())
        except Exception as exc:  # network errors must never break a scan
            log.warning("TMDB request failed (%s): %s", path, exc)
            return None

    def movie(self, title: str, year: int | None, tmdb_id: int | None = None) -> dict:
        if not self.enabled:
            return {}
        if not tmdb_id:
            params = {"query": title}
            if year:
                params["year"] = year
            res = self._get("/search/movie", **params) or {}
            hits = res.get("results") or []
            if not hits and year:
                hits = (self._get("/search/movie", query=title) or {}).get("results") or []
            if not hits:
                return {}
            tmdb_id = hits[0]["id"]
        d = self._get(f"/movie/{tmdb_id}") or {}
        if not d:
            return {}
        return _compact({
            "tmdb_id": tmdb_id,
            "title": d.get("title"),
            "year": int(d["release_date"][:4]) if d.get("release_date") else None,
            "plot": d.get("overview"),
            "rating": round(d["vote_average"], 1) if d.get("vote_average") else None,
            "genres": [g["name"] for g in d.get("genres", [])] or None,
            "poster": f"tmdb:{d['poster_path']}" if d.get("poster_path") else None,
            "backdrop": f"tmdb:{d['backdrop_path']}" if d.get("backdrop_path") else None,
        })

    def show(self, title: str, year: int | None, tmdb_id: int | None = None) -> dict:
        if not self.enabled:
            return {}
        if not tmdb_id:
            params = {"query": title}
            if year:
                params["first_air_date_year"] = year
            hits = (self._get("/search/tv", **params) or {}).get("results") or []
            if not hits:
                return {}
            tmdb_id = hits[0]["id"]
        d = self._get(f"/tv/{tmdb_id}") or {}
        if not d:
            return {}
        return _compact({
            "tmdb_id": tmdb_id,
            "title": d.get("name"),
            "year": int(d["first_air_date"][:4]) if d.get("first_air_date") else None,
            "plot": d.get("overview"),
            "rating": round(d["vote_average"], 1) if d.get("vote_average") else None,
            "genres": [g["name"] for g in d.get("genres", [])] or None,
            "poster": f"tmdb:{d['poster_path']}" if d.get("poster_path") else None,
            "backdrop": f"tmdb:{d['backdrop_path']}" if d.get("backdrop_path") else None,
        })

    def episode(self, show_tmdb_id: int, season: int, episode: int) -> dict:
        if not self.enabled or not show_tmdb_id:
            return {}
        with self._lock:
            key = (show_tmdb_id, season)
            if key not in self._season_cache:
                self._season_cache[key] = self._get(f"/tv/{show_tmdb_id}/season/{season}") or {}
            data = self._season_cache[key]
        for ep in data.get("episodes", []):
            if ep.get("episode_number") == episode:
                return _compact({
                    "title": ep.get("name"),
                    "plot": ep.get("overview"),
                    "rating": round(ep["vote_average"], 1) if ep.get("vote_average") else None,
                    "thumb": f"tmdb:{ep['still_path']}" if ep.get("still_path") else None,
                })
        return {}

    @staticmethod
    def image_url(path: str, width: int) -> str:
        size = "original" if width > 780 else ("w780" if width > 500 else "w500")
        return f"https://image.tmdb.org/t/p/{size}{path}"


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [])}


tmdb = Tmdb()
