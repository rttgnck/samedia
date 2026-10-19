"""Players keep a WebSocket open; remotes list them and send commands."""

import time

import pytest

from samedia import db, remote
from samedia.config import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path / "config")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(config, "pin", "")
    monkeypatch.setattr(config, "tmdb_key", "")
    monkeypatch.setenv("SAMEDIA_NO_SCAN", "1")
    monkeypatch.setattr(remote, "hub", remote.Hub())
    db.connect()
    db.upsert("items", {"id": "m1", "kind": "movie", "path": "/media/a.mkv", "root": "/media", "size": 1, "mtime": 1,
                        "title": "Alien", "sort_title": "alien", "year": 1979, "duration": 7000, "added_at": time.time()})
    from fastapi.testclient import TestClient
    from samedia.main import app
    with TestClient(app) as c:
        yield c
    db._conn.close()


def test_players_report_and_take_commands(client):
    with client.websocket_connect("/api/v1/remote/ws?device=tv-living&name=Samsung%20Frame&kind=tv") as tv:
        tv.send_json({"type": "ping"})
        assert tv.receive_json() == {"type": "pong"}
        tv.send_json({"type": "state", "item_id": "m1", "title": "Alien", "position": 600, "duration": 7000,
                      "playing": True, "profile_id": "default"})
        tv.send_json({"type": "ping"}); tv.receive_json()          # make sure the state was handled
        players = client.get("/api/v1/remote/players", headers={"X-Samedia-Device": "ios-ipad"}).json()["players"]
        assert len(players) == 1 and players[0]["name"] == "Samsung Frame" and players[0]["kind"] == "tv"
        now = players[0]["now_playing"]
        assert now["item_id"] == "m1" and now["playing"] and 600 <= now["position"] < 610
        # the asking device doesn't see itself
        assert client.get("/api/v1/remote/players", headers={"X-Samedia-Device": "tv-living"}).json()["players"] == []

        # play from the iPad on the TV, as the iPad's profile, from 12:00
        r = client.post("/api/v1/remote/players/tv-living/command", headers={"X-Samedia-Profile": "default"},
                        json={"action": "play", "item_id": "m1", "position": 720})
        assert r.status_code == 200
        assert tv.receive_json() == {"type": "command", "action": "play", "item_id": "m1", "position": 720,
                                     "profile_id": "default"}
        client.post("/api/v1/remote/players/tv-living/command", json={"action": "seek", "position": 30})
        assert tv.receive_json() == {"type": "command", "action": "seek", "position": 30}
        client.post("/api/v1/remote/players/tv-living/command", json={"action": "pause"})
        assert tv.receive_json() == {"type": "command", "action": "pause"}
        assert client.post("/api/v1/remote/players/tv-living/command", json={"action": "dance"}).status_code == 400
        assert client.post("/api/v1/remote/players/tv-living/command",
                           json={"action": "play", "item_id": "nope"}).status_code == 404
    # gone when it disconnects
    assert client.get("/api/v1/remote/players").json()["players"] == []
    assert client.post("/api/v1/remote/players/tv-living/command", json={"action": "pause"}).status_code == 404


def test_a_restricted_tv_only_plays_its_profiles(client):
    kids = client.post("/api/v1/profiles", json={"name": "Kids", "kids": True}).json()
    with client.websocket_connect("/api/v1/remote/ws?device=tv-kids&name=Kids%20room") as tv:
        client.put("/api/v1/admin/devices/tv-kids", json={"profiles": [kids["id"]]})
        r = client.post("/api/v1/remote/players/tv-kids/command", headers={"X-Samedia-Profile": "default"},
                        json={"action": "play", "item_id": "m1"})
        assert r.status_code == 403
        r = client.post("/api/v1/remote/players/tv-kids/command", json={"action": "play", "item_id": "m1",
                                                                       "profile_id": kids["id"]})
        assert r.status_code == 200 and tv.receive_json()["profile_id"] == kids["id"]


def test_reconnecting_replaces_the_old_socket_and_pin_is_checked(client, monkeypatch):
    with client.websocket_connect("/api/v1/remote/ws?device=tv-a&name=A"):
        with client.websocket_connect("/api/v1/remote/ws?device=tv-a&name=A again") as again:
            again.send_json({"type": "ping"}); again.receive_json()
            assert [p["name"] for p in client.get("/api/v1/remote/players").json()["players"]] == ["A again"]   # one entry, latest name
    monkeypatch.setattr(config, "pin", "1234")
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/remote/ws?device=tv-b") as ws:
            ws.receive_json()


def test_tvs_take_arrow_keys_and_volume(client):
    with client.websocket_connect("/api/v1/remote/ws?device=tv-den&name=Den&kind=tv&can=keys,volume,teleport") as tv:
        tv.send_json({"type": "ping"}); tv.receive_json()
        players = client.get("/api/v1/remote/players").json()["players"]
        assert players[0]["can"] == ["keys", "volume"]                    # unknown extras dropped
        client.post("/api/v1/remote/players/tv-den/command", json={"action": "key", "key": "left"})
        assert tv.receive_json() == {"type": "command", "action": "key", "key": "left"}
        client.post("/api/v1/remote/players/tv-den/command", json={"action": "volume", "key": "mute"})
        assert tv.receive_json() == {"type": "command", "action": "volume", "key": "mute"}
        assert client.post("/api/v1/remote/players/tv-den/command", json={"action": "key", "key": "power"}).status_code == 400
        assert client.post("/api/v1/remote/players/tv-den/command", json={"action": "volume", "key": "left"}).status_code == 400


def test_devices_say_which_app_and_version_they_run(client):
    h = {"X-Samedia-Device": "gtv-1", "X-Samedia-Device-Name": "Den TV", "X-Samedia-App": "googletv/0.9.0"}
    client.get("/api/v1/home", headers=h)
    dev = next(d for d in client.get("/api/v1/admin/devices").json()["devices"] if d["id"] == "gtv-1")
    assert dev["app"] == "googletv" and dev["version"] == "0.9.0" and dev["address"] and not dev["online"]
    # an update shows at once; nonsense is ignored
    client.get("/api/v1/home", headers={**h, "X-Samedia-App": "googletv/1.0.0"})
    client.get("/api/v1/home", headers={**h, "X-Samedia-App": "toaster/9"})
    dev = next(d for d in client.get("/api/v1/admin/devices").json()["devices"] if d["id"] == "gtv-1")
    assert dev["version"] == "1.0.0" and dev["app"] == "googletv"
    # and over the remote-control socket
    with client.websocket_connect("/api/v1/remote/ws?device=tv-x&name=Frame&kind=tv&app=tv%2F0.9.1") as tv:
        tv.send_json({"type": "ping"}); tv.receive_json()
        dev = next(d for d in client.get("/api/v1/admin/devices").json()["devices"] if d["id"] == "tv-x")
        assert dev["app"] == "tv" and dev["version"] == "0.9.1" and dev["online"]


def test_playback_failures_are_kept_for_finding_the_title(client):
    h = {"X-Samedia-Device": "tv-y", "X-Samedia-Device-Name": "Frame"}
    r = client.post("/api/v1/events", headers=h, json={"kind": "playback_error", "item_id": "m1", "mode": "hls",
                                                         "error": "PLAYER_ERROR_NOT_SUPPORTED_FORMAT", "recovered": False})
    assert r.status_code == 200
    assert client.post("/api/v1/events", json={"kind": "party"}).status_code == 400
    ev = client.get("/api/v1/admin/events").json()["events"]
    assert ev[0]["title"] == "Alien" and ev[0]["device"] == "Frame" and ev[0]["error"].endswith("FORMAT")
