/* Samedia server API client. */
(function () {
  'use strict';

  var S = SM.settings;

  function base() { return (S.get('server') || '').replace(/\/+$/, ''); }

  function withToken(url) {
    var t = S.get('token');
    if (!t) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 't=' + encodeURIComponent(t);
  }

  /** Absolute URL for an API path, with the access token as a query param (AVPlay and <img> can't send headers). */
  function abs(path) { return withToken(base() + path); }

  function request(method, path, body, opts) {
    opts = opts || {};
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, opts.timeout || 15000) : null;
    var headers = { 'Content-Type': 'application/json' };
    var token = S.get('token');
    if (token) headers.Authorization = 'Bearer ' + token;
    var url = (opts.base !== undefined ? opts.base : base()) + path;
    return fetch(url, {
      method: method, headers: headers, signal: ctrl ? ctrl.signal : undefined,
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(function (res) {
      clearTimeout(timer);
      if (res.status === 401) {
        var err401 = new Error('PIN required');
        err401.status = 401;
        SM.events.emit('auth-required');
        throw err401;
      }
      if (res.status === 202 && opts.allowPending) return { pending: true };
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (j) {
          var err = new Error(j.detail || ('HTTP ' + res.status));
          err.status = res.status;
          throw err;
        });
      }
      return opts.raw ? res : res.json();
    }, function (e) {
      clearTimeout(timer);
      var err = new Error(e && e.name === 'AbortError' ? 'Server did not respond' : 'Cannot reach server');
      err.network = true;
      throw err;
    });
  }

  function art(path, width) {
    if (!path) return null;
    return abs(path + '?w=' + (width || 400));
  }

  /** Probe a candidate server; resolves with its /info or rejects. */
  function probe(url, timeout) {
    return request('GET', '/api/v1/info', undefined, { base: url.replace(/\/+$/, ''), timeout: timeout || 3000 })
      .then(function (info) {
        if (info.app !== 'samedia') throw new Error('Not a Samedia server');
        return info;
      });
  }

  /** Scan the TV's /24 subnet for servers on port 8097. */
  function discover(onFound, onProgress) {
    var ip = null;
    try { ip = webapis.network.getIp(); } catch (e) { /* not on a TV */ }
    if (!ip) ip = '192.168.1.2';
    var prefix = ip.split('.').slice(0, 3).join('.');
    var hosts = [];
    for (var i = 1; i < 255; i++) hosts.push(prefix + '.' + i);
    var done = 0, found = [], idx = 0;
    return new Promise(function (resolve) {
      function next() {
        if (idx >= hosts.length) return;
        var url = 'http://' + hosts[idx++] + ':8097';
        probe(url, 1500).then(function (info) {
          var entry = { url: url, info: info };
          found.push(entry);
          onFound && onFound(entry);
        }, function () {}).then(function () {
          done++;
          onProgress && onProgress(done / hosts.length);
          if (done === hosts.length) resolve(found);
          else next();
        });
      }
      for (var w = 0; w < 24; w++) next();
    });
  }

  SM.api = {
    base: base, abs: abs, art: art, probe: probe, discover: discover,
    get: function (path, opts) { return request('GET', path, undefined, opts); },
    post: function (path, body, opts) { return request('POST', path, body || {}, opts); },
    home: function () { return request('GET', '/api/v1/home'); },
    movies: function (q) { return request('GET', '/api/v1/movies' + (q || '')); },
    shows: function (q) { return request('GET', '/api/v1/shows' + (q || '')); },
    show: function (id) { return request('GET', '/api/v1/shows/' + id); },
    item: function (id) { return request('GET', '/api/v1/items/' + id); },
    search: function (q) { return request('GET', '/api/v1/search?q=' + encodeURIComponent(q)); },
    playback: function (id, body) { return request('POST', '/api/v1/items/' + id + '/playback', body, { timeout: 30000 }); },
    progress: function (id, position, duration) {
      return request('POST', '/api/v1/items/' + id + '/progress', { position: position, duration: duration });
    },
    watched: function (id, watched) { return request('POST', '/api/v1/items/' + id + '/watched', { watched: watched }); },
    showWatched: function (id, watched, season) {
      return request('POST', '/api/v1/shows/' + id + '/watched' + (season !== undefined ? '?season=' + season : ''), { watched: watched });
    },
    pair: function (url, pin) {
      return request('POST', '/api/v1/auth', { pin: pin }, { base: url.replace(/\/+$/, '') });
    },
  };

  /* Tiny event bus used for cross-module notifications (watched state changed, auth lost...). */
  var handlers = {};
  SM.events = {
    on: function (name, fn) { (handlers[name] = handlers[name] || []).push(fn); },
    off: function (name, fn) { handlers[name] = (handlers[name] || []).filter(function (f) { return f !== fn; }); },
    emit: function (name, data) { (handlers[name] || []).slice().forEach(function (fn) { fn(data); }); },
  };
})();
