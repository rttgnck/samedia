"""Filename / folder parsing for movies and TV episodes (Kodi-style naming)."""

import re
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTS = {
    ".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".mts", ".webm",
    ".wmv", ".mpg", ".mpeg", ".vob", ".flv", ".iso",
}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sup"}
IGNORED_DIRS = {
    "extras", "featurettes", "behind the scenes", "deleted scenes", "interviews",
    "scenes", "shorts", "trailers", "sample", "samples", "other", "@eadir", ".trash",
    "#recycle", "$recycle.bin", "lost+found", ".@__thumb",
}

_EPISODE_PATTERNS = [
    # Show.Name.S01E02E03.title / s1e2 / S01.E02
    re.compile(r"(?P<pre>.*?)[\s._-]*[Ss](?P<season>\d{1,2})[\s._-]?[Ee](?P<ep>\d{1,3})(?:[\s._-]?[Ee-](?P<end>\d{1,3}))?"),
    # Show Name 1x02
    re.compile(r"(?P<pre>.*?)[\s._-]*(?<!\d)(?P<season>\d{1,2})x(?P<ep>\d{2,3})(?:[x-](?P<end>\d{2,3}))?(?!\d)"),
]
_SEASON_DIR = re.compile(r"^(?:season|series|staffel|saison|temporada)[\s._-]*(\d{1,3})$|^s(\d{1,3})$", re.I)
_SPECIALS_DIR = re.compile(r"^specials?$", re.I)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_JUNK = re.compile(
    r"[\s._\[(-]+(?:2160p|1080p|1080i|720p|576p|480p|4k|uhd|hdr10\+?|hdr|dv|dovi|remux|bluray|blu-ray|bdrip|brrip|"
    r"web-?dl|web-?rip|webrip|hdtv|dvdrip|x264|x265|h\.?264|h\.?265|hevc|avc|10bit|atmos|truehd|dts(?:-hd)?|"
    r"ddp?5\.1|aac|ac3|proper|repack|extended|unrated|imax|directors\.cut|criterion)\b.*$",
    re.I,
)
_ARTICLES = re.compile(r"^(the|a|an)\s+", re.I)


@dataclass
class Parsed:
    kind: str                 # movie | episode
    title: str
    year: int | None = None
    show_title: str | None = None
    show_dir: Path | None = None
    season: int | None = None
    episode: int | None = None
    episode_end: int | None = None


def clean(name: str) -> str:
    # Leading site / release-group tags: "[UsaBit com] Pirates of Silicon Valley"
    name = re.sub(r"^\s*(?:\[[^\]]*\]\s*)+", "", name)
    name = _JUNK.sub("", name)
    name = re.sub(r"[._]", " ", name)
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"[\s\-\[(]+$", "", name)
    name = re.sub(r"^[\s\-\])]+", "", name)
    if name.endswith(")") and name.count("(") < name.count(")"):
        name = name[:-1].rstrip()
    return name.strip()


def sort_title(title: str) -> str:
    return _ARTICLES.sub("", title).lower()


def split_title_year(name: str) -> tuple[str, int | None]:
    """'The Matrix (1999) 1080p' -> ('The Matrix', 1999)."""
    matches = list(_YEAR.finditer(name))
    # Ignore a year that *is* the whole title (e.g. "1917" or "2012").
    for m in reversed(matches):
        before = name[: m.start()]
        if clean(before):
            return clean(before), int(m.group(1))
    return clean(name), None


def is_ignored(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    # Hidden files, incl. macOS "._name" AppleDouble files left on non-Mac disks (not videos)
    if path.name.startswith("."):
        return True
    for part in rel.parts[:-1]:
        if part.lower() in IGNORED_DIRS or part.startswith("."):
            return True
    stem = path.stem.lower()
    return stem.endswith(("-sample", ".sample", "-trailer")) or stem == "sample"


def _show_dir_for(path: Path, root: Path) -> Path | None:
    """For .../Show/Season 1/ep.mkv returns .../Show; for .../Show/ep.mkv returns .../Show."""
    parent = path.parent
    if parent == root:
        return None
    if _SEASON_DIR.match(parent.name) or _SPECIALS_DIR.match(parent.name):
        return parent.parent if parent.parent != root.parent else None
    return parent


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", split_title_year(s)[0].lower())


def _same_name(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    return bool(na and nb) and (na.startswith(nb) or nb.startswith(na))


def parse(path: Path, root: Path, folder_exclusive: bool = False) -> Parsed:
    """folder_exclusive: the video's folder holds only this movie (folder-per-movie layout)."""
    stem = path.stem
    for pattern in _EPISODE_PATTERNS:
        m = pattern.search(stem)
        if not m:
            continue
        season, ep = int(m.group("season")), int(m.group("ep"))
        end = int(m.group("end")) if m.group("end") else None
        show_dir = _show_dir_for(path, root)
        pre = clean(m.group("pre"))
        if show_dir is not None and pre and show_dir == path.parent and not _same_name(pre, show_dir.name):
            show_dir = None  # e.g. "Downloads/Show.S01E01.mkv": the folder is not the show
        if show_dir is not None and show_dir != root:
            show_title, show_year = split_title_year(show_dir.name)
        else:
            show_title, show_year = split_title_year(m.group("pre"))
            show_dir = path.parent / f"#{show_title}"   # virtual show for flat folders
        after = stem[m.end():]
        ep_title = clean(after) or f"Episode {ep}"
        return Parsed(
            kind="episode", title=ep_title, year=show_year, show_title=show_title or "Unknown Show",
            show_dir=show_dir, season=season, episode=ep, episode_end=end if end and end > ep else None,
        )

    # ".../Show/Season 2/03 - Title.mkv" with no SxxEyy in the filename.
    season_dir = _SEASON_DIR.match(path.parent.name)
    numbered = re.match(r"^(?:e|ep|episode)?[\s._-]*(\d{1,3})(?!\d)[\s._-]*(.*)$", stem, re.I)
    if season_dir and numbered and path.parent.parent != root.parent:
        show_dir = path.parent.parent
        show_title, show_year = split_title_year(show_dir.name)
        ep = int(numbered.group(1))
        return Parsed(
            kind="episode", title=clean(numbered.group(2)) or f"Episode {ep}", year=show_year,
            show_title=show_title, show_dir=show_dir,
            season=int(season_dir.group(1) or season_dir.group(2)), episode=ep,
        )

    # Folder-per-movie layouts usually name the folder better than the file.
    name = stem
    if path.parent != root and _YEAR.search(path.parent.name) and (folder_exclusive or not _YEAR.search(stem)):
        name = path.parent.name
    title, year = split_title_year(name)
    return Parsed(kind="movie", title=title or stem, year=year)
