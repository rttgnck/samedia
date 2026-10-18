# Samedia server

A small media server for the Samedia TV app. It is packaged as a Docker image so it can be installed from the
nasOS App Store (or any Docker host).

- Scans media folders for movies and TV episodes using Kodi-style naming (`Title (Year)`, `S01E02`, `Season 1/`).
- Reads **Kodi `.nfo` files and local artwork** (`poster.jpg`, `fanart.jpg`, `<name>-poster.jpg`, …), so an
  existing Kodi library comes across with its metadata. TMDB lookup is optional.
- Decides per file whether the TV can **direct play** it. If not, it **remuxes** on the fly: video copied,
  DTS/TrueHD → E-AC3 5.1, output as MPEG-TS. Full **transcode** (H.264 1080p) is a last resort only.
  A Raspberry Pi 5 has no hardware video encoder, so the design avoids video transcoding entirely.
- Extracts subtitles (text → WebVTT, PGS → `.sup`) in one pass per file and caches them.
- Tracks resume points, watched state, Continue Watching and Next Up.
- Admin page at `http://<nas>:8097/` for media folders, PIN, TMDB key, rescan and status.

## Run

```bash
docker compose up -d        # see docker-compose.yml
```

Or locally for development (needs `ffmpeg`/`ffprobe` on PATH):

```bash
pip install -r requirements.txt
SAMEDIA_DATA_DIR=./config SAMEDIA_MEDIA_ROOTS=/path/to/Movies:/path/to/TV python -m samedia.main
```

Tests: `python -m pytest -q`.

## Configuration

Environment variables set the defaults. Values changed in the admin page are stored in the database and win.

| Variable | Default | Meaning |
|---|---|---|
| `SAMEDIA_MEDIA_ROOTS` | `/media` | Colon-separated folders to scan |
| `SAMEDIA_DATA_DIR` | `/config` | Database, caches (artwork, subtitles), secret |
| `SAMEDIA_PORT` | `8097` | HTTP port |
| `SAMEDIA_SERVER_NAME` | `Samedia` | Name shown on the TV |
| `SAMEDIA_PIN` | *(empty)* | If set, the TV must pair with this PIN |
| `SAMEDIA_TMDB_KEY` | *(empty)* | TMDB v3 key or v4 token (optional) |
| `SAMEDIA_SCAN_INTERVAL_HOURS` | `6` | Periodic rescan |
| `SAMEDIA_PROBE_WORKERS` | `2` | Parallel ffprobe workers during scans |
| `SAMEDIA_PREEXTRACT_SUBS` | `0` | `1` = extract subtitles during scans |
| `SAMEDIA_EAC3_BITRATE` | `640k` | Bitrate for converted audio |

## API (v1)

Every endpoint except `/api/v1/info` and `/api/v1/auth` requires the token, sent as
`Authorization: Bearer <token>` or `?t=<token>`. The token is only needed when a PIN is set.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/info` | `{name, app:"samedia", version, api, pin_required}`. Used by the TV for discovery |
| POST | `/api/v1/auth` | `{pin}` → `{token}` |
| GET | `/api/v1/home` | `{hero[], rows[{id,title,style,items[]}]}` |
| GET | `/api/v1/movies` | `?sort=title\|added\|year\|rating&genre=&unwatched=` → `{items, genres}` |
| GET | `/api/v1/shows` | Same filters → `{items, genres}` |
| GET | `/api/v1/shows/{id}` | Show, `seasons[]`, `episodes[]`, `next_up` |
| GET | `/api/v1/items/{id}` | Full item: media info, `audio_tracks`, `subtitle_tracks`, `next` |
| GET | `/api/v1/search?q=` | `{movies, shows, episodes}` |
| POST | `/api/v1/items/{id}/playback` | `{capabilities, audio_index, start, force, prefer_audio_lang, session}` → playback decision with `mode`, `url`, `start_offset`, `seekable`, tracks, warnings |
| GET/HEAD | `/api/v1/stream/{id}/direct` | Original file, supports Range requests |
| GET | `/api/v1/stream/{id}/remux` | `?start&audio&acodec=copy\|eac3&vcodec=copy\|h264&session`. MPEG-TS from ffmpeg; a new request for the same session kills the previous ffmpeg |
| GET | `/api/v1/subs/{id}/e{index}` / `x{n}` | Embedded / external subtitle as WebVTT or `.sup`. Returns `202` while extraction runs |
| GET | `/api/v1/art/{id}/{poster\|backdrop\|thumb}?w=` | Resized, cached JPEG |
| POST | `/api/v1/items/{id}/progress` | `{position, duration}`. Marked watched at ≥ 92 % |
| POST | `/api/v1/items/{id}/watched` | `{watched}` |
| POST | `/api/v1/shows/{id}/watched?season=` | `{watched}` |
| GET | `/api/v1/admin/status` | Scan state, counts, roots, active conversions |
| GET/PUT | `/api/v1/admin/settings` | Editable settings |
| POST | `/api/v1/admin/scan` | Start a scan |
| GET | `/healthz` | Liveness |

### Playback decision

1. **Direct**: the container, video codec and selected audio codec are all in the TV's `capabilities`. The TV
   seeks natively, and switches embedded audio tracks with AVPlay's `setSelectTrack`.
2. **Remux**: the video is supported, but the audio or container isn't. The video is copied and the audio is
   copied or converted to E-AC3 (≤ 5.1). Output is MPEG-TS starting at the keyframe before `start`; the exact
   keyframe time is returned as `start_offset` so subtitles stay in sync. Seeking re-requests the stream.
3. **Transcode**: the video codec is unsupported. Output is libx264 `veryfast`, ≤ 1080p.

If direct play fails on the TV, the app automatically retries once with `force: "remux"`.
