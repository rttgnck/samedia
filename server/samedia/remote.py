"""Players and remotes.

Every app (TV, iPhone/iPad, Android) keeps a WebSocket open to the server while it runs, so it
can be told what to play, and reports what it is playing. Any app can then list the players
and control them: play a title on another screen, hand over what it is playing ("send to"),
pause, seek, stop.

Player -> server:  {"type": "state", "item_id", "title", "position", "duration", "playing", "profile_id"}
                   {"type": "state", "item_id": null}            (stopped)
Server -> player:  {"type": "command", "action": "play", "item_id", "position", "profile_id"}
                   {"type": "command", "action": "pause" | "resume" | "toggle" | "stop"}
                   {"type": "command", "action": "seek", "position"} | {"action": "skip", "delta"}
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

log = logging.getLogger("samedia.remote")

ACTIONS = {"play", "pause", "resume", "toggle", "seek", "skip", "stop"}


@dataclass
class Player:
    device_id: str
    kind: str
    name: str
    ws: WebSocket
    connected_at: float = field(default_factory=time.time)
    now: dict | None = None          # what it is playing, as last reported

    def describe(self, label: str | None = None) -> dict:
        now = None
        if self.now and self.now.get("item_id"):
            # positions move on between reports: estimate where it is now
            n = dict(self.now)
            if n.get("playing") and n.get("position") is not None:
                n["position"] = min(n["position"] + (time.time() - n["at"]), n.get("duration") or 1e12)
            now = {k: n.get(k) for k in ("item_id", "title", "position", "duration", "playing", "profile_id", "kind")}
        return {"id": self.device_id, "name": label or self.name, "kind": self.kind, "now_playing": now}


class Hub:
    def __init__(self) -> None:
        self.players: dict[str, Player] = {}
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, device_id: str, name: str, kind: str) -> Player:
        player = Player(device_id=device_id, kind=kind, name=name, ws=ws)
        async with self.lock:
            old = self.players.get(device_id)
            self.players[device_id] = player
        if old:                          # the same app reconnected: drop the stale socket
            try:
                await old.ws.close(code=4000)
            except Exception:  # noqa: BLE001 - it may be gone already
                pass
        log.info("player connected: %s (%s)", name, kind)
        return player

    def disconnect(self, player: Player) -> None:
        if self.players.get(player.device_id) is player:
            del self.players[player.device_id]
            log.info("player gone: %s", player.name)

    def update(self, player: Player, state: dict) -> None:
        if not state.get("item_id"):
            player.now = None
            return
        player.now = {
            "item_id": str(state["item_id"])[:40], "title": str(state.get("title") or "")[:200],
            "kind": str(state.get("kind") or "")[:20],
            "position": _num(state.get("position")), "duration": _num(state.get("duration")),
            "playing": bool(state.get("playing")), "profile_id": state.get("profile_id"), "at": time.time(),
        }

    async def send(self, device_id: str, message: dict) -> bool:
        player = self.players.get(device_id)
        if not player:
            return False
        try:
            await player.ws.send_json(message)
            return True
        except Exception as exc:  # noqa: BLE001 - a dead socket
            log.info("player %s unreachable: %s", player.name, exc)
            self.disconnect(player)
            return False


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


hub = Hub()
