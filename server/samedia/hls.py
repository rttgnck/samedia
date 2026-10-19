"""HLS: a movie as a playlist of short segments, for players that can't seek in a plain file
over HTTP (Samsung's AVPlay refuses every seek there) and for iPhone/iPad.

Segments are cut at the file's own keyframes, so the video is copied untouched (audio is
copied, or converted to E-AC3 when the player can't decode it). The keyframes come from the
container's index (MP4 'stss', Matroska 'Cues'), read in milliseconds; other files fall back
to asking ffprobe for the keyframe before each 6-second mark.

Segments are made on demand by one ffmpeg process per playback session, writing a few
segments ahead of what the player has asked for and pausing (SIGSTOP) beyond that. A request
far from what is being made (a seek) restarts ffmpeg at that segment. Timestamps are the
file's own (+10 s, so they never go negative), identical whichever process made a segment
(see build_cmd for how that is kept the same across ffmpeg versions).
"""

from __future__ import annotations

import asyncio
import bisect
import logging
import math
import os
import shutil
import signal
import struct
import subprocess
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

from .config import config

log = logging.getLogger("samedia.hls")

TARGET = 6.0          # seconds per segment (cut at the first keyframe from there)
AHEAD = 6             # segments made beyond the last one asked for
KEEP_BEHIND = 4       # segments kept behind it (a player may re-read a little)
IDLE_SECONDS = 90     # a session nobody reads from is stopped
MAX_JOBS = 4
SEEK_NUDGE = 0.2      # ffmpeg seeks ~0.13 s before -ss in B-frame files; land on the keyframe itself
CUT_MARGIN = 0.05     # cut times a little early, so rounding never skips the intended keyframe
TS_OFFSET = 10.0      # keeps B-frame decode timestamps positive


# ── keyframes from the container index ─────────────────────────────────

def _read(f, offset: int, size: int) -> bytes:
    f.seek(offset)
    return f.read(size)


def _mp4_boxes(data: bytes, start: int = 0, end: int | None = None):
    """(type, payload_start, payload_end) of the boxes in data[start:end]."""
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield kind.decode("latin-1"), pos + header, min(pos + size, end)
        pos += size


def mp4_keyframes(path: Path, track_ordinal: int) -> list[float] | None:
    """Presentation times of the sync samples of the track-th 'trak' (= ffmpeg's stream index)."""
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        pos, moov = 0, None
        while pos + 8 <= size:
            head = _read(f, pos, 16)
            box_size, kind = struct.unpack(">I4s", head[:8])
            if box_size == 1:
                box_size = struct.unpack(">Q", head[8:16])[0]
            elif box_size == 0:
                box_size = size - pos
            if box_size < 8:
                return None
            if kind == b"moov":
                if box_size > 256 * 1024 * 1024:
                    return None
                moov = _read(f, pos, box_size)
                break
            pos += box_size
    if moov is None:
        return None
    traks = [(s, e) for k, s, e in _mp4_boxes(moov, 8) if k == "trak"]
    if track_ordinal >= len(traks):
        return None
    t_start, t_end = traks[track_ordinal]

    def find(path_names, s, e):
        for name in path_names:
            for k, cs, ce in _mp4_boxes(moov, s, e):
                if k == name:
                    s, e = cs, ce
                    break
            else:
                return None
        return s, e

    mdia = find(["mdia"], t_start, t_end)
    hdlr = find(["hdlr"], *mdia) if mdia else None
    if not hdlr or moov[hdlr[0] + 8:hdlr[0] + 12] != b"vide":
        return None
    mdhd = find(["mdhd"], *mdia)
    version = moov[mdhd[0]]
    timescale = struct.unpack(">I", moov[mdhd[0] + (20 if version == 1 else 12):][:4])[0]
    stbl = find(["minf", "stbl"], *mdia)
    if not stbl or not timescale:
        return None
    boxes = {k: (s, e) for k, s, e in _mp4_boxes(moov, *stbl)}
    if "stts" not in boxes:
        return None

    def table(name, fmt):
        if name not in boxes:
            return None
        s, _ = boxes[name]
        ver = moov[s]
        count = struct.unpack(">I", moov[s + 4:s + 8])[0]
        width = struct.calcsize(fmt)
        rows = [struct.unpack(fmt, moov[s + 8 + i * width:s + 8 + (i + 1) * width]) for i in range(count)]
        return ver, rows

    _, stts = table("stts", ">II")
    stss = table("stss", ">I")
    ctts = table("ctts", ">Ii")          # signed: version 1 says so, version 0 files use it too
    sync = None if stss is None else {r[0] for r in stss[1]}   # no stss: every sample is a keyframe

    # Edit list: the presentation starts media_time into the track
    shift = 0
    edts = find(["edts", "elst"], t_start, t_end)
    if edts:
        s, _ = edts
        ver = moov[s]
        count = struct.unpack(">I", moov[s + 4:s + 8])[0]
        for i in range(count):
            if ver == 1:
                _dur, media_time = struct.unpack(">Qq", moov[s + 8 + i * 20:s + 8 + i * 20 + 16])
            else:
                _dur, media_time = struct.unpack(">Ii", moov[s + 8 + i * 12:s + 8 + i * 12 + 8])
            if media_time != -1:
                shift = media_time
                break

    offsets = []
    for count, off in (ctts[1] if ctts else []):
        offsets.extend([off] * count)
    times, sample, dts = [], 1, 0
    for count, delta in stts:
        for _ in range(count):
            if sync is None or sample in sync:
                cts = offsets[sample - 1] if sample - 1 < len(offsets) else 0
                times.append((dts + cts - shift) / timescale)
            dts += delta
            sample += 1
    return sorted(times)


def _vint(data: bytes, pos: int, keep_marker: bool) -> tuple[int, int]:
    first = data[pos]
    length = 1
    mask = 0x80
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError("bad EBML length")
    value = first if keep_marker else first & (mask - 1)
    for b in data[pos + 1:pos + length]:
        value = (value << 8) | b
    if not keep_marker and value == (1 << (7 * length)) - 1:
        value = -1                                  # unknown size
    return value, pos + length


def _ebml(data: bytes, start: int, end: int):
    pos = start
    while pos < end:
        try:
            eid, pos2 = _vint(data, pos, True)
            size, pos3 = _vint(data, pos2, False)
        except (IndexError, ValueError):
            return
        stop = end if size < 0 else min(pos3 + size, end)
        yield eid, pos3, stop
        if size < 0:
            return
        pos = pos3 + size


def _uint(data: bytes, s: int, e: int) -> int:
    return int.from_bytes(data[s:e], "big") if e > s else 0


SEGMENT, SEEKHEAD, SEEK, SEEKID, SEEKPOS = 0x18538067, 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
INFO, TIMESCALE, TRACKS, TRACKENTRY, TRACKNUM, TRACKTYPE = 0x1549A966, 0x2AD7B1, 0x1654AE6B, 0xAE, 0xD7, 0x83
CUES, CUEPOINT, CUETIME, CUEPOS, CUETRACK, CLUSTER = 0x1C53BB6B, 0xBB, 0xB3, 0xB7, 0xF7, 0x1F43B675


def mkv_keyframes(path: Path, stream_index: int) -> list[float] | None:
    """Cue times of the stream_index-th track (= ffmpeg's stream index), in seconds."""
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        head = _read(f, 0, 64 * 1024)
        seg_data = None
        for eid, s, _e in _ebml(head, 0, len(head)):
            if eid == SEGMENT:
                seg_data = s
                break
        if seg_data is None:
            return None

        def element_at(offset: int, limit: int = 64 * 1024 * 1024):
            blob = _read(f, offset, 12)
            eid, p = _vint(blob, 0, True)
            length, p = _vint(blob, p, False)
            if length < 0 or length > limit:
                return None, None
            return eid, _read(f, offset + p, length)

        found: dict[int, bytes] = {}
        positions: dict[int, int] = {}
        # Walk the top level of the segment (skipping clusters) and follow the SeekHead
        offset = seg_data
        for _ in range(64):
            if offset >= size:
                break
            blob = _read(f, offset, 12)
            try:
                eid, p = _vint(blob, 0, True)
                length, p = _vint(blob, p, False)
            except (IndexError, ValueError):
                break
            if eid in (SEEKHEAD, INFO, TRACKS, CUES) and 0 <= length <= 64 * 1024 * 1024:
                found.setdefault(eid, _read(f, offset + p, length))
                if eid == SEEKHEAD:
                    data = found[SEEKHEAD]
                    for sid, ss, se in _ebml(data, 0, len(data)):
                        if sid != SEEK:
                            continue
                        target = position = None
                        for cid, cs, ce in _ebml(data, ss, se):
                            if cid == SEEKID:
                                target = _uint(data, cs, ce)
                            elif cid == SEEKPOS:
                                position = _uint(data, cs, ce)
                        if target is not None and position is not None:
                            positions[target] = seg_data + position
            if eid == CLUSTER or length < 0:
                break                                   # media data: the rest comes from the SeekHead
            offset += p + length
        for eid in (INFO, TRACKS, CUES):
            if eid not in found and eid in positions:
                got, data = element_at(positions[eid])
                if got == eid:
                    found[eid] = data
    if TRACKS not in found or CUES not in found:
        return None

    scale = 1_000_000
    info = found.get(INFO, b"")
    for eid, s, e in _ebml(info, 0, len(info)):
        if eid == TIMESCALE:
            scale = _uint(info, s, e) or scale
    tracks = []
    data = found[TRACKS]
    for eid, s, e in _ebml(data, 0, len(data)):
        if eid != TRACKENTRY:
            continue
        number = kind = None
        for cid, cs, ce in _ebml(data, s, e):
            if cid == TRACKNUM:
                number = _uint(data, cs, ce)
            elif cid == TRACKTYPE:
                kind = _uint(data, cs, ce)
        tracks.append((number, kind))
    if stream_index < len(tracks) and tracks[stream_index][1] == 1:
        number = tracks[stream_index][0]
    else:
        number = next((n for n, k in tracks if k == 1), None)
    if number is None:
        return None

    times = []
    cues = found[CUES]
    for eid, s, e in _ebml(cues, 0, len(cues)):
        if eid != CUEPOINT:
            continue
        cue_time, mine = None, False
        for cid, cs, ce in _ebml(cues, s, e):
            if cid == CUETIME:
                cue_time = _uint(cues, cs, ce)
            elif cid == CUEPOS:
                for tid, ts, te in _ebml(cues, cs, ce):
                    if tid == CUETRACK and _uint(cues, ts, te) == number:
                        mine = True
        if mine and cue_time is not None:
            times.append(cue_time * scale / 1e9)
    return sorted(set(times))


def ffprobe_keyframes(path: Path, stream_index: int, duration: float) -> list[float]:
    """The keyframe at or before each TARGET mark, from ffprobe (one seek per mark: slow on disks)."""
    marks = ",".join(f"{t:.3f}%+#1" for t in [i * TARGET for i in range(int(duration // TARGET) + 1)])
    cmd = [config.ffprobe, "-v", "error", "-select_streams", str(stream_index), "-read_intervals", marks,
           "-show_entries", "packet=pts_time,dts_time,flags", "-of", "csv=p=0", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600).stdout
    times = set()
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 3 and "K" in parts[2]:
            # AVI packets have no presentation time, only a decode time
            for t in (parts[0], parts[1]):
                try:
                    times.add(float(t))
                    break
                except ValueError:
                    pass
    return sorted(times)


_kf_cache: OrderedDict[tuple, list[float]] = OrderedDict()


def keyframes(path: Path, container: str | None, stream_index: int, duration: float) -> list[float]:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime, stream_index)
    if key in _kf_cache:
        _kf_cache.move_to_end(key)
        return _kf_cache[key]
    started = time.monotonic()
    times = None
    try:
        if container in ("mp4", "mov", "m4v"):
            times = mp4_keyframes(path, stream_index)
        elif container in ("mkv", "webm"):
            times = mkv_keyframes(path, stream_index)
    except (OSError, ValueError, IndexError, struct.error) as exc:
        log.debug("index read failed for %s: %s", path, exc)
        times = None
    source = "index"
    if not _plausible(times, duration):
        times = ffprobe_keyframes(path, stream_index, duration)
        source = "ffprobe"
    log.info("keyframes for %s: %d from %s in %.2fs", path.name, len(times), source, time.monotonic() - started)
    _kf_cache[key] = times
    while len(_kf_cache) > 64:
        _kf_cache.popitem(last=False)
    return times


def _plausible(times: list[float] | None, duration: float) -> bool:
    if not times or times[0] > 10:
        return False
    return duration <= 120 or times[-1] >= min(duration - 120, duration * 0.5)


def boundaries(kf: list[float], duration: float) -> list[float]:
    """Segment start times: 0, then each time the keyframe nearest TARGET after the previous
    start (at least half of TARGET after it)."""
    starts = [0.0]
    while True:
        prev = starts[-1]
        want = prev + TARGET
        i = bisect.bisect_left(kf, want)
        options = [k for k in kf[max(i - 1, 0):i + 1] if k > prev + TARGET / 2]
        if not options:
            break
        nxt = min(options, key=lambda k: abs(k - want))
        if nxt >= duration - 1:
            break
        starts.append(nxt)
    return starts


def playlist(starts: list[float], duration: float) -> str:
    ends = starts[1:] + [duration]
    lens = [max(e - s, 0.001) for s, e in zip(starts, ends)]
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{math.ceil(max(lens))}",
             "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for n, length in enumerate(lens):
        lines += [f"#EXTINF:{length:.6f},", f"{n}.ts"]
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


# ── segment jobs ──────────────────────────────────────────────────────

class Job:
    """One ffmpeg process making segments start.. of one session into its own directory."""

    def __init__(self, session: str, params: tuple, start: int):
        self.session, self.params, self.start = session, params, start
        self.dir = Path(tempfile.mkdtemp(prefix="samedia-hls-"))
        self.proc: asyncio.subprocess.Process | None = None
        self.done: set[int] = set()
        self.wanted = start                 # highest segment asked for
        self.paused = False
        self.exited = False
        self.used = time.monotonic()
        self.error = ""

    def frontier(self) -> int:
        return max(self.done) if self.done else self.start - 1

    def refresh(self) -> None:
        try:
            for line in (self.dir / "list.csv").read_text().splitlines():
                name = line.split(",", 1)[0]
                if name.endswith(".ts"):
                    self.done.add(int(name[:-3]))
        except (OSError, ValueError):
            pass

    def signal(self, stop: bool) -> None:
        if not self.proc or self.exited or stop == self.paused:
            return
        try:
            os.kill(self.proc.pid, signal.SIGSTOP if stop else signal.SIGCONT)
            self.paused = stop
        except ProcessLookupError:
            pass

    async def stop(self) -> None:
        if self.proc and not self.exited:
            self.signal(False)
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
            await self.proc.wait()
        self.exited = True
        shutil.rmtree(self.dir, ignore_errors=True)


def build_cmd(path: str, starts: list[float], n: int, video_index: int, audio_index: int,
              acodec: str, channels: int, out_dir: Path) -> list[str]:
    """ffmpeg making segments n.. of a file.

    The job's own timeline starts at 0 at segment n (seek to just past its keyframe, shift back
    by the same amount), because the segment muxer reads -segment_times relative to the start in
    some ffmpeg versions and as absolute times in others (5.1, in the image). Its -initial_offset,
    applied after the cut decisions, then puts every packet at the file's own time + TS_OFFSET.
    """
    cmd = [config.ffmpeg, "-nostdin", "-v", "error", "-fflags", "+genpts", "-seek_timestamp", "1",
           "-ss", f"{starts[n] + SEEK_NUDGE:.3f}", "-i", path, "-map", f"0:{video_index}"]
    if audio_index >= 0:
        cmd += ["-map", f"0:{audio_index}"]
    cmd += ["-c:v", "copy"]
    if audio_index >= 0:
        if acodec == "eac3":
            cmd += ["-c:a", "eac3", "-b:a", config.eac3_bitrate, "-ac", str(channels)]
        else:
            cmd += ["-c:a", "copy"]
    cuts = [s - starts[n] - CUT_MARGIN for s in starts[n + 1:]]
    cmd += ["-sn", "-dn", "-output_ts_offset", f"{SEEK_NUDGE}", "-avoid_negative_ts", "disabled",
            "-max_muxing_queue_size", "4096", "-muxdelay", "0",
            # each segment is a new MPEG-TS muxer, so continuity counters restart: flag it, or
            # players treat the last frame before every segment boundary as corrupt
            "-f", "segment", "-segment_format", "mpegts",
            "-segment_format_options", "mpegts_copyts=1:mpegts_flags=+initial_discontinuity",
            "-initial_offset", f"{starts[n] + TS_OFFSET:.6f}",
            "-segment_start_number", str(n), "-segment_list", str(out_dir / "list.csv"),
            "-segment_list_type", "csv", "-reset_timestamps", "0"]
    if cuts:
        cmd += ["-segment_times", ",".join(f"{c:.3f}" for c in cuts)]
    else:
        cmd += ["-segment_time", "100000"]
    cmd.append(str(out_dir / "%d.ts"))
    return cmd


class Manager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = asyncio.Lock()
        self.reaper: asyncio.Task | None = None

    async def segment(self, session: str, params: tuple, item: dict, starts: list[float], n: int,
                      audio_index: int, acodec: str, channels: int, timeout: float = 45) -> Path | None:
        """Path of segment n (made now if needed), or None if it couldn't be made."""
        async with self.lock:
            job = self.jobs.get(session)
            if job:
                job.refresh()
            if not self._covers(job, params, n):
                if job:
                    await job.stop()
                job = Job(session, params, n)
                cmd = build_cmd(item["path"], starts, n, item["media"]["video"]["index"], audio_index,
                                acodec, channels, job.dir)
                log.info("hls %s: segments from %d (%.1fs)", session, n, starts[n])
                log.debug("hls %s: %s", session, " ".join(cmd))
                job.proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                                stderr=asyncio.subprocess.PIPE)
                asyncio.create_task(self._watch(job))
                self.jobs[session] = job
                await self._limit()
            job.used = time.monotonic()
            job.wanted = max(job.wanted, n)
            self._pace(job)
            if not self.reaper or self.reaper.done():
                self.reaper = asyncio.create_task(self._reap())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job.refresh()
            if n in job.done:
                self._pace(job)
                path = job.dir / f"{n}.ts"
                return path if path.exists() else None
            if job.exited:
                job.refresh()
                if n in job.done:
                    continue
                log.warning("hls %s: ffmpeg stopped before segment %d: %s", session, n, job.error[-400:])
                return None
            self._pace(job)
            await asyncio.sleep(0.1)
        return None

    @staticmethod
    def _covers(job: Job | None, params: tuple, n: int) -> bool:
        """Whether this job has segment n, or is about to make it."""
        if not job or job.params != params:
            return False
        if n in job.done:
            return (job.dir / f"{n}.ts").exists()
        return not job.exited and job.start <= n <= job.frontier() + 3

    def _pace(self, job: Job) -> None:
        """Run ffmpeg up to AHEAD segments beyond what was asked for; drop old segments."""
        job.refresh()
        job.signal(job.frontier() >= job.wanted + AHEAD)
        for k in list(job.done):
            if k < job.wanted - KEEP_BEHIND:
                (job.dir / f"{k}.ts").unlink(missing_ok=True)

    async def _watch(self, job: Job) -> None:
        err = await job.proc.stderr.read() if job.proc and job.proc.stderr else b""
        await job.proc.wait()
        job.exited = True
        job.error = err.decode(errors="replace")
        job.refresh()
        if job.proc.returncode not in (0, -9, 137) and job.error.strip():
            log.warning("hls %s: ffmpeg exited %s: %s", job.session, job.proc.returncode, job.error[-600:])

    async def _limit(self) -> None:
        while len(self.jobs) > MAX_JOBS:
            oldest = min(self.jobs.values(), key=lambda j: j.used)
            del self.jobs[oldest.session]
            await oldest.stop()

    async def _reap(self) -> None:
        while self.jobs:
            await asyncio.sleep(5)
            async with self.lock:
                now = time.monotonic()
                for session, job in list(self.jobs.items()):
                    if now - job.used > IDLE_SECONDS:
                        del self.jobs[session]
                        await job.stop()
                    else:
                        self._pace(job)

    async def stop_all(self) -> None:
        async with self.lock:
            for job in list(self.jobs.values()):
                await job.stop()
            self.jobs.clear()


manager = Manager()


def index_for(item: dict) -> tuple[list[float], float]:
    """(segment start times, duration) of an item, from its keyframes."""
    media = item.get("media") or {}
    duration = float(media.get("duration") or item.get("duration") or 0)
    kf = keyframes(Path(item["path"]), media.get("container"), media["video"]["index"], duration)
    return boundaries(kf, duration), duration
