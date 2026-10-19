# Samedia

A modern media player for your NAS library — films, shows and music (with a late-90s visualizer and Spotify) —
on Samsung TVs, Google TV, Android and iPhone/iPad, with Kodi-level format support, plus a small companion server
that runs on nasOS.

```
 ┌───────────────────────── Samsung TV (Tizen 6.5) ─────────────────────────┐
 │  Samedia app  ── Cover Flow library · AVPlay hardware player · PGS/VTT subs │
 └───────────────▲─────────────────────────────────────────────┬────────────┘
                 │ JSON API, artwork, subtitles                 │ video stream
                 │                                              ▼
 ┌───────────────┴──────────── nasOS (Raspberry Pi 5) ─────────────────────┐
 │  Samedia server (Docker, :8097)                                           │
 │   scan + .nfo/art ─ playback decision ─┬─ direct: original file (Range)  │
 │                                        ├─ remux: video copied, DTS/TrueHD │
 │                                        │         → E-AC3, MPEG-TS         │
 │                                        └─ transcode: last resort          │
 │  /srv/nasos/shares, /mnt/<disks>  (mounted read-only)                     │
 └───────────────────────────────────────────────────────────────────────────┘
```

**Why a server at all?** The TV's own decoder handles 4K HEVC/AV1, HDR10/HDR10+ and MKV fine. What it
lacks are a few licensed formats: Samsung dropped **DTS** in 2018, TrueHD from apps is unreliable, and there's no
Dolby Vision. Tizen apps also can't open SMB shares. The server serves files over HTTP and converts **only the
audio** when needed, which a Pi 5 does easily. Video is passed through untouched, so you keep full 4K HDR quality.

| Folder | What | Docs |
|---|---|---|
| `tv/` | Samsung TV app (Tizen web app) | [tv/README.md](tv/README.md): sideloading, development |
| `server/` | Media server (Python/FastAPI + ffmpeg, Docker) | [server/README.md](server/README.md): config, API |
| `ios/` | iPhone/iPad app (SwiftUI): browse, play, remote | `scripts/build-ios.sh` |
| `android/` | Android app: on phones a remote that plays too (Compose, Media3); on Google TV the TV interface over the native player | `scripts/build-android.sh` |
| `scripts/updater.mjs` | `npm run updater`: every screen running Samedia, its version, update any of them from this checkout | below |
| `docs/NASOS_INTEGRATION_SPEC.md` | Spec for adding Samedia to the nasOS App Store | [spec](docs/NASOS_INTEGRATION_SPEC.md) |
| `scripts/package-tv.sh` | Build, sign and install the TV app | |
| `.github/workflows/server-image.yml` | Multi-arch image → `ghcr.io/rttgnck/samedia-server` | |

## Quick start

1. **Server.** Install it from the nasOS App Store once the integration spec is implemented, or run it directly:
   `cd server && docker compose up -d`. Then open `http://<nas>:8097/` and check the media folders.
2. **TV.** Follow [tv/README.md](tv/README.md) to enable Developer Mode and run `scripts/package-tv.sh <tv-ip>`.
3. In the TV app, pick the server from **On your network** (or type its IP), then browse.

Existing Kodi libraries carry over: `movie.nfo` / `tvshow.nfo` / episode `.nfo` files and `poster.jpg` /
`fanart.jpg` / `<name>-poster.jpg` artwork are read directly. A TMDB key is optional.

## Updating every screen

```
npm run updater
```

Lists every TV, phone and tablet that runs Samedia (the server keeps track of them, with the
version each runs) next to the latest build, which is made on the spot from this checkout. Pick
any with the arrow keys and space, press Enter: it builds what's needed and installs it.

| Screen | How the updater reaches it |
|---|---|
| Samsung TV | Developer Mode with this Mac as Host PC (found by scanning the network), Tizen Studio's `sdb`/`tizen` |
| Android phone, Google TV | Developer options → Wireless debugging, paired with `adb pair` |
| iPhone, iPad | Paired with Xcode; your Apple team id is asked once and kept in `~/.config/samedia/updater.json` |

A screen that's playing something is left unticked. Other commands: `npm run updater -- --list`,
`npm run build -- tv android ios` (release builds in `dist/release/`), `npm run version -- 1.0.0`.

## What plays how on the Frame

| Source | Result |
|---|---|
| H.264 / HEVC / AV1 / VP9 · HDR10 · HDR10+ · MKV/MP4/TS | Direct play |
| AAC, AC3, E-AC3 (incl. Atmos), FLAC, Opus | Direct play |
| DTS, DTS-HD MA, DTS:X, TrueHD (incl. Atmos) | Remux: audio → E-AC3 5.1, video untouched |
| Dolby Vision profile 7/8 | HDR10 base layer (the TV has no DV) |
| Dolby Vision profile 5 | Wrong colours; can't be fixed on this TV (the app warns) |
| PGS (Blu-ray) and SRT/ASS/embedded text subtitles | Rendered by the app (ASS styling is simplified to plain text) |
| Rare video codecs (e.g. ProRes) | Full transcode to H.264 1080p (slow on a Pi) |
