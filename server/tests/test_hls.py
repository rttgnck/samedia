"""HLS: keyframes from the container index, the playlist, and segments made on demand."""

import json
import subprocess
import time

import pytest

from samedia import db, hls, probe
from samedia.config import config


def make_clip(path, seconds=40, gop=48):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "ultrafast", "-bf", "2", "-g", str(gop), "-keyint_min", str(gop),
                    "-sc_threshold", "0", "-c:a", "aac", "-b:a", "64k", str(path)], check=True)
    return path


def ffprobe_keyframes(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "0", "-skip_frame", "nokey",
                          "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout
    return [float(x.strip(",")) for x in out.split() if x.strip(",")]


def packets(data: bytes, tmp_path, stream="v"):
    f = tmp_path / f"seg-{time.monotonic_ns()}.ts"
    f.write_bytes(data)
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "packet=pts_time,flags",
                          "-of", "json", str(f)], capture_output=True, text=True).stdout
    return [(float(p["pts_time"]), "K" in p["flags"]) for p in json.loads(out)["packets"] if p.get("pts_time")]


@pytest.mark.parametrize("ext", ["mp4", "mkv"])
def test_keyframes_from_the_index_match_ffprobe(tmp_path, ext):
    clip = make_clip(tmp_path / f"clip.{ext}")
    reader = hls.mp4_keyframes if ext == "mp4" else hls.mkv_keyframes
    mine = reader(clip, 0)
    ref = ffprobe_keyframes(clip)
    assert len(mine) == len(ref) and max(abs(a - b) for a, b in zip(mine, ref)) < 0.002
    # the generic entry point uses the index (and caches it)
    assert hls.keyframes(clip, ext, 0, 40.0) == mine


def test_boundaries_and_playlist():
    kf = [i * 2.0 for i in range(20)]                      # a keyframe every 2 s
    starts = hls.boundaries(kf, 40.0)
    assert starts == [0.0, 6.0, 12.0, 18.0, 24.0, 30.0, 36.0]
    text = hls.playlist(starts, 40.0)
    lines = text.splitlines()
    assert lines[0] == "#EXTM3U" and "#EXT-X-PLAYLIST-TYPE:VOD" in lines and lines[-1] == "#EXT-X-ENDLIST"
    lengths = [float(l[8:-1]) for l in lines if l.startswith("#EXTINF:")]
    assert abs(sum(lengths) - 40.0) < 1e-6 and lines.count("0.ts") == 1
    assert hls.boundaries([0.0, 30.0, 31.0, 90.0], 100.0) == [0.0, 30.0, 90.0]   # long GOPs


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path / "config")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(config, "tmdb_key", "")
    monkeypatch.setattr(config, "pin", "")
    monkeypatch.setenv("SAMEDIA_NO_SCAN", "1")
    monkeypatch.setattr(hls, "manager", hls.Manager())     # its lock belongs to one event loop
    db.connect()
    from fastapi.testclient import TestClient
    from samedia.main import app
    with TestClient(app) as c:
        yield c
    db._conn.close()


def add_clip(path, mid="m1"):
    media = probe.probe(path)
    db.upsert("items", {"id": mid, "kind": "movie", "path": str(path), "root": str(path.parent), "size": 1, "mtime": 1,
                        "title": "Clip", "sort_title": "clip", "year": 2020, "duration": media["duration"],
                        "media": media, "added_at": time.time()})
    return media


@pytest.mark.parametrize("ext", ["mp4", "mkv", "avi"])     # AVI: no index, and no presentation times
def test_segments_on_demand(client, tmp_path, ext):
    clip = make_clip(tmp_path / f"clip.{ext}")
    add_clip(clip)
    d = client.post("/api/v1/items/m1/playback", json={"force": "hls", "session": "tv1"}).json()
    assert d["mode"] == "hls" and d["seekable"] and d["url"].endswith("/index.m3u8") and "/-/m1/tv1/" in d["url"]
    base = d["url"].rsplit("/", 1)[0]
    text = client.get(d["url"]).text
    names = [line for line in text.splitlines() if line.endswith(".ts")]
    starts = hls.boundaries(hls.keyframes(clip, ext, 0, 40.0), 40.0)
    assert len(names) == len(starts) >= 6

    # in order: each segment starts on its keyframe, at the file's own time (+ the fixed offset)
    seen = {}
    for n in range(3):
        r = client.get(f"{base}/{n}.ts")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp2t"
        pk = packets(r.content, tmp_path)
        assert pk[0][1], f"segment {n} must start with a keyframe"
        assert abs(min(p for p, _ in pk) - (starts[n] + hls.TS_OFFSET)) < 0.05
        seen[n] = pk
    assert max(p for p, _ in seen[0]) < min(p for p, _ in seen[1])          # no overlap, in order
    # joined as a player reads them: no frame flagged corrupt at the boundaries
    joined = tmp_path / "joined.ts"
    joined.write_bytes(b"".join(client.get(f"{base}/{n}.ts").content for n in range(3)))
    log = subprocess.run(["ffmpeg", "-nostdin", "-v", "verbose", "-i", str(joined), "-c", "copy", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    assert "corrupt" not in log.lower()

    # a seek: a far segment restarts ffmpeg there, with the same timestamps
    far = len(starts) - 2
    pk = packets(client.get(f"{base}/{far}.ts").content, tmp_path)
    assert pk[0][1] and abs(min(p for p, _ in pk) - (starts[far] + hls.TS_OFFSET)) < 0.05
    # and back: segment 1 made again by a new process is the same video
    again = packets(client.get(f"{base}/1.ts").content, tmp_path)
    assert [p for p, _ in again] == [p for p, _ in seen[1]]

    assert client.get(f"{base}/{len(starts)}.ts").status_code == 404
    assert client.get(f"{base.rsplit('/', 2)[0]}/99/copy/0.ts").status_code == 400   # unknown audio track


def test_hls_needs_the_token_when_a_pin_is_set(client, tmp_path, monkeypatch):
    clip = make_clip(tmp_path / "clip.mp4", seconds=12)
    add_clip(clip)
    monkeypatch.setattr(config, "pin", "1234")
    from samedia.main import access_token
    token = access_token()
    d = client.post("/api/v1/items/m1/playback", json={"force": "hls", "session": "s"},
                    headers={"Authorization": f"Bearer {token}"}).json()
    assert f"/api/v1/hls/{token}/m1/" in d["url"]
    assert client.get(d["url"]).status_code == 200
    assert client.get(d["url"].replace(token, "-")).status_code == 401


def test_players_that_cant_take_the_codec_in_segments_get_something_else(client, tmp_path):
    clip = make_clip(tmp_path / "clip.mp4", seconds=12)
    add_clip(clip)
    caps = {"containers": ["mp4"], "video": ["h264", "hevc"], "audio": ["aac"], "hls_video": ["hevc"]}
    d = client.post("/api/v1/items/m1/playback", json={"force": "hls", "capabilities": caps}).json()
    assert d["mode"] == "direct"


def test_old_codecs_are_re_encoded_in_segments(client, tmp_path):
    """XviD (MPEG-4 Part 2) for a TV that only seeks in segments: H.264 segments, each starting on
    a forced keyframe at the same times as the untouched video would."""
    clip = tmp_path / "xvid.avi"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "30",
                    "-c:v", "mpeg4", "-g", "48", "-c:a", "libmp3lame", "-b:a", "64k", str(clip)], check=True)
    add_clip(clip)
    caps = {"containers": ["avi"], "video": ["h264", "mpeg4"], "audio": ["mp3"], "hls_video": ["h264", "hevc"]}
    d = client.post("/api/v1/items/m1/playback", json={"force": "hls", "session": "tv2", "capabilities": caps}).json()
    assert d["mode"] == "hls" and d["url"].endswith("/copy/h264/index.m3u8")
    base = d["url"].rsplit("/", 1)[0]
    names = [line for line in client.get(d["url"]).text.splitlines() if line.endswith(".ts")]
    starts = hls.boundaries(hls.keyframes(clip, "avi", 0, 30.0), 30.0)
    assert len(names) == len(starts) >= 4
    for n in (0, 1, 3):          # 3: a seek, made by a new ffmpeg from there
        r = client.get(f"{base}/{n}.ts")
        assert r.status_code == 200
        f = tmp_path / f"t{n}.ts"
        f.write_bytes(r.content)
        codec = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_name",
                                "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout.split()
        assert set(codec) == {"h264"}
        pk = packets(r.content, tmp_path)
        assert pk[0][1], f"segment {n} must start with a keyframe"
        assert abs(min(p for p, _ in pk) - (starts[n] + hls.TS_OFFSET)) < 0.05
        assert max(p for p, _ in pk) < (starts[n + 1] if n + 1 < len(starts) else 31) + hls.TS_OFFSET
