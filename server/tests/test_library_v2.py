"""Profiles, kids mode, hidden titles, collections and TMDB backfill."""

import time
from pathlib import Path

import pytest

from samedia import db, library, metadata
from samedia.config import config
from samedia.library import Viewer


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path / "config")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(config, "tmdb_key", "")
    db.connect()
    yield tmp_path
    db._conn.close()


def add_movie(mid, title, path, root="/media", cert=None, year=2020, collection_id=None, hint=None):
    db.upsert("items", {"id": mid, "kind": "movie", "path": path, "root": root, "size": 1, "mtime": 1,
                        "title": title, "sort_title": title.lower(), "year": year, "certification": cert,
                        "collection_id": collection_id, "collection_hint": hint, "added_at": time.time()})


def add_profile(pid, kids=False):
    db.upsert("profiles", {"id": pid, "name": pid, "color": "#123456", "kids": int(kids), "created_at": time.time()})


def ids(items):
    return [i["id"] for i in items]


def test_default_profile_exists(fresh_db):
    assert db.query("SELECT id, kids FROM profiles") == [{"id": "default", "kids": 0}]


def test_progress_is_per_profile(fresh_db):
    add_movie("m1", "A", "/media/a.mkv")
    add_profile("kid", kids=False)
    db.save_progress("default", "m1", 600, 3600)
    assert library.continue_watching(Viewer("default"))[0]["position"] == 600
    assert library.continue_watching(Viewer("kid")) == []


def test_kids_profile_only_sees_kid_safe_ratings(fresh_db):
    add_movie("m1", "Toy Story", "/media/toy.mkv", cert="G")
    add_movie("m2", "Up", "/media/up.mkv", cert="PG")
    add_movie("m3", "Alien", "/media/alien.mkv", cert="R")
    add_movie("m4", "Home Video", "/media/home.mkv", cert=None)
    assert ids(library.movies(Viewer("k", kids=True))) == ["m1", "m2"]
    assert len(library.movies(Viewer())) == 4


def test_kids_episodes_follow_show_rating(fresh_db):
    db.upsert("shows", {"id": "s1", "path": "/media/Bluey", "title": "Bluey", "sort_title": "bluey",
                        "certification": "TV-Y", "added_at": 1})
    db.upsert("shows", {"id": "s2", "path": "/media/GoT", "title": "GoT", "sort_title": "got",
                        "certification": "TV-MA", "added_at": 1})
    for sid, eid in (("s1", "e1"), ("s2", "e2")):
        db.upsert("items", {"id": eid, "kind": "episode", "path": f"/media/{eid}.mkv", "root": "/media", "size": 1,
                            "mtime": 1, "title": eid, "sort_title": eid, "show_id": sid, "season": 1, "episode": 1,
                            "added_at": 1})
    kid = Viewer("k", kids=True)
    assert ids(library.shows(kid)) == ["s1"]
    assert ids(library.search(kid, "e")["episodes"]) == ["e1"]


def test_hidden_titles_per_profile(fresh_db):
    add_movie("m1", "A", "/media/a.mkv")
    add_movie("m2", "B", "/media/b.mkv")
    db.execute("INSERT INTO hidden VALUES ('default', 'm1', 1)")
    assert ids(library.movies(Viewer())) == ["m2"]
    add_profile("other")
    assert len(library.movies(Viewer("other"))) == 2
    assert ids(library.hidden(Viewer())) == ["m1"]


def test_hiding_a_collection_hides_its_movies(fresh_db):
    db.upsert("collections", {"id": "c1", "name": "Saga", "sort_title": "saga", "source": "folder"})
    add_movie("m1", "Saga 1", "/media/Saga/1.mkv", collection_id="c1")
    add_movie("m2", "Saga 2", "/media/Saga/2.mkv", collection_id="c1")
    add_movie("m3", "Other", "/media/o.mkv")
    db.execute("INSERT INTO hidden VALUES ('default', 'c1', 1)")
    assert ids(library.movies(Viewer())) == ["m3"]


def test_group_folds_collections_into_one_card(fresh_db):
    db.upsert("collections", {"id": "c1", "name": "Mission Impossible", "sort_title": "mission impossible",
                              "source": "folder"})
    add_movie("m1", "Mission Impossible", "/media/MI/1.mkv", collection_id="c1", year=1996)
    add_movie("m2", "Mission Impossible 2", "/media/MI/2.mkv", collection_id="c1", year=2000)
    add_movie("m3", "Alien", "/media/alien.mkv")
    grouped = library.movies(Viewer(), group=True)
    assert [(g["kind"], g["title"]) for g in grouped] == [("movie", "Alien"), ("collection", "Mission Impossible")]
    col = grouped[1]
    assert col["item_count"] == 2 and col["years"] == "1996–2000"
    detail = library.collection_detail(Viewer(), "c1")
    assert ids(detail["items"]) == ["m1", "m2"]


def test_folder_collections(fresh_db, tmp_path):
    from samedia.scanner import Scanner
    root = tmp_path / "media"
    layout = {
        "m1": "Movies/Mission Impossible/Mission Impossible (1996)/mi1.mkv",
        "m2": "Movies/Mission Impossible/Mission Impossible 2 (2000)/mi2.mkv",
        "m3": "Movies/Mission Impossible/mi3.mkv",
        "m4": "Movies/Alien (1979)/alien.mkv",           # a movie's own folder is not a collection
        "m5": "Movies/Dune Part Two.mkv",                # directly in a library folder
        "m6": "Movies/Star Wars/sw4.mkv",
        "m7": "Movies/Star Wars/sw5.mkv",
    }
    for mid, rel in layout.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        add_movie(mid, mid, str(p), root=str(root))
    Scanner()._refresh_collections()
    cols = {r["name"]: r["id"] for r in db.query("SELECT id, name FROM collections")}
    assert set(cols) == {"Mission Impossible", "Star Wars"}   # "Movies" is a library folder
    by = {r["id"]: r["collection_id"] for r in db.query("SELECT id, collection_id FROM items")}
    assert by["m1"] == by["m2"] == by["m3"] == cols["Mission Impossible"]
    assert by["m6"] == by["m7"] == cols["Star Wars"]
    assert by["m4"] is None and by["m5"] is None


def test_nfo_and_tmdb_collections_need_two_members(fresh_db):
    from samedia.scanner import Scanner
    tmdb = {"tmdb": {"id": 10, "name": "Dune Collection", "poster": "tmdb:/p.jpg", "backdrop": None}}
    add_movie("m1", "Dune", "/media/dune.mkv", hint=tmdb)
    add_movie("m2", "Dune Part Two", "/media/dune2.mkv", hint=tmdb)
    add_movie("m3", "Lonely", "/media/lonely.mkv", hint={"tmdb": {"id": 11, "name": "Solo Collection"}})
    add_movie("m4", "Bourne", "/media/b1.mkv", hint={"nfo": "Bourne"})
    add_movie("m5", "Bourne 2", "/media/b2.mkv", hint={"nfo": "bourne ", "tmdb": {"id": 99, "name": "x"}})
    Scanner()._refresh_collections()
    rows = {r["name"]: r for r in db.query("SELECT * FROM collections")}
    assert set(rows) == {"Dune Collection", "Bourne"}
    assert rows["Dune Collection"]["poster"] == "tmdb:/p.jpg"
    assert db.one("SELECT collection_id FROM items WHERE id='m3'")["collection_id"] is None


def test_backfill_fetches_tmdb_for_titles_scanned_without_a_key(fresh_db, tmp_path, monkeypatch):
    from samedia.scanner import Scanner
    root = tmp_path / "media"
    f = root / "Up (2009)" / "up.mkv"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    add_movie("m1", "Up", str(f), root=str(root), year=2009)
    monkeypatch.setattr(config, "tmdb_key", "k" * 32)
    calls = []

    def fake_movie(title, year, tmdb_id=None):
        calls.append((title, year))
        return {"tmdb_id": 14160, "plot": "Carl flies his house.", "certification": "PG",
                "cast_members": [{"name": "Ed Asner", "role": "Carl"}], "poster": "tmdb:/up.jpg"}
    monkeypatch.setattr(metadata.tmdb, "movie", fake_movie)
    Scanner()._enrich_pending()
    row = db.one("SELECT plot, certification, cast_members, poster, meta_at FROM items WHERE id='m1'")
    assert calls == [("Up", 2009)]
    assert row["certification"] == "PG" and row["poster"] == "tmdb:/up.jpg" and row["meta_at"]
    assert row["cast_members"][0]["name"] == "Ed Asner"
    Scanner()._enrich_pending()
    assert len(calls) == 1          # done once


def test_nfo_certification_set_and_cast(tmp_path):
    nfo = tmp_path / "movie.nfo"
    nfo.write_text("<movie><title>Up</title><mpaa>Rated PG</mpaa><set><name>Pixar</name></set>"
                   "<actor><name>Ed Asner</name><role>Carl</role></actor><tagline>Adventure!</tagline></movie>")
    meta = metadata.read_nfo(nfo)
    assert meta["certification"] == "PG"
    assert meta["collection_hint"] == {"nfo": "Pixar"}
    assert meta["cast_members"] == [{"name": "Ed Asner", "role": "Carl"}]
    assert meta["tagline"] == "Adventure!"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client(fresh_db, monkeypatch):
    monkeypatch.setenv("SAMEDIA_NO_SCAN", "1")
    monkeypatch.setattr(config, "pin", "")
    from fastapi.testclient import TestClient
    from samedia.main import app
    with TestClient(app) as c:
        yield c


def test_profiles_api_and_kids_header(client):
    add_movie("m1", "Toy Story", "/media/toy.mkv", cert="G")
    add_movie("m2", "Alien", "/media/alien.mkv", cert="R")
    kid = client.post("/api/v1/profiles", json={"name": "Kids", "kids": True}).json()
    assert kid["kids"] is True
    assert len(client.get("/api/v1/profiles").json()["profiles"]) == 2
    everyone = client.get("/api/v1/movies").json()["items"]
    kids = client.get("/api/v1/movies", headers={"X-Samedia-Profile": kid["id"]}).json()["items"]
    assert len(everyone) == 2 and ids(kids) == ["m1"]
    # unknown profile falls back to the default profile
    assert len(client.get("/api/v1/movies", headers={"X-Samedia-Profile": "nope"}).json()["items"]) == 2
    assert client.post("/api/v1/profiles", json={"name": "x", "color": "red"}).status_code == 400
    assert client.delete(f"/api/v1/profiles/{kid['id']}").status_code == 200
    assert client.delete("/api/v1/profiles/default").status_code == 400   # last one


def test_hide_api(client):
    add_movie("m1", "A", "/media/a.mkv")
    assert client.post("/api/v1/hidden", json={"id": "m1"}).status_code == 200
    assert client.get("/api/v1/movies").json()["items"] == []
    assert ids(client.get("/api/v1/hidden").json()["items"]) == ["m1"]
    client.delete("/api/v1/hidden/m1")
    assert len(client.get("/api/v1/movies").json()["items"]) == 1
    assert client.post("/api/v1/hidden", json={"id": "nothing"}).status_code == 404


def test_tmdb_key_is_never_sent_back(client, monkeypatch):
    from samedia import scanner as scanner_mod
    monkeypatch.setattr(scanner_mod.scanner, "request_scan", lambda: True)
    r = client.put("/api/v1/admin/settings", json={"tmdb_key": "abcdef1234567890abcdef1234567890"})
    assert r.json()["tmdb_key"] == "••••7890"
    assert config.tmdb_key == "abcdef1234567890abcdef1234567890"
    # The masked value coming back from the admin page leaves the key alone
    client.put("/api/v1/admin/settings", json={"tmdb_key": "••••7890", "server_name": "x"})
    assert config.tmdb_key == "abcdef1234567890abcdef1234567890"
    assert "abcdef" not in client.get("/api/v1/admin/settings").text


def test_info_advertises_features(client):
    assert "profiles" in client.get("/api/v1/info").json()["features"]


def test_rescan_reclassifies_movies_that_are_episodes(fresh_db, tmp_path, monkeypatch):
    """Earth2_E01_* files indexed as movies by an older version become episodes, without re-probing."""
    from samedia import probe
    from samedia.scanner import Scanner, make_id
    root = tmp_path / "media"
    f = root / "Earth 2 (1994)" / "Earth2_E01_First-Contact.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    st = f.stat()
    media = {"container": "mp4", "duration": 2700.0, "video": {"codec": "h264"}, "audio": [], "subtitles": []}
    db.upsert("items", {"id": make_id("m", str(f)), "kind": "movie", "path": str(f), "root": str(root),
                        "size": st.st_size, "mtime": st.st_mtime, "title": "Earth 2", "sort_title": "earth 2",
                        "media": media, "added_at": 123.0})
    monkeypatch.setattr(config, "media_roots", [str(root)])
    monkeypatch.setattr(probe, "probe", lambda p: (_ for _ in ()).throw(AssertionError("re-probed")))
    Scanner().scan()
    rows = db.query("SELECT id, kind, title, season, episode, added_at, show_id FROM items")
    assert len(rows) == 1 and rows[0]["kind"] == "episode"
    assert (rows[0]["season"], rows[0]["episode"], rows[0]["title"]) == (1, 1, "First Contact")
    assert rows[0]["added_at"] == 123.0
    assert db.one("SELECT title FROM shows WHERE id=?", (rows[0]["show_id"],))["title"] == "Earth 2"


def test_bookmarks_api(client):
    add_movie("m1", "Alien", "/media/alien.mkv")
    db.execute("UPDATE items SET duration=7000 WHERE id='m1'")
    r = client.post("/api/v1/items/m1/bookmarks", json={"position": 1234.5}).json()
    assert r["bookmark"]["position"] == 1234.5
    # pressing twice in the same spot doesn't duplicate
    r = client.post("/api/v1/items/m1/bookmarks", json={"position": 1235.0}).json()
    assert len(r["bookmarks"]) == 1
    client.post("/api/v1/items/m1/bookmarks", json={"position": 99999})            # clamped to the duration
    marks = client.get("/api/v1/items/m1/bookmarks").json()["bookmarks"]
    assert [m["position"] for m in marks] == [1234.5, 7000]
    client.put(f"/api/v1/bookmarks/{marks[0]['id']}", json={"label": "Chestburster"})
    assert client.get("/api/v1/items/m1").json()["bookmarks"][0]["label"] == "Chestburster"
    # per profile
    kid = client.post("/api/v1/profiles", json={"name": "Kids"}).json()
    assert client.get("/api/v1/items/m1/bookmarks", headers={"X-Samedia-Profile": kid["id"]}).json()["bookmarks"] == []
    shelf = next(s for s in client.get("/api/v1/home").json()["shelves"] if s["id"] == "bookmarks")
    assert shelf["items"][0]["id"] == "m1" and len(shelf["items"][0]["bookmarks"]) == 2
    client.delete(f"/api/v1/bookmarks/{marks[1]['id']}")
    assert len(client.get("/api/v1/items/m1/bookmarks").json()["bookmarks"]) == 1
    assert client.post("/api/v1/items/nope/bookmarks", json={"position": 1}).status_code == 404


def test_continue_watching_after_20_seconds(fresh_db):
    add_movie("m1", "A", "/media/a.mkv")
    add_movie("m2", "B", "/media/b.mkv")
    db.save_progress("default", "m1", 24, 7000)
    db.save_progress("default", "m2", 12, 7000)
    assert ids(library.continue_watching(Viewer())) == ["m1"]


def test_preview_frame_grid():
    from samedia import frames
    assert frames.snap(123, 7000) == 120
    assert frames.snap(126, 7000) == 130
    assert frames.snap(9999, 600) == 599
    assert frames.snap(-5, None) == 0


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="needs ffmpeg")
def test_preview_frame_endpoint(client, tmp_path):
    import subprocess
    f = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10", "-t", "30",
                    "-c:v", "libx264", "-y", str(f)], check=True)
    add_movie("m1", "Clip", str(f))
    db.execute("UPDATE items SET duration=30, media=? WHERE id='m1'", ('{"container": "mp4"}',))
    r = client.get("/api/v1/items/m1/frame", params={"t": 12, "w": 240})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and len(r.content) > 500
    assert client.get("/api/v1/items/nope/frame", params={"t": 1}).status_code == 404


def test_tv_profile_restrictions(client):
    add_movie("m1", "Toy Story", "/media/toy.mkv", cert="G")
    add_movie("m2", "Alien", "/media/alien.mkv", cert="R")
    kids = client.post("/api/v1/profiles", json={"name": "Kids", "kids": True}).json()
    tv = {"X-Samedia-Device": "TV-KIDSROOM", "X-Samedia-Device-Name": "QN43LS03B"}
    # first contact registers the TV, unrestricted
    assert len(client.get("/api/v1/profiles", headers=tv).json()["profiles"]) == 2
    dev = client.get("/api/v1/admin/devices").json()["devices"][0]
    assert dev["id"] == "TV-KIDSROOM" and dev["name"] == "QN43LS03B" and dev["profiles"] is None
    # restrict the kids' room TV to the Kids profile
    r = client.put("/api/v1/admin/devices/TV-KIDSROOM", json={"profiles": [kids["id"]], "name": "Kids room"})
    assert r.json()["profiles"] == [kids["id"]] and r.json()["name"] == "Kids room"
    assert [p["name"] for p in client.get("/api/v1/profiles", headers=tv).json()["profiles"]] == ["Kids"]
    # asking for the main profile from that TV is refused: it browses as Kids
    movies = client.get("/api/v1/movies", headers={**tv, "X-Samedia-Profile": "default"}).json()["items"]
    assert [m["title"] for m in movies] == ["Toy Story"]
    # the admin page still sees every profile; other TVs are unaffected
    assert len(client.get("/api/v1/profiles", params={"all": True}).json()["profiles"]) == 2
    assert len(client.get("/api/v1/movies", headers={"X-Samedia-Device": "LIVINGROOM"}).json()["items"]) == 2
    # an empty selection isn't allowed; "all" resets the restriction
    assert client.put("/api/v1/admin/devices/TV-KIDSROOM", json={"profiles": []}).status_code == 400
    assert client.put("/api/v1/admin/devices/TV-KIDSROOM", json={"all_profiles": True}).json()["profiles"] is None


def test_new_tvs_get_the_default_profiles(client):
    kids = client.post("/api/v1/profiles", json={"name": "Kids", "kids": True}).json()
    client.put("/api/v1/admin/new-device-profiles", json={"profiles": [kids["id"]]})
    names = [p["name"] for p in client.get("/api/v1/profiles", headers={"X-Samedia-Device": "NEW-TV"}).json()["profiles"]]
    assert names == ["Kids"]
    # a profile that is the only one new TVs (or some TV) get can't be deleted: they'd fall open to all
    r = client.delete(f"/api/v1/profiles/{kids['id']}")
    assert r.status_code == 400 and "the TV" in r.json()["detail"]
    assert client.get("/api/v1/admin/devices").json()["devices"][0]["profiles"] == [kids["id"]]
    client.put("/api/v1/admin/devices/NEW-TV", json={"profiles": [kids["id"], "default"]})
    r = client.delete(f"/api/v1/profiles/{kids['id']}")
    assert r.status_code == 400 and "New TVs" in r.json()["detail"]
    # once nothing depends on it alone, deleting just removes it from the TV's list
    client.put("/api/v1/admin/new-device-profiles", json={"all_profiles": True})
    assert client.delete(f"/api/v1/profiles/{kids['id']}").status_code == 200
    assert client.get("/api/v1/admin/devices").json()["devices"][0]["profiles"] == ["default"]


def test_bad_device_ids_are_ignored(client):
    assert len(client.get("/api/v1/profiles", headers={"X-Samedia-Device": "x" * 200}).json()["profiles"]) == 1
    assert client.get("/api/v1/admin/devices").json()["devices"] == []


def test_profile_avatars(client):
    assert client.get("/api/v1/avatars").json()["avatars"][:2] == ["fox", "panda"]
    main = client.get("/api/v1/profiles").json()["profiles"][0]
    assert main["avatar"] == "fox"
    # new profiles get a picture nobody uses yet
    kids = client.post("/api/v1/profiles", json={"name": "Kids", "kids": True}).json()
    assert kids["avatar"] == "panda"
    assert client.put(f"/api/v1/profiles/{kids['id']}", json={"avatar": "robot"}).json()["avatar"] == "robot"
    assert client.put(f"/api/v1/profiles/{kids['id']}", json={"avatar": "../../etc/passwd"}).status_code == 400
    # "" = no picture, just the initial
    assert client.put(f"/api/v1/profiles/{kids['id']}", json={"avatar": ""}).json()["avatar"] is None
    r = client.get("/avatars/robot.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    for name in db.AVATARS:
        assert client.get(f"/avatars/{name}.svg").status_code == 200


def test_existing_profiles_get_avatars_on_upgrade(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(config, "data_dir", tmp_path / "config")
    monkeypatch.setattr(db, "_conn", None)
    db.connect()
    db._conn.execute("ALTER TABLE profiles DROP COLUMN avatar")
    db._conn.execute("INSERT INTO profiles (id, name, color, kids, created_at) VALUES ('k', 'Kids', '#123456', 1, ?)",
                     (time.time() + 1,))
    db._conn.execute("PRAGMA user_version=3")
    db._conn.close()
    monkeypatch.setattr(db, "_conn", None)
    db.connect()
    assert {r["id"]: r["avatar"] for r in db.query("SELECT id, avatar FROM profiles")} == {"default": "fox", "k": "panda"}
    db._conn.close()


def test_tv_picks_avatars_only_for_its_profiles(client):
    kids = client.post("/api/v1/profiles", json={"name": "Kids", "kids": True}).json()
    tv = {"X-Samedia-Device": "TV-KIDSROOM"}
    client.get("/api/v1/profiles", headers=tv)
    client.put("/api/v1/admin/devices/TV-KIDSROOM", json={"profiles": [kids["id"]]})
    r = client.post(f"/api/v1/profiles/{kids['id']}/avatar", json={"avatar": "dino"}, headers=tv)
    assert r.status_code == 200 and r.json()["avatar"] == "dino"
    assert client.post(f"/api/v1/profiles/{kids['id']}/avatar", json={"avatar": "nope"}, headers=tv).status_code == 400
    # the kids' room TV can't touch the main profile
    assert client.post("/api/v1/profiles/default/avatar", json={"avatar": "robot"}, headers=tv).status_code == 403
    assert client.post("/api/v1/profiles/nope/avatar", json={"avatar": "robot"}, headers=tv).status_code == 403
    assert client.post(f"/api/v1/profiles/{kids['id']}/avatar", json={"avatar": ""}, headers=tv).json()["avatar"] is None
