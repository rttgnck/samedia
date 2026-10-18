"""Metadata sources: Kodi .nfo files, local artwork, and (optionally) TMDB.

Artwork is stored as a reference string:
    file:/abs/path/poster.jpg   local image next to the media
    tmdb:/abcdef.jpg            TMDB image path, downloaded on first request
"""

import json
import logging
import re
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

from .config import config

log = logging.getLogger("samedia.metadata")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Age ratings a kids profile may see (US MPAA + US TV Parental Guidelines).
KIDS_CERTIFICATIONS = ("G", "PG", "TV-Y", "TV-Y7", "TV-Y7-FV", "TV-G", "TV-PG")
_CERT_PREFIX = re.compile(r"^(?:rated\s+|us\s*:\s*|usa\s*:\s*)", re.I)
_KNOWN_CERTS = {"G", "PG", "PG-13", "R", "NC-17", "NR", "UNRATED", "TV-Y", "TV-Y7", "TV-Y7-FV", "TV-G", "TV-PG",
                "TV-14", "TV-MA"}


def normalize_certification(value: str | None) -> str | None:
    """'Rated PG-13', 'US:PG-13', 'pg-13' -> 'PG-13'. Non-US or unknown ratings -> None."""
    if not value:
        return None
    v = _CERT_PREFIX.sub("", value.strip()).upper().replace(" ", "")
    v = {"TVY": "TV-Y", "TVY7": "TV-Y7", "TVG": "TV-G", "TVPG": "TV-PG", "TV14": "TV-14", "TVMA": "TV-MA",
         "PG13": "PG-13", "NC17": "NC-17"}.get(v, v)
    return v if v in _KNOWN_CERTS else None


def kids_safe(certification: str | None) -> bool:
    return certification in KIDS_CERTIFICATIONS


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
    if cert := normalize_certification(_text(root, "mpaa") or _text(root, "certification")):
        out["certification"] = cert
    if tagline := _text(root, "tagline"):
        out["tagline"] = tagline
    if director := _text(root, "director"):
        out["director"] = director
    cast = [{"name": _text(a, "name"), "role": _text(a, "role")} for a in root.findall("actor")]
    cast = [c for c in cast if c["name"]][:12]
    if cast:
        out["cast_members"] = cast
    # Movie sets: <set><name>X</name></set> (Kodi 17+) or <set>X</set> (older)
    set_name = _text(root, "set/name") or _text(root, "set")
    if set_name:
        out["collection_hint"] = {"nfo": set_name}
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
            hit = self._find("/search/movie", "year", title, year, "title", "release_date")
            if not hit:
                return {}
            tmdb_id = hit["id"]
        d = self._get(f"/movie/{tmdb_id}", append_to_response="release_dates,credits") or {}
        if not d:
            return {}
        coll = d.get("belongs_to_collection") or {}
        return _compact({
            "tmdb_id": tmdb_id,
            "title": d.get("title"),
            "year": int(d["release_date"][:4]) if d.get("release_date") else None,
            "plot": d.get("overview"),
            "tagline": d.get("tagline"),
            "rating": round(d["vote_average"], 1) if d.get("vote_average") else None,
            "genres": [g["name"] for g in d.get("genres", [])] or None,
            "poster": f"tmdb:{d['poster_path']}" if d.get("poster_path") else None,
            "backdrop": f"tmdb:{d['backdrop_path']}" if d.get("backdrop_path") else None,
            "certification": _us_movie_certification(d),
            "cast_members": _cast(d),
            "director": ", ".join(c["name"] for c in (d.get("credits") or {}).get("crew", [])
                                  if c.get("job") == "Director")[:200] or None,
            "collection_hint": {"tmdb": {
                "id": coll["id"], "name": coll.get("name"),
                "poster": f"tmdb:{coll['poster_path']}" if coll.get("poster_path") else None,
                "backdrop": f"tmdb:{coll['backdrop_path']}" if coll.get("backdrop_path") else None,
            }} if coll.get("id") else None,
        })

    def show(self, title: str, year: int | None, tmdb_id: int | None = None) -> dict:
        if not self.enabled:
            return {}
        if not tmdb_id:
            hit = self._find("/search/tv", "first_air_date_year", title, year, "name", "first_air_date")
            if not hit:
                return {}
            tmdb_id = hit["id"]
        d = self._get(f"/tv/{tmdb_id}", append_to_response="content_ratings,credits") or {}
        if not d:
            return {}
        return _compact({
            "tmdb_id": tmdb_id,
            "certification": next((normalize_certification(r.get("rating"))
                                   for r in (d.get("content_ratings") or {}).get("results", [])
                                   if r.get("iso_3166_1") == "US"), None),
            "cast_members": _cast(d),
            "title": d.get("name"),
            "year": int(d["first_air_date"][:4]) if d.get("first_air_date") else None,
            "plot": d.get("overview"),
            "rating": round(d["vote_average"], 1) if d.get("vote_average") else None,
            "genres": [g["name"] for g in d.get("genres", [])] or None,
            "poster": f"tmdb:{d['poster_path']}" if d.get("poster_path") else None,
            "backdrop": f"tmdb:{d['backdrop_path']}" if d.get("backdrop_path") else None,
        })

    def _find(self, path: str, year_param: str, title: str, year: int | None,
              name_key: str, date_key: str) -> dict | None:
        """Search TMDB, retrying with cleaned-up variants of the title when nothing convincing comes back."""
        for query in _query_variants(title, year):
            hits: list[dict] = []
            if year:
                hits = (self._get(path, query=query, **{year_param: year}) or {}).get("results") or []
            if not hits:
                hits = (self._get(path, query=query) or {}).get("results") or []
            if hit := _best_match(hits, query, year, name_key, date_key):
                return hit
        return None

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


def _simplify(title: str) -> str:
    t = title.lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"^the ", "", t)


def _deleet(title: str) -> str:
    """"Z00topia" -> "Zootopia": digits used as letters inside words."""
    t = re.sub(r"(?<=[A-Za-z])0|0(?=[A-Za-z])", "o", title)
    return re.sub(r"(?<=[A-Za-z])1(?=[A-Za-z])", "i", t)


def _query_variants(title: str, year: int | None) -> list[str]:
    out = [title, _deleet(title), re.sub(r"\s+the movie$", "", title, flags=re.I)]
    words = title.split()
    # Long titles with extra words ("Free Willy Havets forsvarer & ..."): try shorter
    # prefixes, but only with a known year to keep the match honest.
    if year and len(words) > 3:
        out += [" ".join(words[:n]) for n in range(len(words) - 1, 1, -1)]
    seen, unique = set(), []
    for q in out:
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            unique.append(q)
    return unique[:8]


def _contains_match(want: str, name: str, year_ok: bool) -> bool:
    """One title inside the other: "mandalorian and grogu" in "star wars the mandalorian and grogu"."""
    shorter, longer = sorted((want, name), key=len)
    if len(shorter) < 8 or f" {shorter} " not in f" {longer} ":
        return False
    if year_ok:
        return True
    # Without a year only accept a sequel-like prefix: "free willy 2" -> "free willy 2 the adventure home"
    return longer.startswith(shorter) and (len(shorter.split()) >= 3 or any(c.isdigit() for c in shorter))


def _best_match(hits: list[dict], title: str, year: int | None, name_key: str, date_key: str) -> dict | None:
    """The closest search hit, or None when nothing is a convincing match.

    TMDB always returns *something*; a home video named "Dad's retirement party" must not
    get some random film's poster, plot and age rating.
    """
    want = _simplify(title)
    best, best_score = None, 0.0
    for h in hits[:10]:
        names = [n for n in (h.get(name_key), h.get("original_" + name_key)) if n]
        if not names:
            continue
        hit_year = int(h[date_key][:4]) if (h.get(date_key) or "")[:4].isdigit() else None
        if year and hit_year and abs(hit_year - year) > 1:
            continue
        year_ok = bool(year and hit_year)
        score = max(SequenceMatcher(None, want, _simplify(n)).ratio() for n in names)
        if score < 0.82 and any(_contains_match(want, _simplify(n), year_ok) for n in names):
            score = 0.82
        if score > best_score:
            best, best_score = h, score
    return best if best_score >= 0.82 else None


def _us_movie_certification(d: dict) -> str | None:
    for country in (d.get("release_dates") or {}).get("results", []):
        if country.get("iso_3166_1") != "US":
            continue
        # Prefer theatrical (3) then digital (4) releases that carry a rating
        dates = sorted(country.get("release_dates", []), key=lambda r: {3: 0, 4: 1}.get(r.get("type"), 2))
        for r in dates:
            if cert := normalize_certification(r.get("certification")):
                return cert
    return None


def _cast(d: dict) -> list[dict] | None:
    cast = (d.get("credits") or {}).get("cast", [])[:12]
    return [{"name": c["name"], "role": c.get("character") or None} for c in cast if c.get("name")] or None


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [])}


tmdb = Tmdb()
