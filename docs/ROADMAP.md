# Samedia roadmap

## Done

### Remote control and hand-off (0.7)
- Every app (TV, iPhone/iPad, Android) registers with the server as a player and keeps a live
  connection for commands; the server knows what each is playing.
- "Play on…" from any card or details page; "Send to…" from the player's controls.
- Remote screen: now playing on each player, play/pause, skip, seek, stop.

### Android app (0.8)
- Phone-first remote: every screen that's on, what it plays, scrubbing and transport controls,
  arrows/OK/Back/Home for a TV's menus and its volume (the phone's volume buttons too).
- Browse, "Play on…", and plays on the phone (Media3; Dolby/DTS/TrueHD audio decoded on the
  phone, picture-in-picture, automatic foreign-parts subtitles, hand-off with "Send to").

### Google TV, updater, playback problems (0.9)
- Samedia on Google TV (Chromecast with Google TV): the TV interface over the native player.
- `npm run updater`: every screen, its version, update from the codebase; `npm run build`.
- Apps report playback failures; the admin page lists them. Old codecs re-encoded in segments.

## Done in 0.10 (music)

### Music
- Music from the media folders (tags, or Artist/Album/01 - Title), album art from the folder, the
  files or the Cover Art Archive; AcoustID (optional key) names untagged files.
- On the TV (Samsung and Google TV): albums in Cover Flow, artists, Now Playing with a late-90s
  visualizer (classic spectrum, Milkdrop-style, oscilloscope, vinyl). On phone and iPad: the same
  library, background playback with lock-screen controls, Now Playing with a visualizer.

### Spotify
- Connected once in the admin page; playlists, search, play on any Spotify device (Spotify
  Connect, needs Premium), radio from a song. Spotify's own Autoplay carries on after that.

### Locked screens
- A screen locked (admin page, phone, iPad) to one profile and approved artists, albums and
  Spotify playlists: no films, nothing else.

### Admin page
- Tabs: overview (what plays where), folders (with a folder browser and what each holds),
  music, Spotify, screens (locks), profiles, playback problems, settings.

### Title cards
- Browsing backgrounds show a text-free scene of what's in focus (not its poster) with its logo.

## Next

### iPhone/iPad: 4K HEVC in MKV
- Apple's players take HEVC only in fragmented-MP4 segments, so 4K HEVC MKVs can't play on the
  iPad yet (1080p ones are re-encoded). Serve fMP4 segments of the untouched video for Apple.

### Subtitles without an account
- OpenSubtitles needs an account for its key; the main no-account source (Podnapisi) is gone.
  Option: make foreign-parts subtitles on the server itself (speech recognition + translation,
  e.g. Whisper), run once per title in the background.
