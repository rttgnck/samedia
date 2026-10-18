"""Subtitle discovery and extraction.

The TV renders every subtitle itself (text as WebVTT cues, Blu-ray PGS as bitmaps), so
subtitles never force a video transcode. Embedded tracks are extracted with ffmpeg in a
single pass per file (all tracks at once, because reading a 50 GB remux is the slow part)
and cached under <data>/cache/subs/<item_id>/.
"""

import logging
import re
import subprocess
import threading
from pathlib import Path

from . import naming
from .config import config

log = logging.getLogger("samedia.subtitles")

_LANG_HINT = re.compile(r"^[a-z]{2,3}(?:[-_][a-z]{2,4})?$", re.I)
_jobs: dict[str, threading.Event] = {}
_jobs_lock = threading.Lock()


def cache_dir(item_id: str) -> Path:
    return config.cache_dir / "subs" / item_id


# ── sidecar files ───────────────────────────────────────────────────

def find_sidecars(video: Path) -> list[dict]:
    """Movie.en.forced.srt / Movie.eng.sup / Movie.srt next to Movie.mkv."""
    out = []
    stem = video.stem
    try:
        entries = sorted(video.parent.iterdir())
    except OSError:
        return out
    for p in entries:
        ext = p.suffix.lower()
        # "Movie 2.srt" must not attach to "Movie.mkv", so require an exact stem match.
        if ext not in naming.SUB_EXTS or not p.name.startswith(stem + "."):
            continue
        rest = [r for r in p.name[len(stem) + 1:-len(ext)].split(".") if r]
        tags = {r.lower() for r in rest}
        lang = next((r for r in rest if _LANG_HINT.match(r) and r.lower() not in ("sdh", "cc", "forced")), None)
        out.append({
            "file": p.name,
            "format": "pgs" if ext == ".sup" else "text",
            "language": lang,
            "forced": "forced" in tags,
            "sdh": bool(tags & {"sdh", "cc", "hi"}),
        })
    return out


# ── embedded extraction ─────────────────────────────────────────────

def _target(item_id: str, stream: dict) -> Path:
    ext = "sup" if stream["format"] == "pgs" else "vtt"
    return cache_dir(item_id) / f"{stream['index']}.{ext}"


def extract_all(item_id: str, video: Path, media: dict) -> None:
    """Extract every supported embedded subtitle track of a file in one ffmpeg pass (blocking)."""
    streams = [s for s in media.get("subtitles", []) if s["format"] in ("text", "pgs")]
    pending = [s for s in streams if not _target(item_id, s).exists()]
    if not pending:
        return

    with _jobs_lock:
        event = _jobs.get(item_id)
        owner = event is None
        if owner:
            event = _jobs[item_id] = threading.Event()
    if not owner:
        event.wait(timeout=1800)
        return

    try:
        out_dir = cache_dir(item_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [config.ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(video)]
        tmp_files = []
        for s in pending:
            final = _target(item_id, s)
            tmp = final.with_name(final.name + ".part")
            tmp_files.append((tmp, final))
            if s["format"] == "pgs":
                cmd += ["-map", f"0:{s['index']}", "-c", "copy", "-f", "sup", str(tmp)]
            else:
                cmd += ["-map", f"0:{s['index']}", "-c:s", "webvtt", "-f", "webvtt", str(tmp)]
        log.info("extracting %d subtitle track(s) from %s", len(pending), video.name)
        subprocess.run(["nice", "-n", "15", *cmd], capture_output=True, timeout=3600)
        for tmp, final in tmp_files:
            if tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(final)
            else:
                tmp.unlink(missing_ok=True)
                final.write_text("WEBVTT\n\n" if final.suffix == ".vtt" else "")
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("subtitle extraction failed for %s: %s", video, exc)
    finally:
        with _jobs_lock:
            _jobs.pop(item_id, None)
        event.set()


def extract_in_background(item_id: str, video: Path, media: dict) -> None:
    threading.Thread(target=extract_all, args=(item_id, video, media), daemon=True).start()


def embedded_path(item_id: str, stream: dict) -> Path | None:
    p = _target(item_id, stream)
    return p if p.exists() else None


def is_extracting(item_id: str) -> bool:
    return item_id in _jobs


# ── sidecar conversion ──────────────────────────────────────────────

def sidecar_as_vtt(item_id: str, sub_file: Path) -> Path:
    """Convert an external .srt/.ass/.ssa to WebVTT (cached). .vtt is served as-is."""
    if sub_file.suffix.lower() == ".vtt":
        return sub_file
    out = cache_dir(item_id) / f"ext-{sub_file.name}.vtt"
    if out.exists() and out.stat().st_mtime >= sub_file.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [config.ffmpeg, "-nostdin", "-v", "error", "-y", "-sub_charenc", "UTF-8", "-i", str(sub_file),
         "-f", "webvtt", str(out)],
        capture_output=True, timeout=60,
    )
    if not out.exists() or out.stat().st_size == 0:
        # Retry without forcing UTF-8 (cp1252 / latin-1 encoded .srt files are common).
        subprocess.run([config.ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(sub_file), "-f", "webvtt", str(out)],
                       capture_output=True, timeout=60)
    return out
