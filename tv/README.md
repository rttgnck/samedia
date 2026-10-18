# Samedia — Samsung TV app

A Tizen web app for Samsung TVs (built for the 2022 Frame QN75LS03B, Tizen 6.5). It plays everything
from your NAS through the TV's own hardware decoder (Samsung **AVPlay**): 4K, HEVC/AV1/VP9, HDR10/HDR10+,
MKV/MP4/TS. It renders subtitles itself, including Blu-ray **PGS** bitmaps. Anything the TV can't decode,
mainly DTS and TrueHD audio, is converted on the server: the audio is re-encoded and the video is copied untouched.

## Features

- **Cover Flow** library shelf for Movies and TV. OK flips the centre cover to show details and Play.
  A poster grid view is available from the toolbar.
- Home with a backdrop hero that follows focus. Rows: Continue Watching, Next Up, Recently Added, genres.
- Show pages with season tabs and an episode row. Detail pages with resume, audio and subtitle pickers, and watched toggle.
- Player: resume, ±10/30 s scrubbing with hold-to-accelerate, audio and subtitle menus, subtitle timing,
  playback-info overlay, auto-play next episode, progress synced to the server.
- Remote: arrows, OK, Back, ▶/❚❚, ◀◀/▶▶, CH±. Colour keys in the player: red = audio, yellow = subtitles, green = info.
- On-screen keyboards (search, server IP, PIN), so there's no fighting with the system IME.
- Finds the server automatically by scanning the TV's subnet for port 8097.

## Install on the TV (sideload)

Samsung only allows store apps by default, so you install Samedia in **Developer Mode** using a free
**Samsung certificate**.

### 1. Put the TV in Developer Mode

1. On the TV, open **Apps**.
2. Press **1 2 3 4 5** on the remote. On the Frame's solar remote, press the `123` button to get the number pad.
3. Switch **Developer mode** to *On*. For **Host PC IP**, enter your Mac's IP address.
4. Fully restart the TV: hold the power button until the logo appears.

### 2. Install Tizen Studio and create a certificate (one time)

1. Install [Tizen Studio](https://developer.tizen.org/development/tizen-studio/download) (the CLI-only installer is enough).
2. In the **Package Manager**, install **Extension SDK → Samsung Certificate Extension** and **TV Extensions**.
3. Open **Tools → Certificate Manager → + → Samsung**:
   - Device type: **TV**
   - Create an author certificate. This requires signing in with a Samsung account.
   - Create a distributor certificate. **Add the TV's DUID**, which Certificate Manager reads from the connected
     TV. Connect first with `sdb connect <tv-ip>`.
4. Add Tizen Studio's tools to your PATH:

```bash
export PATH="$HOME/tizen-studio/tools:$HOME/tizen-studio/tools/ide/bin:$PATH"
```

### 3. Build, sign and install

```bash
scripts/package-tv.sh 192.168.1.50
```

This copies the app into `dist/tv`, signs it with your active certificate profile (set `TIZEN_PROFILE=name`
to choose another), installs `dist/Samedia.wgt` on the TV and launches it. Samedia then shows up in the
TV's Apps list.

> A developer-mode install keeps working after Developer Mode is switched off. Samsung expires
> developer certificates after a while; when that happens, re-run the script.

## Develop in a browser

The app runs in desktop Chrome, using `<video>` instead of AVPlay, and scales the 1920×1080 canvas to the window:

```bash
python3 -m http.server 8098 --directory tv
```

Open <http://localhost:8098>, enter `127.0.0.1` on the keypad, and use the arrow keys, Enter and Esc (Back).
Chrome can't play MPEG-TS or DTS, so the server's remuxed streams only play on the TV.

## Code map

| Path | What |
|---|---|
| `config.xml` | Tizen manifest (privileges: internet, tv.inputdevice, productinfo, network) |
| `js/core/focus.js` | Spatial D-pad navigation, focus groups with memory, modal layers |
| `js/core/router.js` | View stack. Views stay in the DOM while covered, so Back is instant |
| `js/core/coverflow.js` | Cover Flow shelf (3D transforms, windowed rendering, flip-to-back) |
| `js/player/backends.js` | AVPlay backend (TV) and HTML5 backend (browser) |
| `js/player/subtitles.js` | WebVTT parser, PGS (.sup) decoder, renderer |
| `js/player/player.js` | Player UI, direct-play vs remux timeline, retries |
| `js/views/*` | Home, library, show, detail, search, settings, setup |

The code uses plain ES5-style scripts with a global `SM` namespace and no build step. Packaged Tizen apps load from
`file://`, where ES modules are blocked, and the TV's Chromium (M85 on Tizen 6.5) lacks newer CSS such as
`inset` and `:has()`.

## Things to verify on the real TV

These are known Tizen behaviours, but they could not be tested without the hardware:

- **TrueHD passthrough.** It's off by default. Turn on *Settings → Dolby TrueHD* to try it, for example with an eARC soundbar.
- **Remuxed MPEG-TS start-up time.** Buffering is set to 6 s for remux streams in `player.js`.
- **`SET_MODE_4K`.** The app requests UHD decoding for sources wider than 1920 px.
