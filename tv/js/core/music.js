/* Music player: one <audio> element and a queue, shared by every screen. Plays the file as it
 * is when the TV can, as MP3 otherwise; reports what it plays (remote control, "recently
 * played"); feeds the visualizer through Web Audio (with a made-up signal when a TV won't hand
 * the sound over, so the visualizer never sits dead). */
(function () {
  'use strict';

  var S = SM.settings;
  // what HTML5 audio in the TV's browser (Tizen, Android WebView) plays as it is
  var PLAYS = { mp3: 1, aac: 1, flac: 1, vorbis: 1, opus: 1, pcm_s16le: 1, pcm_s24le: 1 };
  var audio = new Audio();
  audio.crossOrigin = 'anonymous';         // so Web Audio may read it (the server allows any origin)
  audio.preload = 'auto';
  var queue = [], index = -1, shuffled = false, order = [];
  var listeners = [];
  var ctx = null, analyser = null, gain = null, freq = null, wave = null, silentSince = 0;
  var reportTimer = null, playedSent = null, outputGain = 1;

  function emit(what) { listeners.forEach(function (fn) { try { fn(what); } catch (e) { /* a view's problem */ } }); }
  function current() { return index >= 0 ? queue[order[index]] : null; }

  function url(t) {
    var direct = PLAYS[t.codec];
    return SM.api.abs('/api/v1/music/stream/' + t.id + (direct ? '' : '?format=mp3'));
  }

  /** Web Audio, set up on first play (TVs want a user action first). */
  function wire() {
    if (ctx || !(window.AudioContext || window.webkitAudioContext)) return;
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      var source = ctx.createMediaElementSource(audio);
      analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.75;
      gain = ctx.createGain();
      gain.gain.value = outputGain;
      source.connect(analyser);
      analyser.connect(gain);
      gain.connect(ctx.destination);
      freq = new Uint8Array(analyser.frequencyBinCount);
      wave = new Uint8Array(analyser.fftSize);
    } catch (e) {
      SM.devlog.log('music.webaudio', { error: e && e.message });
      analyser = null;
    }
  }

  function load(autoplay) {
    var t = current();
    if (!t) return;
    wire();
    if (ctx && ctx.state === 'suspended') ctx.resume();
    audio.src = url(t);
    playedSent = null;
    if (autoplay !== false) {
      var p = audio.play();
      if (p && p.catch) p.catch(function (e) { SM.devlog.log('music.play', { error: e && e.message }); });
    }
    emit('track');
    report();
  }

  function reorder(keepCurrent) {
    var cur = index >= 0 ? order[index] : 0;
    order = queue.map(function (_, i) { return i; });
    if (shuffled) {
      for (var i = order.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var x = order[i]; order[i] = order[j]; order[j] = x;
      }
      if (keepCurrent) { order.splice(order.indexOf(cur), 1); order.unshift(cur); }
    }
    index = keepCurrent ? order.indexOf(cur) : 0;
  }

  /** Play these tracks, starting with tracks[start]. */
  function play(tracks, start, opts) {
    if (!tracks || !tracks.length) return;
    // a film playing stops (one thing at a time)
    var top = SM.router.top();
    if (top && top.name === 'player') SM.router.pop();
    queue = tracks.slice();
    shuffled = !!(opts && opts.shuffle);
    order = queue.map(function (_, i) { return i; });
    index = Math.max(0, Math.min(queue.length - 1, start || 0));
    if (shuffled) {
      // shuffle the rest; a chosen track plays first
      index = start === undefined ? Math.floor(Math.random() * queue.length) : index;
      reorder(true);
    }
    load();
  }

  function next(auto) {
    if (index < 0) return;
    if (index + 1 < order.length) { index++; load(); return; }
    if (S.get('musicRepeat') && order.length) { index = 0; load(); return; }
    if (auto) stop();
  }

  function previous() {
    if (index < 0) return;
    if (audio.currentTime > 4 || index === 0) { audio.currentTime = 0; return; }
    index--; load();
  }

  function toggle() { if (audio.paused) resume(); else audio.pause(); }
  function resume() { if (ctx && ctx.state === 'suspended') ctx.resume(); var p = audio.play(); if (p && p.catch) p.catch(function () {}); }
  function seek(sec) { if (isFinite(sec)) audio.currentTime = Math.max(0, Math.min(sec, (audio.duration || sec) - 0.5)); }

  function stop() {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    queue = []; order = []; index = -1;
    emit('track');
    SM.remote.report(null);
  }

  function setShuffle(on) {
    shuffled = !!on;
    reorder(true);
    emit('state');
  }

  // ── reporting ──
  function report() {
    var t = current();
    if (!t) return;
    SM.remote.report({ item_id: t.id, title: t.title, artist: t.artist, kind: 'track', art: t.art,
                       position: audio.currentTime || 0, duration: audio.duration || t.duration || 0,
                       playing: !audio.paused, profile_id: S.get('profileId') });
  }

  audio.addEventListener('ended', function () { next(true); });
  audio.addEventListener('play', function () { emit('state'); report(); });
  audio.addEventListener('pause', function () { emit('state'); report(); });
  audio.addEventListener('timeupdate', function () {
    var t = current();
    // counts as played after 30 s (or half of a short one)
    if (t && playedSent !== t.id && audio.currentTime > Math.min(30, (audio.duration || 60) / 2)) {
      playedSent = t.id;
      SM.api.music.played(t.id).catch(function () {});
    }
    emit('time');
  });
  audio.addEventListener('error', function () {
    var t = current();
    SM.devlog.log('music.error', { track: t && t.id, code: audio.error && audio.error.code });
    if (t) SM.api.post('/api/v1/events', { kind: 'playback_error', item_id: t.id, mode: 'music',
      error: 'MEDIA_ERR_' + (audio.error ? audio.error.code : '?') }).catch(function () {});
    if (t) setTimeout(function () { next(true); }, 800);
  });
  setInterval(function () { if (!audio.paused && current()) report(); }, 5000);

  // ── the sound, for the visualizer (0..1 bands, -1..1 wave) ──
  var fake = 0;
  function bands(n) {
    var out = new Array(n);
    var live = analyser && !audio.paused;
    if (live) {
      analyser.getByteFrequencyData(freq);
      var peak = 0;
      for (var k = 0; k < freq.length; k++) if (freq[k] > peak) peak = freq[k];
      var now = Date.now();
      silentSince = peak < 24 ? (silentSince || now) : 0;
      live = !silentSince || now - silentSince < 1500;   // 1.5 s of nothing: no data from this TV (or a silent part)
    }
    if (live) {
      // log-spaced bands over 30 Hz – 16 kHz
      var nyq = (ctx ? ctx.sampleRate : 44100) / 2;
      for (var i = 0; i < n; i++) {
        var lo = 30 * Math.pow(16000 / 30, i / n), hi = 30 * Math.pow(16000 / 30, (i + 1) / n);
        var a = Math.floor(lo / nyq * freq.length), b = Math.max(a + 1, Math.ceil(hi / nyq * freq.length));
        var m = 0;
        for (var j = a; j < b && j < freq.length; j++) m = Math.max(m, freq[j]);
        out[i] = m / 255;
      }
      return out;
    }
    // made up: a slow groove so the screen still moves to something
    fake += audio.paused ? 0.004 : 0.016;
    var beat = Math.pow(Math.max(0, Math.sin(fake * 7.5)), 6);
    for (var q = 0; q < n; q++) {
      var x = q / n;
      out[q] = audio.paused ? 0.04 : Math.max(0, Math.min(1, 0.55 * (1 - x) * (0.6 + 0.4 * Math.sin(fake * 3 + q * 0.7))
        + 0.25 * Math.sin(fake * 5.3 + q * 1.9) * Math.sin(fake * 1.7 + x * 6) + beat * (1 - x) * 0.5));
    }
    return out;
  }

  function waveform(n) {
    var out = new Array(n);
    if (analyser && !audio.paused && (!silentSince || Date.now() - silentSince < 1500)) {
      analyser.getByteTimeDomainData(wave);
      for (var i = 0; i < n; i++) out[i] = (wave[Math.floor(i * wave.length / n)] - 128) / 128;
      return out;
    }
    var amp = audio.paused ? 0.02 : 0.35 + 0.25 * Math.sin(fake * 2.1);
    for (var k = 0; k < n; k++) {
      var t = k / n;
      out[k] = amp * (Math.sin(t * 22 + fake * 9) * 0.6 + Math.sin(t * 57 - fake * 13) * 0.3 + Math.sin(t * 5 + fake) * 0.1);
    }
    return out;
  }

  // ── keys and remotes ──
  /** A key while music plays (and no film is up): true when used. */
  function key(action) {
    if (!current()) return false;
    switch (action) {
      case 'playpause': toggle(); return true;
      case 'play': resume(); return true;
      case 'pause': audio.pause(); return true;
      case 'stop': stop(); return true;
      case 'ff': case 'chup': next(); return true;
      case 'rw': case 'chdown': previous(); return true;
    }
    return false;
  }

  /** A command from another device. */
  function command(m) {
    switch (m.action) {
      case 'play_music':
        SM.api.music.tracks(m.tracks || []).then(function (r) {
          var list = r.tracks || [];
          if (!list.length) return;
          play(list, Math.min(m.index || 0, list.length - 1));
          if (!SM.router.top() || SM.router.top().name !== 'nowplaying') SM.router.push('nowplaying', {});
        });
        return true;
      case 'next': next(); return true;
      case 'previous': previous(); return true;
    }
    if (!current()) return false;
    switch (m.action) {
      case 'toggle': toggle(); break;
      case 'pause': audio.pause(); break;
      case 'resume': resume(); break;
      case 'seek': seek(m.position || 0); break;
      case 'skip': seek((audio.currentTime || 0) + (m.delta || 0)); break;
      case 'stop': stop(); break;
      default: return false;
    }
    report();
    return true;
  }

  SM.music = {
    play: play, next: next, previous: previous, toggle: toggle, resume: resume, pause: function () { audio.pause(); },
    seek: seek, stop: stop, setShuffle: setShuffle, key: key, command: command, bands: bands, waveform: waveform,
    current: current, playing: function () { return !!current() && !audio.paused; },
    active: function () { return !!current(); },
    time: function () { return audio.currentTime || 0; },
    duration: function () { var t = current(); return audio.duration || (t && t.duration) || 0; },
    shuffled: function () { return shuffled; },
    upcoming: function () { return order.slice(index + 1).map(function (i) { return queue[i]; }); },
    on: function (fn) { listeners.push(fn); return function () { listeners = listeners.filter(function (f) { return f !== fn; }); }; },
    /** Output level (tests run silent with 0); the visualizer still sees the sound. */
    setGain: function (v) { outputGain = v; if (gain) gain.gain.value = v; },
  };
})();
