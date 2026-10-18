/* Playback backends with one interface:
 *   open(url, {uhd}) -> Promise   prepare the stream
 *   play() pause() stop()
 *   seek(sec) -> Promise           only for seekable (direct) streams
 *   time() -> sec                  position reported by the decoder
 *   selectAudio(ordinal) -> bool   switch embedded audio track natively (direct play)
 *   on(event, fn)                  'time' | 'buffering' | 'ready' | 'ended' | 'error'
 *
 * AVPlayBackend drives Samsung's native player (hardware decode, HDR10/HDR10+, 4K, all
 * containers). HTML5Backend is a <video> fallback so the UI can be developed in a browser.
 */
(function () {
  'use strict';

  var PREPARE_TIMEOUT_MS = 30000; // a file the TV can't open may never call back
  var avGeneration = 0;           // webapis.avplay is one shared player: tag each opening

  // Picture modes: fit (letterbox), fill (crop to fill the screen), stretch
  var AV_MODES = { fit: 'PLAYER_DISPLAY_MODE_LETTER_BOX', fill: 'PLAYER_DISPLAY_MODE_CROPPED_FULL',
                   stretch: 'PLAYER_DISPLAY_MODE_FULL_SCREEN' };
  var CSS_FIT = { fit: 'contain', fill: 'cover', stretch: 'fill' };

  function Emitter() { this._h = {}; }
  Emitter.prototype.on = function (n, fn) { (this._h[n] = this._h[n] || []).push(fn); };
  Emitter.prototype.emit = function (n, a) { (this._h[n] || []).forEach(function (fn) { fn(a); }); };

  // ── Samsung AVPlay ──────────────────────────────────────────────

  function AVPlayBackend(objectEl) {
    Emitter.call(this);
    this.av = webapis.avplay;
    this.obj = objectEl;
    this._time = 0;
  }
  AVPlayBackend.prototype = Object.create(Emitter.prototype);

  AVPlayBackend.prototype.open = function (url, opts) {
    var self = this, av = this.av;
    opts = opts || {};
    this._closeQuiet();
    this._gen = ++avGeneration;
    this._time = 0;
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = setTimeout(function () {
        if (settled) return;
        settled = true;
        self._closeQuiet();
        reject(new Error('The TV could not open this video (no response after ' + PREPARE_TIMEOUT_MS / 1000 + 's)'));
      }, PREPARE_TIMEOUT_MS);
      function done(fn, arg) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        fn(arg);
      }
      try {
        av.open(url);
        av.setDisplayRect(0, 0, 1920, 1080);
        try { av.setDisplayMethod(AV_MODES[opts.displayMode] || AV_MODES.fit); }
        catch (e) { av.setDisplayMethod(AV_MODES.fit); }
        if (opts.uhd) {
          try { av.setStreamingProperty('SET_MODE_4K', 'TRUE'); } catch (e) { /* older firmware */ }
        }
        if (opts.bufferSec) {
          try {
            av.setBufferingParam('PLAYER_BUFFER_FOR_PLAY', 'PLAYER_BUFFER_SIZE_IN_SECOND', opts.bufferSec);
            av.setBufferingParam('PLAYER_BUFFER_FOR_RESUME', 'PLAYER_BUFFER_SIZE_IN_SECOND', opts.bufferSec);
          } catch (e) { /* optional */ }
        }
        var timeEvents = 0;
        av.setListener({
          onbufferingstart: function () { SM.devlog.log('av.bufferingstart'); self.emit('buffering', true); },
          onbufferingprogress: function () {},
          onbufferingcomplete: function () { SM.devlog.log('av.bufferingcomplete'); self.emit('buffering', false); },
          oncurrentplaytime: function (ms) {
            if (++timeEvents === 1) SM.devlog.log('av.firsttime', ms);
            self._time = ms / 1000; self.emit('time', self._time);
          },
          onstreamcompleted: function () { SM.devlog.log('av.completed'); self.emit('ended'); },
          onerror: function (type) { SM.devlog.log('av.error', String(type)); self.emit('error', new Error(String(type))); },
          onevent: function (type, data) { SM.devlog.log('av.event', { type: String(type), data: String(data).slice(0, 200) }); },
          onsubtitlechange: function () {},
          ondrmevent: function () {},
        });
        av.prepareAsync(function () {
          if (settled) return;
          // The app draws subtitles itself; stop the TV's player drawing its own (an empty
          // native subtitle box can sit on the picture for the whole film).
          try { av.setSilentSubtitle(true); } catch (e) { /* older firmware */ }
          if (SM.devlog.on) {
            var tracks = [];
            try { tracks = av.getTotalTrackInfo().map(function (t) { return t.type + ':' + t.index; }); } catch (e) {}
            var dur = null;
            try { dur = av.getDuration(); } catch (e) {}
            SM.devlog.log('av.prepared', { duration: dur, tracks: tracks });
          }
          self.emit('ready');
          done(resolve);
        }, function (err) {
          done(reject, new Error(err && err.name ? err.name : 'PLAYER_ERROR_PREPARE'));
        });
      } catch (e) {
        done(reject, e);
      }
    });
  };

  AVPlayBackend.prototype.setDisplayMode = function (mode) {
    try { this.av.setDisplayMethod(AV_MODES[mode] || AV_MODES.fit); return true; } catch (e) { return false; }
  };

  AVPlayBackend.prototype.play = function () { try { this.av.play(); } catch (e) { /* not ready */ } };
  AVPlayBackend.prototype.pause = function () { try { this.av.pause(); } catch (e) {} };
  AVPlayBackend.prototype.isPlaying = function () {
    try { return this.av.getState() === 'PLAYING'; } catch (e) { return false; }
  };

  /** Seek to an absolute time; if the TV refuses (seen: InvalidValuesError), try a relative jump. */
  AVPlayBackend.prototype.seek = function (sec) {
    var av = this.av, self = this;
    var before = this.time(), state = this.state();
    var dur = null;
    try { dur = av.getDuration(); } catch (e) { /* unknown */ }
    SM.devlog.log('av.seek', { to: sec, from: before, state: state, duration: dur });
    function errName(e) { return e && (e.name || e.message || String(e)); }

    function jump(resolve, reject, firstErr) {
      var delta = Math.round((sec - self.time()) * 1000);
      var fn = delta >= 0 ? 'jumpForward' : 'jumpBackward';
      try {
        av[fn](Math.abs(delta), function () {
          SM.devlog.log('av.jump.ok', { fn: fn, delta: delta, now: self.time() });
          self._time = sec; resolve();
        }, function (e) {
          SM.devlog.log('av.jump.fail', { fn: fn, delta: delta, err: errName(e) });
          reject(firstErr || e);
        });
      } catch (e) {
        SM.devlog.log('av.jump.throw', { fn: fn, err: errName(e) });
        reject(firstErr || e);
      }
    }

    return new Promise(function (resolve, reject) {
      try {
        av.seekTo(Math.max(0, Math.floor(sec * 1000)), function () {
          SM.devlog.log('av.seek.ok', { to: sec, now: self.time(), state: self.state() });
          self._time = sec; resolve();
        }, function (e) {
          SM.devlog.log('av.seek.fail', { to: sec, err: errName(e), state: self.state() });
          jump(resolve, reject, e);
        });
      } catch (e) {
        SM.devlog.log('av.seek.throw', { to: sec, err: errName(e), state: self.state() });
        jump(resolve, reject, e);
      }
    });
  };

  AVPlayBackend.prototype.state = function () {
    try { return this.av.getState(); } catch (e) { return 'unknown'; }
  };

  AVPlayBackend.prototype.time = function () {
    try { return this.av.getCurrentTime() / 1000; } catch (e) { return this._time; }
  };

  AVPlayBackend.prototype.selectAudio = function (ordinal) {
    try {
      var tracks = this.av.getTotalTrackInfo().filter(function (t) { return t.type === 'AUDIO'; });
      if (!tracks[ordinal]) return false;
      this.av.setSelectTrack('AUDIO', tracks[ordinal].index);
      return true;
    } catch (e) {
      return false;
    }
  };

  AVPlayBackend.prototype._closeQuiet = function () {
    var t0 = Date.now(), st = this.state();
    try {
      if (st !== 'NONE' && st !== 'IDLE') this.av.stop();
      if (st !== 'NONE') this.av.close();
    } catch (e) { /* already closed */ }
    SM.devlog.log('av.close', { from: st, ms: Date.now() - t0 });
  };
  /** Leaving the player: stop the picture now, release the decoder once the UI has redrawn. */
  AVPlayBackend.prototype.stop = function () {
    var self = this, gen = this._gen;
    try { if (this.state() === 'PLAYING') this.av.pause(); } catch (e) { /* ignore */ }
    setTimeout(function () {
      // Something else (e.g. the next episode) may already be using the player
      if (gen === avGeneration) self._closeQuiet();
      else SM.devlog.log('av.close.skipped', { mine: gen, current: avGeneration });
    }, 120);
  };
  AVPlayBackend.prototype.suspend = function () { try { this.av.suspend(); } catch (e) {} };
  AVPlayBackend.prototype.restore = function () { try { this.av.restore(); } catch (e) {} };

  // ── HTML5 <video> (development in a desktop browser) ────────────

  function HTML5Backend(videoEl) {
    Emitter.call(this);
    var self = this;
    this.v = videoEl;
    videoEl.addEventListener('timeupdate', function () { self.emit('time', videoEl.currentTime); });
    videoEl.addEventListener('waiting', function () { self.emit('buffering', true); });
    videoEl.addEventListener('playing', function () { self.emit('buffering', false); });
    videoEl.addEventListener('ended', function () { self.emit('ended'); });
    videoEl.addEventListener('error', function () {
      if (self._opening) return;
      var e = videoEl.error;
      self.emit('error', new Error(e ? 'MEDIA_ERR_' + e.code + (e.message ? ': ' + e.message : '') : 'MEDIA_ERR'));
    });
  }
  HTML5Backend.prototype = Object.create(Emitter.prototype);

  HTML5Backend.prototype.open = function (url) {
    var v = this.v, self = this;
    this._opening = true;
    return new Promise(function (resolve, reject) {
      function ok() { cleanup(); self._opening = false; self.emit('ready'); resolve(); }
      function bad() {
        cleanup();
        self._opening = false;
        reject(new Error(v.error ? 'MEDIA_ERR_' + v.error.code : 'MEDIA_ERR'));
      }
      function cleanup() { v.removeEventListener('loadedmetadata', ok); v.removeEventListener('error', bad); }
      v.addEventListener('loadedmetadata', ok);
      v.addEventListener('error', bad);
      v.src = url;
      v.load();
    });
  };
  HTML5Backend.prototype.setDisplayMode = function (mode) { this.v.style.objectFit = CSS_FIT[mode] || 'contain'; return true; };

  HTML5Backend.prototype.play = function () { var p = this.v.play(); if (p && p.catch) p.catch(function () {}); };
  HTML5Backend.prototype.pause = function () { this.v.pause(); };
  HTML5Backend.prototype.isPlaying = function () { return !this.v.paused && !this.v.ended; };
  HTML5Backend.prototype.seek = function (sec) { this.v.currentTime = sec; return Promise.resolve(); };
  HTML5Backend.prototype.time = function () { return this.v.currentTime || 0; };
  HTML5Backend.prototype.selectAudio = function (ordinal) {
    var tracks = this.v.audioTracks;
    if (!tracks || !tracks[ordinal]) return false;
    for (var i = 0; i < tracks.length; i++) tracks[i].enabled = i === ordinal;
    return true;
  };
  HTML5Backend.prototype.stop = function () { this.v.pause(); this.v.removeAttribute('src'); this.v.load(); };
  HTML5Backend.prototype.suspend = function () { this.v.pause(); };
  HTML5Backend.prototype.restore = function () {};

  SM.backends = {
    create: function (mount) {
      if (SM.util.isTizen && window.webapis && webapis.avplay) {
        var obj = document.createElement('object');
        obj.setAttribute('type', 'application/avplayer');
        obj.className = 'av-object';
        mount.appendChild(obj);
        return new AVPlayBackend(obj);
      }
      var v = document.createElement('video');
      v.className = 'av-object';
      v.setAttribute('playsinline', '');
      mount.appendChild(v);
      return new HTML5Backend(v);
    },
  };
})();
