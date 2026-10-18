"""SQLite storage (stdlib sqlite3, one shared connection guarded by a lock)."""

import json
import sqlite3
import threading
import time
from typing import Any, Iterable

from .config import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS shows (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    sort_title TEXT NOT NULL,
    year INTEGER,
    plot TEXT,
    rating REAL,
    genres TEXT DEFAULT '[]',
    poster TEXT,
    backdrop TEXT,
    tmdb_id INTEGER,
    added_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,              -- movie | episode
    path TEXT UNIQUE NOT NULL,
    root TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    title TEXT NOT NULL,
    sort_title TEXT NOT NULL,
    year INTEGER,
    show_id TEXT REFERENCES shows(id) ON DELETE CASCADE,
    season INTEGER,
    episode INTEGER,
    episode_end INTEGER,
    plot TEXT,
    rating REAL,
    genres TEXT DEFAULT '[]',
    poster TEXT,
    backdrop TEXT,
    thumb TEXT,
    tmdb_id INTEGER,
    duration REAL,
    media TEXT,                      -- JSON summary from ffprobe
    sidecar_subs TEXT DEFAULT '[]',  -- JSON list of external subtitle files
    added_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_show ON items(show_id, season, episode);
CREATE INDEX IF NOT EXISTS idx_items_added ON items(added_at);

CREATE TABLE IF NOT EXISTS progress (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    position REAL NOT NULL DEFAULT 0,
    duration REAL,
    watched INTEGER NOT NULL DEFAULT 0,
    play_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

JSON_COLUMNS = {"genres", "media", "sidecar_subs"}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.db_path, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(SCHEMA)
    return _conn


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for col in JSON_COLUMNS & out.keys():
        if out[col]:
            out[col] = json.loads(out[col])
    return out


def _encode(values: dict) -> dict:
    return {k: json.dumps(v) if k in JSON_COLUMNS and v is not None else v for k, v in values.items()}


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with _lock:
        return [_decode(r) for r in connect().execute(sql, tuple(params)).fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with _lock:
        return _decode(connect().execute(sql, tuple(params)).fetchone())


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with _lock:
        connect().execute(sql, tuple(params))


def upsert(table: str, values: dict, key: str = "id") -> None:
    values = _encode(values)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    updates = ", ".join(f"{c}=excluded.{c}" for c in values if c != key)
    with _lock:
        connect().execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT({key}) DO UPDATE SET {updates}",
            tuple(values.values()),
        )


# ── settings ────────────────────────────────────────────────────────

def load_settings() -> dict:
    return {r["key"]: json.loads(r["value"]) for r in query("SELECT key, value FROM settings")}


def save_setting(key: str, value: Any) -> None:
    upsert("settings", {"key": key, "value": json.dumps(value)}, key="key")


# ── progress ────────────────────────────────────────────────────────

def save_progress(item_id: str, position: float, duration: float | None) -> dict:
    now = time.time()
    watched = 0
    if duration and duration > 0 and position / duration >= 0.92:
        watched, position = 1, 0
    existing = one("SELECT * FROM progress WHERE item_id=?", (item_id,))
    play_count = (existing or {}).get("play_count", 0)
    if watched and not (existing or {}).get("watched"):
        play_count += 1
    elif existing and existing["watched"] and not watched:
        # Re-watching something already marked watched keeps it watched until it finishes.
        watched = 1
    upsert("progress", {
        "item_id": item_id, "position": position, "duration": duration,
        "watched": watched, "play_count": play_count, "updated_at": now,
    }, key="item_id")
    return one("SELECT * FROM progress WHERE item_id=?", (item_id,))


def set_watched(item_id: str, watched: bool) -> None:
    existing = one("SELECT * FROM progress WHERE item_id=?", (item_id,))
    upsert("progress", {
        "item_id": item_id, "position": 0, "duration": (existing or {}).get("duration"),
        "watched": int(watched),
        "play_count": (existing or {}).get("play_count", 0) + (1 if watched else 0),
        "updated_at": time.time(),
    }, key="item_id")
