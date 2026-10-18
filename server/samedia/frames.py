"""Still frames for the scrubbing preview: one JPEG per 10 s of a video, made on demand with
ffmpeg (fast keyframe seek) and cached under <data>/cache/frames."""

import logging
import subprocess
import threading
from pathlib import Path

from .config import config

log = logging.getLogger("samedia.frames")

STEP = 10                      # seconds between distinct preview frames
WIDTHS = (240, 320, 480)
_slots = threading.Semaphore(2)  # at most two ffmpeg grabs at once (gentle on a Pi)


def snap(t: float, duration: float | None) -> int:
    """Round to the preview grid and keep inside the video."""
    t = max(0, int(round(t / STEP)) * STEP)
    if duration:
        t = min(t, max(0, int(duration) - 1))
    return t


def frame(item_id: str, path: str, t: float, width: int, duration: float | None) -> Path | None:
    width = next((w for w in WIDTHS if w >= width), WIDTHS[-1])
    t = snap(t, duration)
    out = config.cache_dir / "frames" / item_id / f"{t}_{width}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.jpg")
    cmd = [config.ffmpeg, "-nostdin", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-q:v", "6", "-y", str(tmp)]
    with _slots:
        if out.exists():
            return out
        try:
            subprocess.run(cmd, capture_output=True, timeout=20, check=True)
            tmp.replace(out)
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("preview frame failed for %s at %ss: %s", item_id, t, exc)
            tmp.unlink(missing_ok=True)
            return None
    return out if out.exists() else None
