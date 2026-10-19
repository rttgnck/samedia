"""Music: files become albums and artists, with art; apps browse, stream and lock screens to it."""

import subprocess
import time

import pytest
from PIL import Image

from samedia import db, music, remote
from samedia.config import config


def tone(path, *, title=None, artist=None, album=None, album_artist=None, track=None, disc=None, year=None,
         cover=None, seconds=2):
    """A short silent audio file with the given tags (and an embedded cover)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    tags = {"title": title, "artist": artist, "album": album, "album_artist": album_artist, "track": track,
            "disc": disc, "date": year}
    for k, v in tags.items():
        if v is not None:
            cmd += ["-metadata", f"{k}={v}"]
    cmd += ["-t", str(seconds), "-c:a", "libmp3lame" if path.suffix == ".mp3" else "flac", str(path)]
    subprocess.run(cmd, check=True)


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path / "config")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(config, "pin", "")
    monkeypatch.setattr(config, "acoustid_key", "")
    monkeypatch.setenv("SAMEDIA_NO_SCAN", "1")
    monkeypatch.setattr(remote, "hub", remote.Hub())
    monkeypatch.setattr(music, "cover_art_url", lambda artist, album: (None, None))     # no internet in tests
    db.connect()
    root = tmp_path / "Music"
    Image.new("RGB", (60, 60), (200, 40, 40)).save(tmp_path / "red.jpg")
    # tagged album, cover inside the files
    for n, t in enumerate(["Intro", "Song Two", "Finale"], 1):
        tone(root / "Daft Punk" / "Discovery" / f"{n:02d} {t}.mp3", title=t, artist="Daft Punk", album="Discovery",
             track=n, year=2001, cover=tmp_path / "red.jpg")
    # two discs, cover.jpg in the album folder
    for d in (1, 2):
        tone(root / "Pink Floyd" / "The Wall" / f"CD{d}" / "01 - Part.flac", title=f"Part {d}", artist="Pink Floyd",
             album="The Wall", track=1, disc=d, year=1979)
    Image.new("RGB", (60, 60), (20, 20, 200)).save(root / "Pink Floyd" / "The Wall" / "cover.jpg")
    # a compilation without album artists
    tone(root / "Now 1999" / "01.mp3", title="A", artist="Britney Spears", album="Now 1999")
    tone(root / "Now 1999" / "02.mp3", title="B", artist="Blur", album="Now 1999")
    # no tags at all: named from the folders
    tone(root / "Radiohead" / "OK Computer (1997)" / "03 - Subterranean Homesick Alien.mp3")
    # a movie folder's audio isn't music in an "auto" folder
    (tmp_path / "Movies" / "Heat (1995)").mkdir(parents=True)
    (tmp_path / "Movies" / "Heat (1995)" / "Heat.mkv").write_bytes(b"x")
    tone(tmp_path / "Movies" / "Heat (1995)" / "theme.mp3", title="Theme", artist="Elliot Goldenthal")
    yield tmp_path
    db._conn.close()


def scan(tmp_path, kinds=None):
    kinds = kinds or {}
    music.scan([(tmp_path / "Music", kinds.get("Music", "music")), (tmp_path / "Movies", kinds.get("Movies", "auto"))])
    music.find_album_art()


def test_files_become_albums_and_artists(library):
    scan(library)
    allowed = music.Allowed(None)
    albums = {a["title"]: a for a in music.albums(allowed)}
    assert set(albums) == {"Discovery", "The Wall", "Now 1999", "OK Computer"}      # not the movie's theme
    assert albums["The Wall"]["track_count"] == 2 and albums["The Wall"]["year"] == 1979   # one album, two discs
    assert albums["Now 1999"]["artist"] == "Various Artists"
    ok = music.album_detail(allowed, albums["OK Computer"]["id"])
    t = ok["tracks"][0]
    assert ok["artist"] == "Radiohead" and ok["year"] == 1997 and t["title"] == "Subterranean Homesick Alien" \
        and t["track"] == 3
    disc = music.album_detail(allowed, albums["Discovery"]["id"])
    assert [x["title"] for x in disc["tracks"]] == ["Intro", "Song Two", "Finale"]
    names = [a["name"] for a in music.artists(allowed)]
    assert names == sorted(names, key=music.sort_name) and "Daft Punk" in names
    # art: the files' own picture, or the folder's cover
    assert music.art_ref(albums["Discovery"]["id"]).startswith("embedded:")
    assert music.art_ref(albums["The Wall"]["id"]).endswith("cover.jpg")
    assert music.art_ref(albums["Discovery"]["artist_id"]).startswith("embedded:")


def test_rescans_follow_the_files(library):
    scan(library)
    (library / "Music" / "Now 1999" / "02.mp3").unlink()
    scan(library)
    now = next(a for a in music.albums(music.Allowed(None)) if a["title"] == "Now 1999")
    assert now["track_count"] == 1 and now["artist"] == "Britney Spears"
    # a folder set to hold movies has no music
    scan(library, {"Music": "movies"})
    assert music.albums(music.Allowed(None)) == []


@pytest.fixture
def client(library):
    config.media_roots = [str(library / "Music")]
    scan(library)
    from fastapi.testclient import TestClient
    from samedia.main import app
    with TestClient(app) as c:
        yield c


def test_the_api_browses_and_streams(client, library):
    home = client.get("/api/v1/music/home").json()
    assert home["stats"]["albums"] == 4 and home["shelves"][0]["id"] == "recent"
    disc = next(a for a in client.get("/api/v1/music/albums?sort=year").json()["albums"] if a["title"] == "Discovery")
    album = client.get(f"/api/v1/music/albums/{disc['id']}").json()
    first = album["tracks"][0]
    r = client.get(f"/api/v1/music/stream/{first['id']}.mp3", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100 and r.headers["content-type"] == "audio/mpeg"
    wall = next(a for a in client.get("/api/v1/music/albums").json()["albums"] if a["title"] == "The Wall")
    flac = client.get(f"/api/v1/music/albums/{wall['id']}").json()["tracks"][0]
    mp3 = client.get(f"/api/v1/music/stream/{flac['id']}?format=mp3")
    assert mp3.status_code == 200 and mp3.content[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3") or mp3.content[:2] == b"\xff\xfb"
    assert client.get(f"/api/v1/music/art/{disc['id']}?w=160").headers["content-type"] == "image/jpeg"
    found = client.get("/api/v1/music/search?q=punk").json()
    assert found["artists"][0]["name"] == "Daft Punk" and found["albums"][0]["title"] == "Discovery"
    assert client.post("/api/v1/music/played", json={"track_id": first["id"]}).status_code == 200
    assert client.get("/api/v1/music/home").json()["shelves"][0]["id"] == "played"


def test_a_locked_screen_plays_only_approved_music(client):
    h = {"X-Samedia-Device": "tv-kids"}
    client.get("/api/v1/info", headers=h)
    client.get("/api/v1/profiles", headers=h)          # registers the screen
    kids = client.post("/api/v1/profiles", json={"name": "Kids", "kids": True}).json()
    albums = {a["title"]: a for a in client.get("/api/v1/music/albums").json()["albums"]}
    r = client.put("/api/v1/admin/devices/tv-kids/lock", json={"profile": kids["id"], "music_only": True,
                                                                 "albums": [albums["Discovery"]["id"]],
                                                                 "playlists": ["37i9dQZF1DX0XUsuxWHRQd"]})
    assert r.status_code == 200
    assert client.get("/api/v1/device", headers=h).json() == {"id": "tv-kids", "locked": True, "music_only": True,
                                                              "profile": kids["id"]}
    assert [p["id"] for p in client.get("/api/v1/profiles", headers=h).json()["profiles"]] == [kids["id"]]
    assert client.get("/api/v1/home", headers=h).status_code == 403              # no movies
    assert [a["title"] for a in client.get("/api/v1/music/albums", headers=h).json()["albums"]] == ["Discovery"]
    wall = albums["The Wall"]["id"]
    assert client.get(f"/api/v1/music/albums/{wall}", headers=h).status_code == 404
    track = client.get(f"/api/v1/music/albums/{wall}").json()["tracks"][0]["id"]
    assert client.get(f"/api/v1/music/stream/{track}", headers=h).status_code == 403
    assert client.get("/api/v1/spotify/search?q=x", headers=h).status_code == 403
    # a remote can't send it a film, nor music that isn't approved
    with client.websocket_connect("/api/v1/remote/ws?device=tv-kids&name=Kids%20room&kind=tv") as tv:
        tv.send_json({"type": "ping"}); tv.receive_json()
        assert client.post("/api/v1/remote/players/tv-kids/command",
                           json={"action": "play_music", "tracks": [track]}).status_code == 403
        ok = client.get(f"/api/v1/music/albums/{albums['Discovery']['id']}").json()["tracks"]
        r = client.post("/api/v1/remote/players/tv-kids/command",
                        json={"action": "play_music", "tracks": [track] + [t["id"] for t in ok], "index": 1})
        assert r.status_code == 200
        msg = tv.receive_json()
        assert msg["tracks"] == [t["id"] for t in ok] and msg["profile_id"] == kids["id"]
    assert client.delete("/api/v1/admin/devices/tv-kids/lock").status_code == 200
    assert client.get("/api/v1/home", headers=h).status_code == 200


def test_folders_say_what_they_hold(client, library):
    s = client.put("/api/v1/admin/settings", json={"root_kinds": {str(library / "Music"): "music", "/x": "nonsense"}})
    assert s.json()["root_kinds"] == {str(library / "Music"): "music"}
    listing = client.get("/api/v1/admin/folders", params={"path": str(library)}).json()
    assert {"Music", "Movies"} <= {f["name"] for f in listing["folders"]}
    assert client.get("/api/v1/admin/music").json()["albums"] == 4


def test_spotify_connects_once_and_locked_screens_get_only_their_playlists(client, monkeypatch):
    from samedia import spotify as sp
    calls = []

    def token_request(form):
        calls.append(form)
        return {"access_token": "acc", "refresh_token": "ref-1", "expires_in": 3600}

    def api(method, path, params=None, body=None):
        calls.append((method, path, body))
        if path == "/me":
            return {"display_name": "Me", "product": "premium"}
        if path == "/me/playlists":
            return {"items": [{"id": "p1", "name": "Kids", "uri": "spotify:playlist:p1", "tracks": {"total": 3}},
                              {"id": "p2", "name": "Mine", "uri": "spotify:playlist:p2", "tracks": {"total": 9}}]}
        return None

    monkeypatch.setattr(sp.spotify, "_token_request", token_request)
    monkeypatch.setattr(sp.spotify, "api", api)
    r = client.post("/api/v1/admin/spotify/connect", json={"client_id": "0123456789abcdef0123456789abcdef"})
    url = r.json()["url"]
    assert "code_challenge=" in url and "redirect_uri=http%3A%2F%2F127.0.0.1" in url
    state = url.split("state=")[1].split("&")[0]
    done = client.post("/api/v1/admin/spotify/finish",
                       json={"url": f"http://127.0.0.1:8097/api/v1/spotify/callback?code=abc&state={state}"})
    assert done.json() == {"connected": True, "client_id": "0123456789abcdef0123456789abcdef", "user": "Me",
                           "premium": True}
    assert calls[0]["code_verifier"] and db.load_settings()["spotify_refresh_token"] == "ref-1"
    assert "ref-1" not in client.get("/api/v1/admin/settings").text            # never sent out
    assert [p["id"] for p in client.get("/api/v1/spotify/playlists").json()["playlists"]] == ["p1", "p2"]
    # a screen locked to the Kids playlist
    h = {"X-Samedia-Device": "tv-den"}
    client.get("/api/v1/profiles", headers=h)
    client.put("/api/v1/admin/devices/tv-den/lock", json={"profile": "default", "playlists": ["p1"]})
    assert [p["id"] for p in client.get("/api/v1/spotify/playlists", headers=h).json()["playlists"]] == ["p1"]
    assert client.post("/api/v1/spotify/play", headers=h,
                       json={"device_id": "d", "context_uri": "spotify:playlist:p2"}).status_code == 403
    assert client.post("/api/v1/spotify/play", headers=h,
                       json={"device_id": "d", "context_uri": "spotify:playlist:p1"}).status_code == 200
    assert ("PUT", "/me/player/play", {"context_uri": "spotify:playlist:p1"}) in calls


def test_title_cards_pick_a_logo_and_a_different_text_free_scene(monkeypatch):
    from samedia import metadata
    monkeypatch.setattr(config, "tmdb_key", "k" * 32)
    images = {"logos": [{"file_path": "/fr.png", "iso_639_1": "fr", "vote_average": 9},
                        {"file_path": "/en.png", "iso_639_1": "en", "vote_average": 5},
                        {"file_path": "/en.svg", "iso_639_1": "en", "vote_average": 8}],
              "backdrops": [{"file_path": "/main.jpg", "iso_639_1": None, "vote_average": 9, "width": 3840},
                            {"file_path": "/titled.jpg", "iso_639_1": "en", "vote_average": 8, "width": 3840},
                            {"file_path": "/small.jpg", "iso_639_1": None, "vote_average": 7, "width": 780},
                            {"file_path": "/scene.jpg", "iso_639_1": None, "vote_average": 6, "width": 1920}]}
    monkeypatch.setattr(metadata.tmdb, "_get", lambda path, **p: images)
    assert metadata.tmdb.cards("movie", 1, "tmdb:/main.jpg") == {"logo": "tmdb:/en.png", "scene": "tmdb:/scene.jpg"}
