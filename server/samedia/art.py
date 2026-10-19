"""Artwork resolution, resizing and caching (TVs choke on 4000px fanart)."""

import hashlib
import logging
import subprocess
import urllib.request
from pathlib import Path

from PIL import Image

from .config import config
from .metadata import Tmdb

log = logging.getLogger("samedia.art")

ALLOWED_WIDTHS = (160, 240, 320, 400, 500, 640, 960, 1280, 1920)


def _snap_width(w: int) -> int:
    return next((a for a in ALLOWED_WIDTHS if a >= w), ALLOWED_WIDTHS[-1])


def resolve(ref: str, width: int, alpha: bool = False) -> Path | None:
    """Return a cached JPEG (PNG with alpha=True, for logos) of `ref` scaled to (at most)
    `width` pixels wide."""
    width = _snap_width(width)
    key = hashlib.sha1(ref.encode()).hexdigest()
    out = config.cache_dir / "art" / key[:2] / f"{key}_{width}.{'png' if alpha else 'jpg'}"
    if out.exists():
        return out
    src = _source(ref, key)
    if src is None:
        return None
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGBA" if alpha else "RGB")
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            if alpha:
                im.save(out, "PNG", optimize=True)
            else:
                im.save(out, "JPEG", quality=84, optimize=True, progressive=True)
        return out
    except OSError as exc:
        log.warning("could not resize %s: %s", ref, exc)
        return None


def _source(ref: str, key: str) -> Path | None:
    if ref.startswith("file:"):
        p = Path(ref[5:])
        return p if p.exists() else None
    if ref.startswith("url:") or ref.startswith("embedded:"):
        orig = config.cache_dir / "art" / key[:2] / f"{key}_orig"
        if not orig.exists():
            orig.parent.mkdir(parents=True, exist_ok=True)
            if ref.startswith("url:"):
                try:
                    req = urllib.request.Request(ref[4:], headers={"User-Agent": "Samedia"})
                    with urllib.request.urlopen(req, timeout=20) as r:
                        orig.write_bytes(r.read())
                except Exception as exc:  # noqa: BLE001
                    log.warning("artwork download failed: %s", exc)
                    return None
            else:   # the picture inside a music file
                done = subprocess.run([config.ffmpeg, "-v", "error", "-y", "-i", ref[9:], "-an", "-map", "0:v:0",
                                       "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", str(orig)],
                                      capture_output=True, timeout=60)
                if done.returncode or not orig.exists():
                    return None
        return orig
    if ref.startswith("tmdb:"):
        orig = config.cache_dir / "art" / key[:2] / f"{key}_orig"
        if not orig.exists():
            try:
                orig.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(Tmdb.image_url(ref[5:], 1280), timeout=15) as r:
                    orig.write_bytes(r.read())
            except Exception as exc:
                log.warning("TMDB image download failed %s: %s", ref, exc)
                return None
        return orig
    return None
