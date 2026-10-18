"""ffprobe wrapper producing a compact, JSON-friendly media summary."""

import json
import logging
import subprocess
from pathlib import Path

from .config import config

log = logging.getLogger("samedia.probe")

TEXT_SUB_CODECS = {"subrip", "ass", "ssa", "mov_text", "webvtt", "text"}
IMAGE_SUB_CODECS = {"hdmv_pgs_subtitle"}

_CONTAINERS = {
    "matroska": "mkv", "webm": "webm", "mov": "mp4", "mp4": "mp4", "mpegts": "ts",
    "avi": "avi", "asf": "asf", "mpeg": "mpeg", "flv": "flv",
}


def container_of(format_name: str, path: Path) -> str:
    first = format_name.split(",")[0]
    if first == "matroska" and path.suffix.lower() == ".webm":
        return "webm"
    if path.suffix.lower() in (".m2ts", ".mts"):
        return "ts"
    return _CONTAINERS.get(first, first)


def _hdr(stream: dict) -> str | None:
    for side in stream.get("side_data_list", []) or []:
        if side.get("side_data_type") == "DOVI configuration record":
            return f"dv{side.get('dv_profile', '')}"
    transfer = stream.get("color_transfer")
    if transfer == "smpte2084":
        return "hdr10"
    if transfer == "arib-std-b67":
        return "hlg"
    return None


def _lang(stream: dict) -> str | None:
    lang = (stream.get("tags") or {}).get("language")
    return None if lang in (None, "und") else lang


def probe(path: Path) -> dict | None:
    cmd = [config.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=120, check=True).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        log.warning("ffprobe failed for %s: %s", path, exc)
        return None

    fmt = data.get("format", {})
    summary = {
        "container": container_of(fmt.get("format_name", ""), path),
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "bitrate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        "video": None,
        "audio": [],
        "subtitles": [],
    }
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        if kind == "video" and summary["video"] is None and not disp.get("attached_pic"):
            fps = None
            if (rate := s.get("avg_frame_rate")) and "/" in rate:
                num, den = rate.split("/")
                fps = round(int(num) / int(den), 3) if int(den) else None
            summary["video"] = {
                "index": s["index"], "codec": s.get("codec_name"), "profile": s.get("profile"),
                "width": s.get("width"), "height": s.get("height"), "fps": fps,
                "bit_depth": int(s["bits_per_raw_sample"]) if str(s.get("bits_per_raw_sample", "")).isdigit() else None,
                "pix_fmt": s.get("pix_fmt"), "hdr": _hdr(s),
            }
        elif kind == "audio":
            codec = s.get("codec_name")
            profile = s.get("profile") or ""
            summary["audio"].append({
                "index": s["index"], "codec": codec, "profile": profile,
                "channels": s.get("channels"), "layout": s.get("channel_layout"),
                "language": _lang(s), "title": tags.get("title"),
                "default": bool(disp.get("default")),
                "atmos": "atmos" in profile.lower() or "Atmos" in (tags.get("title") or ""),
            })
        elif kind == "subtitle":
            codec = s.get("codec_name")
            summary["subtitles"].append({
                "index": s["index"], "codec": codec,
                "format": "text" if codec in TEXT_SUB_CODECS else ("pgs" if codec in IMAGE_SUB_CODECS else "unsupported"),
                "language": _lang(s), "title": tags.get("title"),
                "default": bool(disp.get("default")), "forced": bool(disp.get("forced")),
                "frames": subtitle_frames(s),
            })
    return summary


def subtitle_frames(stream: dict) -> int | None:
    """How many subtitle lines a track has, from what the container already records
    (Matroska statistics tags, MP4 sample counts) - no need to read the file."""
    tags = stream.get("tags") or {}
    for key, value in tags.items():
        if key.upper().startswith("NUMBER_OF_FRAMES") and str(value).isdigit():
            return int(value)
    n = stream.get("nb_frames")
    return int(n) if str(n or "").isdigit() else None


def subtitle_frame_counts(path: Path) -> dict[int, int | None]:
    """{stream index: lines} for the subtitle tracks (headers only, quick)."""
    cmd = [config.ffprobe, "-v", "error", "-select_streams", "s", "-show_entries",
           "stream=index,nb_frames:stream_tags", "-of", "json", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30, check=True).stdout
        return {s["index"]: subtitle_frames(s) for s in json.loads(out).get("streams", [])}
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError, KeyError) as exc:
        log.debug("subtitle frame count failed for %s: %s", path, exc)
        return {}


def keyframe_at_or_before(path: Path, seconds: float, stream_index: int) -> float:
    """Timestamp ffmpeg will actually start from when seeking to `seconds` with -c:v copy."""
    if seconds <= 0:
        return 0.0
    cmd = [
        config.ffprobe, "-v", "error", "-select_streams", str(stream_index),
        "-read_intervals", f"{seconds}%+#1", "-show_entries", "packet=pts_time,flags",
        "-of", "json", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, check=True).stdout
        for pkt in json.loads(out).get("packets", []):
            if "K" in pkt.get("flags", "") and pkt.get("pts_time") not in (None, "N/A"):
                return float(pkt["pts_time"])
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError, ValueError) as exc:
        log.debug("keyframe lookup failed for %s @ %s: %s", path, seconds, exc)
    return seconds
