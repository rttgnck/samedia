from samedia import playback

ITEM = {
    "id": "mtest", "path": "/media/x.mkv", "sidecar_subs": [],
    "media": {
        "container": "mkv", "duration": 7200,
        "video": {"index": 0, "codec": "hevc", "width": 3840, "height": 2160, "hdr": "dv7"},
        "audio": [
            {"index": 1, "codec": "truehd", "profile": "", "channels": 8, "language": "eng", "default": True, "atmos": True},
            {"index": 2, "codec": "ac3", "profile": "", "channels": 6, "language": "eng", "default": False, "atmos": False},
        ],
        "subtitles": [{"index": 3, "codec": "hdmv_pgs_subtitle", "format": "pgs", "language": "eng",
                       "title": None, "default": False, "forced": False}],
    },
}


def test_truehd_default_track_is_remuxed_to_eac3():
    d = playback.decide(ITEM, None)
    assert d["mode"] == "remux" and "acodec=eac3" in d["url"] and d["audio_index"] == 1
    assert any("Dolby Vision" in w for w in d["warnings"])


def test_supported_track_direct_plays():
    d = playback.decide(ITEM, None, audio_index=2)
    assert d["mode"] == "direct" and d["audio_ordinal"] == 1


def test_truehd_direct_when_tv_claims_support():
    caps = {**playback.DEFAULT_CAPS, "audio": playback.DEFAULT_CAPS["audio"] + ["truehd"]}
    assert playback.decide(ITEM, caps)["mode"] == "direct"


def test_unknown_video_codec_transcodes():
    item = {**ITEM, "media": {**ITEM["media"], "video": {"index": 0, "codec": "prores", "width": 1920}}}
    d = playback.decide(item, None, audio_index=2)
    assert d["mode"] == "transcode" and "vcodec=h264" in d["url"]


def test_pgs_track_is_offered():
    tracks = playback.subtitle_tracks(ITEM)
    assert tracks[0]["format"] == "pgs" and tracks[0]["url"].endswith("/e3")


def test_ffmpeg_cmd_downmixes_to_51():
    cmd = playback.build_ffmpeg_cmd(ITEM, 30, 1, "eac3", "copy")
    assert cmd[cmd.index("-ac") + 1] == "6" and cmd[cmd.index("-c:v") + 1] == "copy"
