"""Runtime configuration.

Environment variables seed the defaults; anything changed in the web admin UI
is persisted in the database `settings` table and takes precedence.
"""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

VERSION = "0.10.0"
API_VERSION = 1


def _split_paths(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(":") if p.strip()]


def _env_list(name: str, default: str) -> list[str]:
    return _split_paths(os.environ.get(name, default))


FOLDER_KINDS = ("auto", "movies", "shows", "music")


def _kinds(value) -> dict[str, str]:
    """{folder: what it holds}; anything unknown counts as "auto"."""
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if v in FOLDER_KINDS and v != "auto"}


def _path_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(p).strip() for p in value if str(p).strip()]
    return _split_paths(str(value))


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("SAMEDIA_DATA_DIR", "/config")))
    host: str = os.environ.get("SAMEDIA_HOST", "0.0.0.0")
    port: int = int(os.environ.get("SAMEDIA_PORT", "8097"))
    server_name: str = os.environ.get("SAMEDIA_SERVER_NAME", "Samedia")
    # Colon-separated list of folders to scan. Each folder may hold movies and/or TV shows.
    media_roots: list[str] = field(default_factory=lambda: _env_list("SAMEDIA_MEDIA_ROOTS", "/media"))
    # What each folder holds (set in the admin page): movies, shows, music; others are "auto"
    root_kinds: dict = field(default_factory=dict)
    pin: str = os.environ.get("SAMEDIA_PIN", "")
    tmdb_key: str = os.environ.get("SAMEDIA_TMDB_KEY", "")
    # OpenSubtitles.com, for foreign-parts subtitles a file doesn't have (optional; the login
    # only raises the daily download allowance)
    opensubtitles_key: str = os.environ.get("SAMEDIA_OPENSUBTITLES_KEY", "")
    opensubtitles_user: str = os.environ.get("SAMEDIA_OPENSUBTITLES_USER", "")
    opensubtitles_password: str = os.environ.get("SAMEDIA_OPENSUBTITLES_PASSWORD", "")
    # AcoustID (acoustid.org/new-application), to name music files that carry no tags (optional)
    acoustid_key: str = os.environ.get("SAMEDIA_ACOUSTID_KEY", "")
    # Spotify: the app's client id (developer.spotify.com); the account's token is kept apart
    spotify_client_id: str = os.environ.get("SAMEDIA_SPOTIFY_CLIENT_ID", "")
    scan_interval_hours: float = float(os.environ.get("SAMEDIA_SCAN_INTERVAL_HOURS", "6"))
    probe_workers: int = int(os.environ.get("SAMEDIA_PROBE_WORKERS", "2"))
    # Extract all subtitle tracks right after a file is scanned (one read of the file).
    preextract_subs: bool = os.environ.get("SAMEDIA_PREEXTRACT_SUBS", "0") == "1"
    ffmpeg: str = os.environ.get("SAMEDIA_FFMPEG", "ffmpeg")
    ffprobe: str = os.environ.get("SAMEDIA_FFPROBE", "ffprobe")
    # E-AC3 bitrate used when converting DTS / TrueHD audio for the TV.
    eac3_bitrate: str = os.environ.get("SAMEDIA_EAC3_BITRATE", "640k")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "samedia.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def kind_of(self, root: str | Path) -> str:
        return self.root_kinds.get(str(root), "auto")

    def secret(self) -> str:
        """Per-install secret used to derive access tokens."""
        f = self.data_dir / ".secret"
        if f.exists():
            return f.read_text().strip()
        key = secrets.token_hex(32)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(key)
        f.chmod(0o600)
        return key


# Keys the admin UI may override at runtime, with their parsers.
EDITABLE = {
    "server_name": str,
    "media_roots": _path_list,
    "root_kinds": _kinds,
    "pin": str,
    "tmdb_key": str,
    "opensubtitles_key": str,
    "opensubtitles_user": str,
    "opensubtitles_password": str,
    "acoustid_key": str,
    "spotify_client_id": str,
    "scan_interval_hours": float,
    "preextract_subs": bool,
    "eac3_bitrate": str,
}

config = Config()


def apply_overrides(overrides: dict) -> None:
    for key, value in overrides.items():
        if key in EDITABLE:
            setattr(config, key, EDITABLE[key](value))
