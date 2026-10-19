"""Spotify, through the one account the server is connected to.

Spotify doesn't let other apps play its audio, so playback happens in a Spotify app (on a TV,
phone, Chromecast...) through Spotify Connect; Samedia browses the account (playlists, search),
starts things there and controls them. Controlling playback needs Premium.

Connecting: the admin page sends you to Spotify with PKCE (no client secret on the server).
Spotify only accepts a loopback address as the return address for new apps, so you paste the
address your browser lands on back into the admin page (or, on the NAS itself, it just works).
The account's refresh token is kept in the settings table and never sent to any app.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import db
from .config import config

log = logging.getLogger("samedia.spotify")

REDIRECT = "http://127.0.0.1:8097/api/v1/spotify/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing "
          "playlist-read-private playlist-read-collaborative user-library-read user-read-recently-played user-top-read")
API = "https://api.spotify.com/v1"


class SpotifyError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class Spotify:
    def __init__(self) -> None:
        self._pending: dict | None = None
        self._access: tuple[str, float] | None = None
        self._lock = threading.Lock()

    # ── connecting ──

    def connected(self) -> bool:
        return bool(config.spotify_client_id and db.load_settings().get("spotify_refresh_token"))

    def authorize_url(self, client_id: str) -> str:
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        self._pending = {"verifier": verifier, "state": state, "client_id": client_id, "at": time.time()}
        return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
            "code_challenge_method": "S256", "code_challenge": challenge, "state": state})

    def finish(self, url_or_code: str) -> dict:
        """Take the address Spotify sent the browser to (or just its code) and keep the account."""
        p = self._pending
        if not p or time.time() - p["at"] > 1800:
            raise SpotifyError("Start connecting again (the link is used or too old).", 400)
        text = url_or_code.strip()
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query) if "?" in text else {"code": [text]}
        if params.get("error"):
            raise SpotifyError(f"Spotify said: {params['error'][0]}", 400)
        if params.get("state") and params["state"][0] != p["state"]:
            raise SpotifyError("That address belongs to another attempt.", 400)
        code = (params.get("code") or [""])[0]
        if not code:
            raise SpotifyError("No code in that address.", 400)
        tokens = self._token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                      "client_id": p["client_id"], "code_verifier": p["verifier"]})
        self._pending = None
        db.save_setting("spotify_client_id", p["client_id"])
        config.spotify_client_id = p["client_id"]
        db.save_setting("spotify_refresh_token", tokens["refresh_token"])
        self._access = (tokens["access_token"], time.time() + tokens.get("expires_in", 3600) - 60)
        return self.status()

    def disconnect(self) -> None:
        db.save_setting("spotify_refresh_token", None)
        self._access = None

    def _token_request(self, form: dict) -> dict:
        req = urllib.request.Request("https://accounts.spotify.com/api/token", data=urllib.parse.urlencode(form).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.load(e).get("error_description", "")
            except Exception:  # noqa: BLE001
                pass
            raise SpotifyError(f"Spotify refused: {detail or e.code}", 400) from None
        except OSError:
            raise SpotifyError("Can't reach Spotify.") from None

    def _token(self) -> str:
        with self._lock:
            if self._access and self._access[1] > time.time():
                return self._access[0]
            refresh = db.load_settings().get("spotify_refresh_token")
            if not refresh or not config.spotify_client_id:
                raise SpotifyError("Spotify isn't connected (admin page → Spotify).", 409)
            t = self._token_request({"grant_type": "refresh_token", "refresh_token": refresh,
                                     "client_id": config.spotify_client_id})
            if t.get("refresh_token") and t["refresh_token"] != refresh:
                db.save_setting("spotify_refresh_token", t["refresh_token"])     # Spotify rotates them
            self._access = (t["access_token"], time.time() + t.get("expires_in", 3600) - 60)
            return self._access[0]

    # ── the Web API ──

    def api(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = API + path + ("?" + urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
                            if params else "")
        for attempt in range(2):
            req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else
                                         (b"" if method in ("PUT", "POST") else None),
                                         headers={"Authorization": f"Bearer {self._token()}",
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self._access = None
                    continue
                if e.code == 429 and attempt == 0:
                    time.sleep(min(int(e.headers.get("Retry-After", "1")), 5))
                    continue
                try:
                    msg = json.load(e).get("error", {}).get("message", "")
                except Exception:  # noqa: BLE001
                    msg = ""
                if e.code == 403 and "premium" in msg.lower():
                    raise SpotifyError("Controlling playback needs Spotify Premium.", 403) from None
                if e.code == 404 and "device" in msg.lower():
                    raise SpotifyError("That Spotify device isn't available: open Spotify on it.", 404) from None
                raise SpotifyError(msg or f"Spotify answered {e.code}", e.code if e.code < 500 else 502) from None
            except OSError:
                raise SpotifyError("Can't reach Spotify.") from None
        raise SpotifyError("Spotify didn't answer.")

    # ── what the apps use ──

    def status(self) -> dict:
        if not self.connected():
            return {"connected": False, "client_id": config.spotify_client_id or None}
        me = self.api("GET", "/me") or {}
        return {"connected": True, "client_id": config.spotify_client_id, "user": me.get("display_name") or me.get("id"),
                "premium": me.get("product") == "premium"}

    def devices(self) -> list[dict]:
        out = self.api("GET", "/me/player/devices") or {}
        return [{"id": d["id"], "name": d["name"], "type": d.get("type"), "active": d.get("is_active"),
                 "volume": d.get("volume_percent")} for d in out.get("devices") or [] if d.get("id")]

    def playlists(self) -> list[dict]:
        items, url = [], "/me/playlists"
        params: dict | None = {"limit": 50}
        while url and len(items) < 300:
            page = self.api("GET", url, params) or {}
            items += page.get("items") or []
            nxt = page.get("next")
            url, params = (nxt[len(API):], None) if nxt else (None, None)
        return [playlist_out(p) for p in items if p]

    def playlist(self, pid: str) -> dict:
        p = self.api("GET", f"/playlists/{pid}", {"fields": "id,name,description,images,owner(display_name),uri,"
                                                  "tracks.total"})
        tracks, url, params = [], f"/playlists/{pid}/tracks", {"limit": 100}
        while url and len(tracks) < 500:
            page = self.api("GET", url, params) or {}
            tracks += [i["track"] for i in page.get("items") or [] if i.get("track") and i["track"].get("id")]
            nxt = page.get("next")
            url, params = (nxt[len(API):], None) if nxt else (None, None)
        return {**playlist_out(p), "tracks": [track_out(t) for t in tracks]}

    def search(self, q: str) -> dict:
        r = self.api("GET", "/search", {"q": q, "type": "track,album,artist,playlist", "limit": 20}) or {}
        pick = lambda k: [x for x in (r.get(k) or {}).get("items") or [] if x]
        return {"tracks": [track_out(t) for t in pick("tracks")], "albums": [album_out(a) for a in pick("albums")],
                "artists": [artist_out(a) for a in pick("artists")],
                "playlists": [playlist_out(p) for p in pick("playlists")]}

    def album(self, aid: str) -> dict:
        a = self.api("GET", f"/albums/{aid}")
        return {**album_out(a), "tracks": [track_out({**t, "album": a}) for t in (a.get("tracks") or {}).get("items", [])]}

    def artist(self, rid: str) -> dict:
        a = self.api("GET", f"/artists/{rid}")
        top = self.api("GET", f"/artists/{rid}/top-tracks", {"market": "from_token"}) or {}
        albums = self.api("GET", f"/artists/{rid}/albums", {"include_groups": "album,single", "limit": 30}) or {}
        return {**artist_out(a), "top_tracks": [track_out(t) for t in top.get("tracks") or []],
                "albums": [album_out(x) for x in albums.get("items") or [] if x]}

    def player(self) -> dict | None:
        p = self.api("GET", "/me/player")
        if not p:
            return None
        item = p.get("item") or {}
        return {"device": (p.get("device") or {}).get("name"), "device_id": (p.get("device") or {}).get("id"),
                "playing": p.get("is_playing"), "position": (p.get("progress_ms") or 0) / 1000,
                "shuffle": p.get("shuffle_state"), "repeat": p.get("repeat_state"),
                "volume": (p.get("device") or {}).get("volume_percent"),
                "track": track_out(item) if item.get("id") else None}

    def play(self, device_id: str, context_uri: str | None = None, uris: list[str] | None = None,
             offset: int | None = None) -> None:
        body: dict = {}
        if context_uri:
            body["context_uri"] = context_uri
            if offset is not None:
                body["offset"] = {"position": offset}
        elif uris:
            body["uris"] = uris[:100]
            if offset is not None:
                body["offset"] = {"position": offset}
        try:
            self.api("PUT", "/me/player/play", {"device_id": device_id}, body)
        except SpotifyError as e:
            if e.status != 404:
                raise
            # a device that's asleep: hand playback to it first, then play
            self.api("PUT", "/me/player", body={"device_ids": [device_id], "play": False})
            time.sleep(0.6)
            self.api("PUT", "/me/player/play", {"device_id": device_id}, body)

    def control(self, action: str, value=None, device_id: str | None = None) -> None:
        d = {"device_id": device_id} if device_id else {}
        if action == "pause":
            self.api("PUT", "/me/player/pause", d)
        elif action == "resume":
            self.api("PUT", "/me/player/play", d)
        elif action == "next":
            self.api("POST", "/me/player/next", d)
        elif action == "previous":
            self.api("POST", "/me/player/previous", d)
        elif action == "seek":
            self.api("PUT", "/me/player/seek", {**d, "position_ms": int(float(value or 0) * 1000)})
        elif action == "volume":
            self.api("PUT", "/me/player/volume", {**d, "volume_percent": max(0, min(100, int(value or 0)))})
        elif action == "shuffle":
            self.api("PUT", "/me/player/shuffle", {**d, "state": "true" if value else "false"})
        elif action == "transfer":
            self.api("PUT", "/me/player", body={"device_ids": [device_id], "play": True})
        else:
            raise SpotifyError("Unknown action", 400)

    def radio(self, device_id: str, seed_uri: str) -> int:
        """Keep playing like it: the seed, its artist's top tracks and songs of its genres, mixed.
        (Spotify's own recommendations are closed to new apps; its Autoplay carries on after.)"""
        kind, _, sid = seed_uri.rpartition(":")
        kind = kind.split(":")[-1]
        seed_track = self.api("GET", f"/tracks/{sid}") if kind == "track" else None
        artist_id = (seed_track or {}).get("artists", [{}])[0].get("id") if seed_track else sid
        artist = self.api("GET", f"/artists/{artist_id}") or {}
        top = (self.api("GET", f"/artists/{artist_id}/top-tracks", {"market": "from_token"}) or {}).get("tracks") or []
        pool = [t["uri"] for t in top]
        for genre in (artist.get("genres") or [])[:2]:
            found = self.api("GET", "/search", {"q": f'genre:"{genre}"', "type": "track", "limit": 25}) or {}
            pool += [t["uri"] for t in (found.get("tracks") or {}).get("items") or [] if t]
        first = [seed_track["uri"]] if seed_track else []
        rest = [u for u in dict.fromkeys(pool) if u not in first]
        random.shuffle(rest)
        uris = (first + rest)[:60]
        if not uris:
            raise SpotifyError("Nothing found to play like that.", 404)
        self.play(device_id, uris=uris)
        return len(uris)


def _image(images: list | None, width: int = 300) -> str | None:
    images = [i for i in images or [] if i and i.get("url")]
    if not images:
        return None
    fits = [i for i in images if (i.get("width") or 0) >= width]
    return (min(fits, key=lambda i: i.get("width") or 0) if fits else images[0])["url"]


def track_out(t: dict) -> dict:
    album = t.get("album") or {}
    return {"id": t.get("id"), "uri": t.get("uri"), "kind": "spotify_track", "title": t.get("name"),
            "artist": ", ".join(a["name"] for a in t.get("artists") or []), "album": album.get("name"),
            "album_id": album.get("id"), "duration": (t.get("duration_ms") or 0) / 1000,
            "image": _image(album.get("images"))}


def album_out(a: dict) -> dict:
    return {"id": a.get("id"), "uri": a.get("uri"), "kind": "spotify_album", "title": a.get("name"),
            "artist": ", ".join(x["name"] for x in a.get("artists") or []),
            "year": int(a["release_date"][:4]) if (a.get("release_date") or "")[:4].isdigit() else None,
            "image": _image(a.get("images"))}


def artist_out(a: dict) -> dict:
    return {"id": a.get("id"), "uri": a.get("uri"), "kind": "spotify_artist", "name": a.get("name"),
            "genres": (a.get("genres") or [])[:3], "image": _image(a.get("images"))}


def playlist_out(p: dict) -> dict:
    return {"id": p.get("id"), "uri": p.get("uri"), "kind": "spotify_playlist", "title": p.get("name"),
            "owner": (p.get("owner") or {}).get("display_name"), "tracks": (p.get("tracks") or {}).get("total"),
            "image": _image(p.get("images"))}


spotify = Spotify()
