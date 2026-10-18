"""Playback decisions and ffmpeg stream sessions.

Three modes, cheapest first:
    direct     the TV reads the original file over HTTP (Range requests). No CPU used.
    remux      video is copied untouched; only the audio is converted (DTS/TrueHD -> E-AC3)
               and/or the container is rewritten to MPEG-TS. Light on CPU (a Pi 5 copes easily).
    transcode  video is re-encoded to H.264 1080p. Last resort for codecs the TV cannot decode;
               a Pi 5 has no hardware encoder, so expect this to struggle above 1080p.
"""

import asyncio
import logging
from pathlib import Path

from . import probe
from .config import config

log = logging.getLogger("samedia.playback")

# What a 2022 Samsung (Tizen 6.5) plays natively through AVPlay. The TV app sends its own
# list (user-adjustable in its settings); this is only the fallback.
DEFAULT_CAPS = {
    "containers": ["mkv", "mp4", "webm", "ts", "avi", "mpeg"],
    "video": ["h264", "hevc", "vp9", "av1", "mpeg2video", "mpeg4", "vc1"],
    "audio": ["aac", "ac3", "eac3", "mp3", "mp2", "flac", "opus", "vorbis", "pcm_s16le", "pcm_s24le", "pcm_bluray"],
    "dolby_vision": False,
    "max_width": 3840,
}

AUDIO_LABELS = {
    "dts": "DTS", "truehd": "TrueHD", "eac3": "Dolby Digital+", "ac3": "Dolby Digital", "aac": "AAC",
    "flac": "FLAC", "opus": "Opus", "mp3": "MP3", "vorbis": "Vorbis",
}
LANGS = {
    "eng": "English", "en": "English", "spa": "Spanish", "es": "Spanish", "fre": "French", "fra": "French",
    "fr": "French", "ger": "German", "deu": "German", "de": "German", "ita": "Italian", "it": "Italian",
    "jpn": "Japanese", "ja": "Japanese", "kor": "Korean", "ko": "Korean", "chi": "Chinese", "zho": "Chinese",
    "zh": "Chinese", "por": "Portuguese", "pt": "Portuguese", "rus": "Russian", "ru": "Russian",
    "dut": "Dutch", "nld": "Dutch", "nl": "Dutch", "swe": "Swedish", "sv": "Swedish", "nor": "Norwegian",
    "dan": "Danish", "fin": "Finnish", "pol": "Polish", "hin": "Hindi", "ara": "Arabic", "tur": "Turkish",
}
MIME = {"mkv": "video/x-matroska", "mp4": "video/mp4", "webm": "video/webm", "ts": "video/mp2t",
        "avi": "video/x-msvideo", "mpeg": "video/mpeg"}


def lang_name(code: str | None) -> str | None:
    return LANGS.get((code or "").lower(), code.upper() if code else None)


def channel_label(ch: int | None) -> str:
    return {1: "Mono", 2: "Stereo", 6: "5.1", 7: "6.1", 8: "7.1"}.get(ch or 0, f"{ch}ch" if ch else "")


def audio_codec_key(a: dict) -> str:
    # DTS-HD MA and DTS:X also report codec "dts"; the variant lives in `profile`.
    return a["codec"] or ""


def _audio_label(a: dict) -> str:
    codec = audio_codec_key(a)
    name = AUDIO_LABELS.get(codec, codec.upper())
    if codec == "dts" and a.get("profile") and a["profile"] != "DTS":
        name = a["profile"]                        # "DTS-HD MA", "DTS:X" ...
    if a.get("atmos"):
        name += " Atmos"
    parts = [lang_name(a.get("language")), name, channel_label(a.get("channels"))]
    label = " · ".join(p for p in parts if p)
    if a.get("title") and a["title"].lower() not in label.lower():
        label += f" — {a['title']}"
    return label


def _pick_audio(audio: list[dict], requested: int | None, prefer_lang: str | None, caps: dict) -> dict | None:
    if not audio:
        return None
    if requested is not None:
        for a in audio:
            if a["index"] == requested:
                return a
    pool = audio
    if prefer_lang:
        same = [a for a in audio if (a.get("language") or "").lower().startswith(prefer_lang.lower()[:2])]
        pool = same or audio
    # Prefer the default track, then a track the TV can play without conversion.
    for a in pool:
        if a.get("default"):
            return a
    for a in pool:
        if audio_codec_key(a) in caps["audio"]:
            return a
    return pool[0]


def subtitle_tracks(item: dict) -> list[dict]:
    """Every subtitle track of an item, with the ones that only cover foreign-language parts
    marked forced (see forced.py)."""
    from . import forced as forced_subs
    media = item.get("media") or {}
    out = []
    for s in media.get("subtitles", []):
        out.append({
            "id": f"e{s['index']}", "source": "embedded", "format": s["format"],
            "label": " · ".join(p for p in [lang_name(s.get("language")) or "Unknown", s.get("title")] if p),
            "title": s.get("title"), "language": s.get("language"), "forced": s["forced"], "default": s["default"],
            "frames": s.get("frames"), "supported": s["format"] in ("text", "pgs"),
            "url": f"/api/v1/subs/{item['id']}/e{s['index']}" if s["format"] in ("text", "pgs") else None,
        })
    folder = Path(item["path"]).parent if item.get("path") else None
    for i, s in enumerate(item.get("sidecar_subs") or []):
        label = lang_name(s.get("language")) or "External"
        if s.get("sdh"):
            label += " SDH"
        frames = forced_subs.cue_count(folder / s["file"]) if folder and s["format"] == "text" else None
        out.append({
            "id": f"x{i}", "source": "external", "format": s["format"], "label": label + " · file",
            "title": s["file"], "language": s.get("language"), "forced": s.get("forced", False), "default": False,
            "frames": frames, "supported": True, "url": f"/api/v1/subs/{item['id']}/x{i}",
        })
    forced_subs.infer(out, media.get("duration") or item.get("duration"))
    for t in out:
        if t["forced"]:
            t["label"] += " (Forced)" if t.get("forced_reason") == "flag" else " (Foreign parts)"
        t.pop("title", None)
    return out


def decide(item: dict, caps: dict | None, *, audio_index: int | None = None, start: float = 0,
           force: str | None = None, prefer_lang: str | None = None, session: str = "default",
           token: str = "-") -> dict:
    caps = {**DEFAULT_CAPS, **(caps or {})}
    media = item.get("media") or {}
    video = media.get("video")
    audio = media.get("audio", [])
    path = Path(item["path"])
    reasons, warnings = [], []

    chosen = _pick_audio(audio, audio_index, prefer_lang, caps)

    container_ok = media.get("container") in caps["containers"]
    video_ok = bool(video) and video["codec"] in caps["video"] and (video.get("width") or 0) <= caps["max_width"]
    audio_ok = chosen is None or audio_codec_key(chosen) in caps["audio"]

    if video and (video.get("hdr") or "").startswith("dv") and not caps.get("dolby_vision"):
        profile = video["hdr"][2:]
        if profile == "5":
            warnings.append("Dolby Vision profile 5 has no HDR10 fallback, so colours will look wrong on this TV.")
        else:
            warnings.append("Dolby Vision is not supported by this TV; playing the HDR10 base layer.")

    if not container_ok:
        reasons.append(f"container {media.get('container')} not supported")
    if not video_ok:
        reasons.append(f"video {video['codec'] if video else 'missing'} not supported")
    if not audio_ok:
        reasons.append(f"audio {audio_codec_key(chosen)} not supported")

    # HLS (segments of the untouched video) when the player asks for it and can take this
    # video inside MPEG-TS segments (iPhone/iPad can't take HEVC there)
    hls_ok = bool(video) and video_ok and video["codec"] in caps.get("hls_video", caps["video"])
    if force == "hls" and not hls_ok:
        force = None if container_ok and audio_ok and video_ok else "transcode"
        reasons.append("segments not possible for this video")

    if force == "transcode" or not video_ok:
        mode = "transcode"
    elif force == "hls":
        mode = "hls"
    elif force == "remux" or not (container_ok and audio_ok):
        # players that seek well in segments (iPhone/iPad) get those rather than a one-way stream
        mode = "hls" if caps.get("prefer_hls") and hls_ok and force != "remux" else "remux"
    else:
        mode = "direct"
    # MPEG-TS output must carry a video codec the player takes there (Apple: H.264 only)
    if mode == "remux" and video and video["codec"] not in caps.get("ts_video", caps["video"]):
        mode = "transcode"
        reasons.append(f"video {video['codec']} not supported in a stream")
    if force:
        reasons.append(f"forced {force}")

    acodec = "copy" if audio_ok and mode != "transcode" else "eac3"
    if mode == "transcode" and chosen and audio_codec_key(chosen) in ("aac", "ac3", "eac3"):
        acodec = "copy"

    duration = media.get("duration") or item.get("duration")
    result = {
        "mode": mode,
        "reasons": reasons,
        "warnings": warnings,
        "duration": duration,
        "audio_index": chosen["index"] if chosen else None,
        "audio_ordinal": audio.index(chosen) if chosen else 0,
        "audio_tracks": [{
            "index": a["index"], "label": _audio_label(a), "codec": audio_codec_key(a),
            "channels": a.get("channels"), "language": a.get("language"), "default": a.get("default"),
            "supported": audio_codec_key(a) in caps["audio"],
        } for a in audio],
        "subtitle_tracks": subtitle_tracks(item),
        "video": video,
    }

    if mode == "hls":
        audio_param = result["audio_index"] if chosen else -1
        result.update(url=f"/api/v1/hls/{token}/{item['id']}/{session}/{audio_param}/{acodec}/index.m3u8",
                      start_offset=0, seekable=True, mime="application/vnd.apple.mpegurl")
        if acodec == "eac3" and chosen:
            result["warnings"].append(f"Converting {_audio_label(chosen)} audio to Dolby Digital+ 5.1 for the TV.")
    elif mode == "direct":
        # With the file's extension: Samsung's player seems to judge a URL without one as a live
        # stream, and refuses every seek in it (InvalidValuesError)
        ext = media.get("container") if media.get("container") in MIME else None
        result.update(url=f"/api/v1/stream/{item['id']}/direct" + (f".{ext}" if ext else ""), start_offset=0, seekable=True,
                      mime=MIME.get(media.get("container"), "video/x-matroska"))
    else:
        offset = start
        if mode == "remux" and start > 0 and video:
            offset = probe.keyframe_at_or_before(path, start, video["index"])
        params = f"start={offset:.3f}&audio={result['audio_index'] if chosen else -1}&acodec={acodec}&session={session}"
        if mode == "transcode":
            params += "&vcodec=h264"
        result.update(url=f"/api/v1/stream/{item['id']}/remux?{params}", start_offset=offset, seekable=False,
                      mime=MIME["ts"])
        if acodec == "eac3" and chosen:
            result["warnings"].append(f"Converting {_audio_label(chosen)} audio to Dolby Digital+ 5.1 for the TV.")
    return result


# ── ffmpeg sessions ─────────────────────────────────────────────────

_sessions: dict[str, asyncio.subprocess.Process] = {}


def build_ffmpeg_cmd(item: dict, start: float, audio_index: int, acodec: str, vcodec: str) -> list[str]:
    media = item["media"] or {}
    video = media.get("video")
    cmd = [config.ffmpeg, "-nostdin", "-v", "error", "-fflags", "+genpts"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", item["path"]]
    if video:
        cmd += ["-map", f"0:{video['index']}"]
    if audio_index >= 0:
        cmd += ["-map", f"0:{audio_index}"]

    if vcodec == "h264":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-g", "48",
                "-vf", "scale='min(1920,iw)':-2", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]

    if audio_index >= 0:
        if acodec == "eac3":
            stream = next((a for a in media.get("audio", []) if a["index"] == audio_index), {})
            channels = min(stream.get("channels") or 6, 6)
            cmd += ["-c:a", "eac3", "-b:a", config.eac3_bitrate, "-ac", str(channels)]
        else:
            cmd += ["-c:a", "copy"]

    cmd += ["-sn", "-dn", "-avoid_negative_ts", "make_zero", "-max_muxing_queue_size", "4096",
            "-f", "mpegts", "-muxdelay", "0", "pipe:1"]
    return cmd


async def stream_ffmpeg(session: str, cmd: list[str]):
    """Async generator yielding MPEG-TS bytes; replaces any earlier stream of the same session."""
    old = _sessions.pop(session, None)
    if old and old.returncode is None:
        old.kill()
    log.info("ffmpeg session %s: %s", session, " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _sessions[session] = proc
    try:
        while True:
            chunk = await proc.stdout.read(256 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        if _sessions.get(session) is proc:
            del _sessions[session]
        if proc.returncode not in (0, -9, 137):
            err = (await proc.stderr.read()).decode(errors="replace")[-2000:]
            if err.strip():
                log.warning("ffmpeg session %s exited %s: %s", session, proc.returncode, err)


def active_sessions() -> int:
    return sum(1 for p in _sessions.values() if p.returncode is None)
