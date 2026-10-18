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

JSON_COLUMNS = {"genres", "media", "sidecar_subs", "cast_members", "collection_hint"}

DEFAULT_PROFILE = "default"


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate_1(conn: sqlite3.Connection) -> None:
    """Profiles, per-profile progress, hidden titles, collections, richer metadata."""
    for col, decl in [("certification", "TEXT"), ("tagline", "TEXT"), ("cast_members", "TEXT DEFAULT '[]'"),
                      ("director", "TEXT"), ("collection_id", "TEXT"), ("collection_hint", "TEXT"),
                      ("meta_at", "REAL")]:
        _add_column(conn, "items", col, decl)
    for col, decl in [("certification", "TEXT"), ("cast_members", "TEXT DEFAULT '[]'"), ("meta_at", "REAL")]:
        _add_column(conn, "shows", col, decl)
    # Statements one by one: executescript() would commit the migration's transaction early
    for stmt in filter(str.strip, """
        CREATE TABLE IF NOT EXISTS collections (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sort_title TEXT NOT NULL,
            source TEXT NOT NULL,          -- folder | nfo | tmdb
            plot TEXT,
            poster TEXT,
            backdrop TEXT,
            tmdb_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_items_collection ON items(collection_id);
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            color TEXT NOT NULL,
            kids INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hidden (
            profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            target_id TEXT NOT NULL,       -- movie / episode / show / collection id
            created_at REAL NOT NULL,
            PRIMARY KEY (profile_id, target_id)
        );
        CREATE TABLE progress_v1 (
            profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            position REAL NOT NULL DEFAULT 0,
            duration REAL,
            watched INTEGER NOT NULL DEFAULT 0,
            play_count INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (profile_id, item_id)
        );
    """.split(";")):
        conn.execute(stmt)
    conn.execute("INSERT OR IGNORE INTO profiles (id, name, color, kids, created_at) VALUES (?, 'Main', '#5b8cff', 0, ?)",
                 (DEFAULT_PROFILE, time.time()))
    # Existing watch history belongs to the first profile.
    conn.execute("INSERT INTO progress_v1 SELECT ?, item_id, position, duration, watched, play_count, updated_at "
                 "FROM progress", (DEFAULT_PROFILE,))
    conn.execute("DROP TABLE progress")
    conn.execute("ALTER TABLE progress_v1 RENAME TO progress")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_progress_updated ON progress(profile_id, updated_at)")


MIGRATIONS = [_migrate_1]


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for n, step in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        try:
            step(conn)
            conn.execute(f"PRAGMA user_version={n}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

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
        _migrate(_conn)
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


def _params(params: Iterable[Any] | dict) -> tuple | dict:
    """Named (:name) parameters stay a dict; positional ones become a tuple."""
    return params if isinstance(params, dict) else tuple(params)


def query(sql: str, params: Iterable[Any] | dict = ()) -> list[dict]:
    with _lock:
        return [_decode(r) for r in connect().execute(sql, _params(params)).fetchall()]


def one(sql: str, params: Iterable[Any] | dict = ()) -> dict | None:
    with _lock:
        return _decode(connect().execute(sql, _params(params)).fetchone())


def execute(sql: str, params: Iterable[Any] | dict = ()) -> None:
    with _lock:
        connect().execute(sql, _params(params))


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

def save_progress(profile_id: str, item_id: str, position: float, duration: float | None) -> dict:
    now = time.time()
    watched = 0
    if duration and duration > 0 and position / duration >= 0.92:
        watched, position = 1, 0
    existing = one("SELECT * FROM progress WHERE profile_id=? AND item_id=?", (profile_id, item_id))
    play_count = (existing or {}).get("play_count", 0)
    if watched and not (existing or {}).get("watched"):
        play_count += 1
    elif existing and existing["watched"] and not watched:
        # Re-watching something already marked watched keeps it watched until it finishes.
        watched = 1
    _save_progress_row(profile_id, item_id, position, duration, watched, play_count, now)
    return one("SELECT * FROM progress WHERE profile_id=? AND item_id=?", (profile_id, item_id))


def set_watched(profile_id: str, item_id: str, watched: bool) -> None:
    existing = one("SELECT * FROM progress WHERE profile_id=? AND item_id=?", (profile_id, item_id))
    _save_progress_row(profile_id, item_id, 0, (existing or {}).get("duration"), int(watched),
                       (existing or {}).get("play_count", 0) + (1 if watched else 0), time.time())


def _save_progress_row(profile_id, item_id, position, duration, watched, play_count, now) -> None:
    with _lock:
        connect().execute(
            "INSERT INTO progress (profile_id, item_id, position, duration, watched, play_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(profile_id, item_id) DO UPDATE SET position=excluded.position, "
            "duration=excluded.duration, watched=excluded.watched, play_count=excluded.play_count, "
            "updated_at=excluded.updated_at",
            (profile_id, item_id, position, duration, watched, play_count, now))
