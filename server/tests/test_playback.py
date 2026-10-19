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
    # the URL carries the file's extension (Samsung's player won't seek in one without)
    assert d["url"] == "/api/v1/stream/mtest/direct.mkv"


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


IPAD = {"containers": ["mp4", "mov", "m4v"], "video": ["h264", "hevc"], "audio": ["aac", "ac3", "eac3", "mp3"],
        "hls_video": ["h264"], "ts_video": ["h264"], "prefer_hls": True, "max_width": 3840}


def _item(container, vcodec, acodec):
    return {"id": "m2", "path": f"/media/x.{container}", "sidecar_subs": [],
            "media": {"container": container, "duration": 600,
                      "video": {"index": 0, "codec": vcodec, "width": 1920, "height": 1080, "hdr": None},
                      "audio": [{"index": 1, "codec": acodec, "profile": "", "channels": 6, "language": "eng",
                                 "default": True, "atmos": False}], "subtitles": []}}


def test_ipad_gets_direct_mp4_and_segments_for_the_rest():
    assert playback.decide(_item("mp4", "hevc", "eac3"), IPAD)["mode"] == "direct"
    d = playback.decide(_item("mkv", "h264", "ac3"), IPAD, session="ipad")
    assert d["mode"] == "hls" and d["seekable"] and "/1/copy/copy/index.m3u8" in d["url"]
    d = playback.decide(_item("mp4", "h264", "dts"), IPAD)                 # audio the iPad can't play
    assert d["mode"] == "hls" and "/eac3/" in d["url"]
    # HEVC outside MP4: Apple players can't take it in MPEG-TS, so up to 1080p it is re-encoded
    # in the segments (still seekable), beyond that the server can't keep up: one-way stream
    d = playback.decide(_item("mkv", "hevc", "aac"), IPAD)
    assert d["mode"] == "hls" and "/copy/h264/index.m3u8" in d["url"]
    uhd = _item("mkv", "hevc", "aac")
    uhd["media"]["video"]["width"] = 3840
    assert playback.decide(uhd, IPAD)["mode"] == "transcode"
    # the TV (no preference) keeps the one-way stream for what it can't play directly
    assert playback.decide(_item("mp4", "h264", "dts"), None)["mode"] == "remux"


TV = {"containers": ["mkv", "mp4", "avi"], "video": ["h264", "hevc", "mpeg4", "vc1"],
      "audio": ["aac", "ac3", "mp3"], "hls_video": ["h264", "hevc", "mpeg2video"], "max_width": 3840}


def test_a_tv_that_needs_segments_gets_old_codecs_re_encoded_in_them():
    """XviD on a Samsung TV that can only seek in segments: H.264 segments rather than a stream
    of a codec its player won't take there."""
    xvid = _item("avi", "mpeg4", "mp3")
    xvid["media"]["video"].update(width=640, height=272)
    d = playback.decide(xvid, TV, force="hls")
    assert d["mode"] == "hls" and d["seekable"] and "/copy/h264/index.m3u8" in d["url"]
    # what it can take in segments stays untouched
    d = playback.decide(_item("mkv", "h264", "ac3"), TV, force="hls")
    assert d["mode"] == "hls" and "/copy/copy/index.m3u8" in d["url"]
