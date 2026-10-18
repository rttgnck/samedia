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
    // No Content-Type on body-less requests: keeps simple GETs free of a CORS preflight
    var headers = body === undefined ? {} : { 'Content-Type': 'application/json' };
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
      err.cause = e ? (e.name || 'Error') + (e.message ? ': ' + e.message : '') : '';
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

  var IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

  function usable(ip) { return !!ip && IPV4.test(ip) && ip !== '0.0.0.0' && ip.indexOf('127.') !== 0; }

  function systemInfoIp(property) {
    return new Promise(function (resolve) {
      try {
        tizen.systeminfo.getPropertyValue(property, function (net) { resolve(net && net.ipAddress); },
          function () { resolve(null); });
      } catch (e) { resolve(null); }
    });
  }

  /** The TV's own IPv4 address: Samsung webapis first, then Tizen system info (wired, Wi-Fi). */
  function localIp() {
    var ip = null;
    try { ip = webapis.network.getIp(); } catch (e) { /* not on a TV, or webapis unavailable */ }
    if (usable(ip)) return Promise.resolve({ ip: ip, source: 'webapis' });
    return systemInfoIp('ETHERNET_NETWORK').then(function (eth) {
      if (usable(eth)) return { ip: eth, source: 'ethernet' };
      return systemInfoIp('WIFI_NETWORK').then(function (wifi) {
        return usable(wifi) ? { ip: wifi, source: 'wifi' } : { ip: null, source: null };
      });
    });
  }

  /** Scan the TV's /24 subnet for servers on port 8097. onStart({ip, prefix}) reports what's scanned. */
  function discover(onFound, onProgress, onStart) {
    return localIp().then(function (local) {
      // Without our own address, guess the most common home subnet
      var ip = local.ip || '192.168.1.2';
      var prefix = ip.split('.').slice(0, 3).join('.');
      onStart && onStart({ ip: local.ip, source: local.source, prefix: prefix });
      return scan(prefix, onFound, onProgress);
    });
  }

  function scan(prefix, onFound, onProgress) {
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
    base: base, abs: abs, art: art, probe: probe, discover: discover, localIp: localIp,
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
