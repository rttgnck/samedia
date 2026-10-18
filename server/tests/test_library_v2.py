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
