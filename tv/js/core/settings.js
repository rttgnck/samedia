/* Persistent TV-side preferences (localStorage survives app updates on Tizen). */
(function () {
  'use strict';

  var KEY = 'samedia.settings.v1';

  var DEFAULTS = {
    server: '',                 // "http://192.168.1.20:8097"
    token: '',
    serverName: '',
    profileId: '',              // who's watching (server profile id)
    profileName: '',
    profileColor: '',
    profileKids: false,
    profileAvatar: '',          // picture name on the server ('' = initial)
    groupCollections: true,     // fold franchise movies into one collection in Movies
    avSeekBroken: '',           // learned: app version in which no way of seeking in our HTTP streams worked
    avSeekMethod: '',           // learned: the way of seeking that works on this TV
    deviceId: '',               // this TV's id for the server (per-TV profile rules)
    audioLanguage: 'en',        // preferred audio language (ISO 639-1 prefix)
    subtitleMode: 'auto',       // off | forced | auto (on when audio isn't your language) | always
    subtitleLanguage: 'en',
    subtitleSize: 'medium',     // small | medium | large
    subtitleBackground: true,
    // Codec support overrides. Samsung dropped DTS in 2018; TrueHD from apps varies by model.
    capTrueHD: false,
    capDTS: false,
    capFLAC: true,
    capOpus: true,
    capAV1: true,
    autoplayNext: true,
    showPlaybackInfo: false,
  };

  var state = load();

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      return Object.assign({}, DEFAULTS, raw ? JSON.parse(raw) : {});
    } catch (e) {
      return Object.assign({}, DEFAULTS);
    }
  }

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* storage full / disabled */ }
  }

  function get(k) { return state[k]; }

  function set(k, v) {
    state[k] = v;
    save();
  }

  /** What this TV can decode natively; sent with every playback request. */
  function capabilities() {
    var audio = ['aac', 'ac3', 'eac3', 'mp3', 'mp2', 'vorbis', 'pcm_s16le', 'pcm_s24le', 'pcm_bluray'];
    if (state.capFLAC) audio.push('flac');
    if (state.capOpus) audio.push('opus');
    if (state.capTrueHD) audio.push('truehd');
    if (state.capDTS) audio.push('dts');
    var video = ['h264', 'hevc', 'vp9', 'mpeg2video', 'mpeg4', 'vc1'];
    if (state.capAV1) video.push('av1');
    if (SM.util.native) {
      try { return JSON.parse(SM.util.native.capabilities()); } catch (e) { /* fall through */ }
    }
    if (!SM.util.isTizen) {
      // Desktop browser (development): only what Chrome's <video> handles.
      return { containers: ['mp4', 'webm', 'mkv'], video: ['h264', 'vp9', 'av1'], audio: ['aac', 'mp3', 'opus', 'flac', 'vorbis'],
               dolby_vision: false, max_width: 3840 };
    }
    // In HLS segments (MPEG-TS) the TV takes only these; anything else comes re-encoded there
    return { containers: ['mkv', 'mp4', 'webm', 'ts', 'avi', 'mpeg'], video: video, audio: audio,
             hls_video: ['h264', 'hevc', 'mpeg2video'], ts_video: ['h264', 'hevc', 'mpeg2video'],
             dolby_vision: false, max_width: 3840 };
  }

  SM.settings = { get: get, set: set, capabilities: capabilities, DEFAULTS: DEFAULTS };
})();
