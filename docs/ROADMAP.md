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

## Next

### Subtitles without an account
- OpenSubtitles needs an account for its key; the main no-account source (Podnapisi) is gone.
  Option: make foreign-parts subtitles on the server itself (speech recognition + translation,
  e.g. Whisper), run once per title in the background.

## After that

### Music
- Local music library (artists, albums, tracks, album art, titles), ~80 GB to upload.
- Playback on TV/iPad/Android with an old-school (90s/00s, Winamp/WMP era) visualizer.

### Spotify
- Connect the Samedia server to Spotify once (admin page); every app can then browse and play
  the account's playlists, search, and keep playing after the queue ends (radio).
- Playback through Spotify Connect (the official Spotify app on the TV/phone plays, Samedia
  controls it): Spotify doesn't allow streaming its audio through other apps. Needs Premium.

### Locked-down players
- Lock a TV to one profile/account that can only play pre-approved music (and/or video),
  set from the admin page and the Android app.

### Admin page revamp
- A fuller management console: players and their locks, profiles, libraries, music and
  Spotify, approvals, server status.
