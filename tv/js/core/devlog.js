/* Developer log: only active in builds made with `scripts/package-tv.sh --devlog <url>`,
 * which define window.SM_DEV = { logUrl }. Sends errors, key presses, view changes and
 * player events to that URL so on-TV problems can be diagnosed. Normal builds: no-op. */
(function () {
  'use strict';

  var cfg = window.SM_DEV || null;
  var queue = [], timer = null, seq = 0;

  function describe(node) {
    if (!node || !node.tagName) return String(node);
    var d = node.tagName.toLowerCase();
    if (node.id) d += '#' + node.id;
    if (node.className && typeof node.className === 'string') d += '.' + node.className.trim().split(/\s+/).slice(0, 3).join('.');
    var t = (node.textContent || '').trim().slice(0, 24);
    return t ? d + ' "' + t + '"' : d;
  }

  function flush() {
    timer = null;
    if (!queue.length) return;
    var batch = queue.splice(0, queue.length);
    try {
      fetch(cfg.logUrl, { method: 'POST', body: JSON.stringify(batch), headers: { 'Content-Type': 'text/plain' } })
        .catch(function () {});
    } catch (e) { /* ignore */ }
  }

  function log(event, data) {
    if (!cfg) return;
    queue.push({ n: ++seq, t: Date.now(), ev: event, d: data === undefined ? null : data });
    if (!timer) timer = setTimeout(flush, 500);
  }

  /** What is drawn at a screen point (top-most first) — e.g. to find what covers the video. */
  function at(x, y) {
    if (!document.elementsFromPoint) return [];
    return document.elementsFromPoint(x, y).slice(0, 8).map(function (n) {
      var cs = getComputedStyle(n);
      return describe(n) + ' [bg ' + cs.backgroundColor + ', op ' + cs.opacity + ', vis ' + cs.visibility + ']';
    });
  }

  if (cfg) {
    window.addEventListener('error', function (e) {
      log('error', { msg: e.message, src: (e.filename || '').split('/').pop() + ':' + e.lineno + ':' + e.colno });
    });
    window.addEventListener('unhandledrejection', function (e) {
      log('rejection', { msg: e.reason && (e.reason.message || String(e.reason)) });
    });
    ['warn', 'error'].forEach(function (lvl) {
      var orig = console[lvl];
      console[lvl] = function () {
        log('console.' + lvl, Array.prototype.map.call(arguments, String).join(' ').slice(0, 500));
        return orig && orig.apply(console, arguments);
      };
    });
    log('start', { ua: navigator.userAgent, w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio });
  }

  SM.devlog = { on: !!cfg, log: log, describe: describe, at: at };
})();
