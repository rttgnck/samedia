"""Which subtitle track covers only the foreign-language parts ("forced" subtitles).

Few files flag such a track. It is also recognised by its title ("Forced", "Foreign parts")
or by having far fewer lines than the full track in the same language - a forced track of an
English film has dozens of lines where the full one has a thousand. Tracks get
`forced: True` and `forced_reason` ("flag", "title", "few lines").
"""

from __future__ import annotations

import re
from pathlib import Path

FORCED_WORDS = re.compile(r"\b(forced|foreign|non[- ]?english|foreign parts|signs)\b", re.I)
FULL_WORDS = re.compile(r"\b(full|sdh|complete|dialogue)\b", re.I)

# Lines per hour below which a track (alone in its language) is taken as forced. Full subtitles
# run at several hundred per hour even in quiet films.
SPARSE_PER_HOUR = 60
# A track with at most this share of the lines of the fullest track in its language is forced.
SHARE_OF_FULL = 0.25

_cue_cache: dict[tuple, int | None] = {}


def cue_count(path: Path) -> int | None:
    """Lines in a subtitle file (SRT/VTT/ASS), cached by size and time."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime)
    if key not in _cue_cache:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            _cue_cache[key] = None
        else:
            if path.suffix.lower() in (".ass", ".ssa"):
                _cue_cache[key] = len(re.findall(r"^Dialogue:", text, re.M))
            else:
                _cue_cache[key] = text.count("-->")
    return _cue_cache[key]


def language_key(code: str | None) -> str | None:
    """'eng', 'en', 'en-US' -> 'english' (so tracks in one language group together)."""
    if not code:
        return None
    from .playback import lang_name
    return (lang_name(code.split("-")[0].lower()) or code).lower()


def infer(tracks: list[dict], duration: float | None) -> list[dict]:
    """Mark forced tracks in place. Each track: language, title/label, forced, frames, format."""
    for t in tracks:
        if t.get("forced"):
            t["forced_reason"] = t.get("forced_reason") or "flag"
        elif FORCED_WORDS.search(t.get("title") or t.get("label") or "") and not FULL_WORDS.search(t.get("title") or ""):
            t["forced"], t["forced_reason"] = True, "title"

    groups: dict[str | None, list[dict]] = {}
    for t in tracks:
        groups.setdefault(language_key(t.get("language")), []).append(t)
    for group in groups.values():
        if any(t.get("forced") for t in group):
            continue                                   # the file already says which one it is
        counted = [t for t in group if lines(t) is not None]
        if not counted:
            continue
        most = max(lines(t) for t in counted)
        for t in counted:
            n = lines(t)
            if len(counted) > 1 and most >= 150 and n <= most * SHARE_OF_FULL:
                t["forced"], t["forced_reason"] = True, "few lines"
            elif len(counted) == 1 and duration and duration > 600 and n < 150 and n / (duration / 3600) < SPARSE_PER_HOUR:
                t["forced"], t["forced_reason"] = True, "few lines"
    return tracks


def lines(track: dict) -> int | None:
    """Comparable line count: a picture (PGS) subtitle shows and clears each line, so halve it."""
    n = track.get("frames")
    if n is None:
        return None
    return n // 2 if track.get("format") == "pgs" else n
