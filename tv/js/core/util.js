/* Small DOM + formatting helpers shared by every module. Plain scripts (no ES modules):
 * Tizen packaged apps load from file://, where module scripts are blocked. */
window.SM = window.SM || {};

(function () {
  'use strict';

  /** el('div.card.big', {onclick, dataset:{id}, text:'..'}, [children]) */
  function el(spec, props, children) {
    var parts = spec.split('.');
    var node = document.createElement(parts[0] || 'div');
    if (parts.length > 1) node.className = parts.slice(1).join(' ');
    if (Array.isArray(props) || typeof props === 'string' || props instanceof Node) {
      children = props;
      props = null;
    }
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (v === undefined || v === null || v === false) return;
        if (k === 'text') node.textContent = v;
        else if (k === 'html') node.innerHTML = v;
        else if (k === 'dataset') Object.keys(v).forEach(function (d) { node.dataset[d] = v[d]; });
        else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
        else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), v);
        else if (k === 'className') node.className += (node.className ? ' ' : '') + v;
        else node.setAttribute(k, v === true ? '' : v);
      });
    }
    append(node, children);
    return node;
  }

  function append(node, children) {
    if (children === undefined || children === null || children === false) return node;
    if (!Array.isArray(children)) children = [children];
    children.forEach(function (c) {
      if (c === undefined || c === null || c === false) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  /** 3725 -> "1:02:05", 65 -> "1:05" */
  function clock(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? h + ':' + pad(m) + ':' + pad(s) : m + ':' + pad(s);
  }

  /** 6300 -> "1h 45m" */
  function runtime(sec) {
    if (!sec) return '';
    var m = Math.round(sec / 60);
    if (m < 60) return m + 'm';
    return Math.floor(m / 60) + 'h ' + (m % 60 ? (m % 60) + 'm' : '');
  }

  function endsAt(remainingSec) {
    var d = new Date(Date.now() + remainingSec * 1000);
    var h = d.getHours(), m = d.getMinutes();
    var ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return 'Ends at ' + h + ':' + pad(m) + ' ' + ampm;
  }

  function episodeCode(item) {
    if (item.season === undefined || item.season === null) return '';
    var code = 'S' + item.season + ' · E' + item.episode;
    if (item.episode_end) code += '–' + item.episode_end;
    return code;
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  /** Stable pleasant hue from a string, for artwork placeholders. */
  function hue(str) {
    var h = 0;
    for (var i = 0; i < (str || '').length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
    return h;
  }

  function uid() {
    return Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
  }

  var isTizen = typeof window.tizen !== 'undefined' && typeof window.webapis !== 'undefined';
  // Samedia for Google TV runs this same app in an Android shell, which plays the video natively
  var native = window.SamediaNative || null;

  /** "1 movie", "3 movies" */
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  var RESUME_AFTER = 20; // seconds watched before a title counts as started (matches the server)

  /** Where to resume a title, or 0 when it should start from the beginning. */
  function resumeAt(item) {
    if (!item || item.watched || !item.position || item.position < RESUME_AFTER) return 0;
    if (item.duration && item.position > item.duration * 0.95) return 0;
    return item.position;
  }

  SM.util = {
    plural: plural, resumeAt: resumeAt,
    el: el, append: append, clear: clear, clock: clock, runtime: runtime, endsAt: endsAt,
    episodeCode: episodeCode, debounce: debounce, hue: hue, uid: uid, isTizen: isTizen,
    native: native, isAndroid: !!native, isTV: isTizen || !!native,
  };
})();
