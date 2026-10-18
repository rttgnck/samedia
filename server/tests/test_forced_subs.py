"""Foreign-parts ("forced") subtitles: recognised in the file, or fetched from OpenSubtitles."""

import json
import time

import pytest

from samedia import db, forced, opensubs
from samedia.config import config


def track(lang, frames=None, title=None, forced_flag=False, fmt="text"):
    return {"language": lang, "frames": frames, "title": title, "forced": forced_flag, "format": fmt, "label": ""}


def test_recognising_forced_tracks():
    # a short English track next to the full one
    tracks = forced.infer([track("eng", 1250), track("eng", 41), track("fre", 1190)], 7200)
    assert [t["forced"] for t in tracks] == [False, True, False] and tracks[1]["forced_reason"] == "few lines"
    # by title, even without line counts
    assert forced.infer([track("eng", title="English (Forced)")], 7200)[0]["forced_reason"] == "title"
    assert not forced.infer([track("eng", title="English SDH Full")], 7200)[0]["forced"]
    # alone in its language but sparse: 35 lines in two hours
    assert forced.infer([track("en", 35)], 7200)[0]["forced"]
    assert not forced.infer([track("en", 900)], 7200)[0]["forced"]
    # a flagged track wins; the others in that language are left alone
    t = forced.infer([track("eng", 1200), track("eng", 40), track("eng", 30, forced_flag=True)], 7200)
    assert [x["forced"] for x in t] == [False, False, True] and t[2]["forced_reason"] == "flag"
    # picture subtitles count each line twice (shown, then cleared)
    assert not forced.infer([track("eng", 1200), track("eng", 900, fmt="pgs")], 7200)[1]["forced"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path / "config")
    monkeypatch.setattr(db, "_conn", None)
    for k in ("tmdb_key", "pin", "opensubtitles_key", "opensubtitles_user", "opensubtitles_password"):
        monkeypatch.setattr(config, k, "")
    monkeypatch.setenv("SAMEDIA_NO_SCAN", "1")
    monkeypatch.setattr(opensubs, "_down_until", 0.0)
    db.connect()
    from fastapi.testclient import TestClient
    from samedia.main import app
    with TestClient(app) as c:
        yield c
    db._conn.close()


def add_movie(tmp_path, subtitles, audio_lang="eng"):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\0" * 200_000)
    media = {"container": "mkv", "duration": 7200,
             "video": {"index": 0, "codec": "h264", "width": 1920, "height": 1080, "hdr": None},
             "audio": [{"index": 1, "codec": "aac", "profile": "", "channels": 2, "language": audio_lang,
                        "default": True, "atmos": False}],
             "subtitles": subtitles}
    db.upsert("items", {"id": "m1", "kind": "movie", "path": str(f), "root": str(tmp_path), "size": 1, "mtime": 1,
                        "title": "Avatar", "sort_title": "avatar", "year": 2009, "tmdb_id": 19995, "duration": 7200,
                        "media": media, "added_at": time.time()})


def sub(index, lang, frames, forced_flag=False):
    return {"index": index, "codec": "subrip", "format": "text", "language": lang, "title": None,
            "default": False, "forced": forced_flag, "frames": frames}


def test_playback_marks_the_foreign_parts_track(client, tmp_path):
    add_movie(tmp_path, [sub(2, "eng", 1300), sub(3, "eng", 60)])
    d = client.post("/api/v1/items/m1/playback", json={}).json()
    t = {x["id"]: x for x in d["subtitle_tracks"]}
    assert t["e3"]["forced"] and t["e3"]["label"].endswith("(Foreign parts)") and not t["e2"]["forced"]


class FakeOpenSubtitles:
    def __init__(self, results):
        self.results, self.calls = results, []

    def request(self, method, path, params=None, body=None, auth=False):
        self.calls.append((method, path, params, body))
        if path == "/subtitles":
            return {"data": self.results}
        if path == "/download":
            return {"link": "https://dl.example/forced.srt"}
        raise AssertionError(path)


class FakeResponse:
    def __init__(self, data): self.data = data
    def read(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_foreign_parts_subtitles_from_opensubtitles(client, tmp_path, monkeypatch):
    add_movie(tmp_path, [sub(2, "eng", 1300)])               # only full English subtitles
    monkeypatch.setattr(config, "opensubtitles_key", "k")
    fake = FakeOpenSubtitles([
        {"attributes": {"foreign_parts_only": True, "moviehash_match": False, "download_count": 900,
                        "files": [{"file_id": 1}], "release": "other"}},
        {"attributes": {"foreign_parts_only": True, "moviehash_match": True, "download_count": 10,
                        "files": [{"file_id": 2}], "release": "this one"}},
        {"attributes": {"foreign_parts_only": False, "files": [{"file_id": 3}]}},
    ])
    monkeypatch.setattr(opensubs, "_request", fake.request)
    srt = b"1\n00:01:00,000 --> 00:01:02,000\nWe come in peace.\n"
    monkeypatch.setattr(opensubs.urllib.request, "urlopen", lambda req, timeout=0: FakeResponse(srt))

    d = client.post("/api/v1/items/m1/playback", json={"subtitle_language": "en"}).json()
    o = next(t for t in d["subtitle_tracks"] if t["source"] == "opensubtitles")
    assert o["forced"] and o["language"] == "en" and o["id"] == "o-en"
    search = fake.calls[0][2]
    assert search["foreign_parts_only"] == "only" and search["tmdb_id"] == 19995 and len(search["moviehash"]) == 16
    assert fake.calls[1][3] == {"file_id": 2}                  # the one made for this file
    vtt = client.get(o["url"]).text
    assert vtt.startswith("WEBVTT") and "We come in peace." in vtt
    # cached: no new lookups
    client.post("/api/v1/items/m1/playback", json={"subtitle_language": "en"})
    assert len(fake.calls) == 2


def test_no_lookup_when_not_needed(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "opensubtitles_key", "k")
    fake = FakeOpenSubtitles([])
    monkeypatch.setattr(opensubs, "_request", fake.request)
    # foreign audio: full subtitles are what to show, nothing to fetch
    add_movie(tmp_path, [sub(2, "eng", 1300)], audio_lang="swe")
    client.post("/api/v1/items/m1/playback", json={"subtitle_language": "en"})
    assert fake.calls == []
    # the file has a foreign-parts track already
    add_movie(tmp_path, [sub(2, "eng", 1300), sub(3, "eng", 20, forced_flag=True)])
    client.post("/api/v1/items/m1/playback", json={"subtitle_language": "en"})
    assert fake.calls == []
    # none on OpenSubtitles: remembered
    add_movie(tmp_path, [sub(2, "eng", 1300)])
    client.post("/api/v1/items/m1/playback", json={"subtitle_language": "en"})
    client.post("/api/v1/items/m1/playback", json={"subtitle_language": "en"})
    assert [c[1] for c in fake.calls] == ["/subtitles"]


def test_opensubtitles_secrets_are_masked(client):
    s = client.put("/api/v1/admin/settings", json={"opensubtitles_key": "abcdef123456", "opensubtitles_user": "me",
                                                   "opensubtitles_password": "hunter2pass"}).json()
    assert s["opensubtitles_key"] == "••••3456" and s["opensubtitles_password"] == "••••pass" and s["opensubtitles_user"] == "me"
    # sending the masked values back keeps the real ones
    client.put("/api/v1/admin/settings", json={"opensubtitles_key": s["opensubtitles_key"],
                                               "opensubtitles_password": s["opensubtitles_password"]})
    assert config.opensubtitles_key == "abcdef123456" and config.opensubtitles_password == "hunter2pass"


def test_moviehash(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(bytes(range(256)) * 1024)
    h = opensubs.moviehash(f)
    assert len(h) == 16 and h == opensubs.moviehash(f)
    assert opensubs.moviehash(tmp_path / "missing") is None
