/* Shared UI building blocks: icons, cards, rows, menus, toasts, keyboards. */
(function () {
  'use strict';

  var el = SM.util.el;

  var ICONS = {
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    shuffle: '<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>',
    prev: '<path d="M19 20 9 12l10-8zM5 19V5"/>',
    skipnext: '<path d="m5 4 10 8-10 8zM19 5v14"/>',
    wave: '<path d="M2 12h2l2-6 3 12 3-15 3 18 3-12 2 3h2"/>',
    spotify: '<circle cx="12" cy="12" r="9.5"/><path d="M7 9.5c3.5-1 7.2-.7 10 1M7.6 12.6c2.8-.8 5.8-.5 8.2.9M8.3 15.5c2.2-.6 4.4-.4 6.4.7"/>',
    radio: '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.5M7.8 16.2a6 6 0 0 1 0-8.5M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5"/>',
    user2: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    home: '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    tv: '<rect x="2.5" y="5" width="19" height="13" rx="2"/><path d="M8 21h8M12 18v3"/>',
    cast: '<path d="M3 17a4 4 0 0 1 4 4M3 13a8 8 0 0 1 8 8M3 9.2V7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-5"/><path d="M3 21h.01"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    play: '<path d="M7 4.5v15l13-7.5z" fill="currentColor" stroke="none"/>',
    pause: '<path d="M7 4h3.5v16H7zM13.5 4H17v16h-3.5z" fill="currentColor" stroke="none"/>',
    back10: '<path d="M4 12a8 8 0 1 0 2.3-5.7L4 8.6"/><path d="M4 4v4.6h4.6"/><text x="12" y="15.5" font-size="7" text-anchor="middle" fill="currentColor" stroke="none" font-weight="700">10</text>',
    fwd30: '<path d="M20 12a8 8 0 1 1-2.3-5.7L20 8.6"/><path d="M20 4v4.6h-4.6"/><text x="12" y="15.5" font-size="7" text-anchor="middle" fill="currentColor" stroke="none" font-weight="700">30</text>',
    audio: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
    subs: '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M6 12.5h4M12 12.5h6M6 15.5h7M15 15.5h3"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    next: '<path d="M5 5v14l10-7zM18 5v14"/>',
    check: '<path d="m4.5 12.5 5 5 10-11"/>',
    star: '<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" fill="currentColor" stroke="none"/>',
    restart: '<path d="M4 12a8 8 0 1 0 2.3-5.7L4 8.6"/><path d="M4 4v4.6h4.6"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H10l2 2.5h7.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
    sort: '<path d="M7 4v16M3.5 16.5 7 20l3.5-3.5M17 20V4M13.5 7.5 17 4l3.5 3.5"/>',
    filter: '<path d="M3 5h18l-7 8.5V19l-4 2v-7.5z"/>',
    backspace: '<path d="M21 5H8.5L3 12l5.5 7H21z"/><path d="m12 9 6 6M18 9l-6 6"/>',
    bookmark: '<path d="M6.5 3.5h11v17l-5.5-4-5.5 4z"/><path d="M12 7.5v5M9.5 10h5"/>',
    bookmarks: '<path d="M8 3.5h11v15l-5.5-4-5.5 4z"/><path d="M5 7v13.5l4.5-3.2"/>',
    aspect: '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M6 9v-1.5h3M18 15v1.5h-3"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    stack: '<rect x="6" y="3" width="13" height="16" rx="1.5"/><path d="M3.5 6.5V20a1.5 1.5 0 0 0 1.5 1.5h11"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    user: '<circle cx="12" cy="8.5" r="4"/><path d="M4 20.5c1.4-4 4.4-6 8-6s6.6 2 8 6"/>',
    hide: '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4M6.6 6.6C3.9 8.3 2 12 2 12s3.6 7 10 7a9.6 9.6 0 0 0 4.4-1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    logo: '<rect x="3" y="5" width="18" height="13" rx="2.5" fill="currentColor" stroke="none" opacity=".25"/><path d="M10 9v5.5l4.5-2.75z" fill="currentColor" stroke="none"/><path d="M8 21h8"/>',
    server: '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  };

  function icon(name, cls) {
    var span = el('span.icon' + (cls ? '.' + cls : ''));
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
      (ICONS[name] || '') + '</svg>';
    return span;
  }

  // ── artwork ─────────────────────────────────────────────────────

  function placeholder(title, kind) {
    var h = SM.util.hue(title);
    return el('div.art-placeholder' + (kind ? '.' + kind : ''), {
      style: { background: 'linear-gradient(150deg, hsl(' + h + ',45%,32%), hsl(' + ((h + 40) % 360) + ',55%,14%))' },
    }, [el('span', { text: title })]);
  }

  /** <img> that fades in when loaded and falls back to a placeholder on error. */
  function image(url, width, title, kind) {
    var wrap = el('div.art');
    var ph = placeholder(title || '', kind);
    wrap.appendChild(ph);
    if (url) {
      var img = el('img', { alt: '', loading: 'lazy', decoding: 'async' });
      img.onload = function () { wrap.classList.add('loaded'); };
      img.onerror = function () { img.remove(); };
      img.src = SM.api.art(url, width);
      wrap.appendChild(img);
    }
    return wrap;
  }

  function progressBar(item) {
    if (!item.duration || !SM.util.resumeAt(item)) return null;
    // At least a visible sliver: 30 seconds into a two-hour film is still "started"
    var pct = Math.min(100, Math.max(6, 100 * item.position / item.duration));
    return el('div.progress', [el('i', { style: { width: pct + '%' } })]);
  }

  function watchedMark(item) {
    return item.watched ? el('div.watched', [icon('check')]) : null;
  }

  // ── cards ───────────────────────────────────────────────────────

  function posterCard(item, opts) {
    opts = opts || {};
    var card = el('div.card.poster.f', { dataset: { id: item.id, kind: item.kind } }, [
      el('div.frame', [image(item.poster, 320, item.title, 'poster'), watchedMark(item), progressBar(item),
        item.kind === 'show' && item.unwatched ? el('div.count', { text: String(item.unwatched) }) : null,
        item.kind === 'collection' ? el('div.count', { text: String(item.item_count) }) : null]),
      opts.caption === false ? null : el('div.caption', [
        el('div.title', { text: item.title }),
        el('div.sub', { text: SM.util.resumeAt(item) ? 'Resume ' + SM.util.clock(item.position)
          : item.watched ? 'Watched' : (item.year ? String(item.year) : '') }),
      ]),
    ]);
    card._item = item;
    return card;
  }

  function landscapeCard(item) {
    var isEp = item.kind === 'episode';
    var art = item.thumb || item.backdrop;
    var title = isEp ? item.show_title : item.title;
    var sub = isEp ? SM.util.episodeCode(item) + ' · ' + item.title : (item.year || '');
    if (item.position && item.duration && item.position < item.duration && !item.watched) sub += ' · ' + SM.util.runtime(item.duration - item.position) + ' left';
    var card = el('div.card.landscape.f', { dataset: { id: item.id, kind: item.kind } }, [
      el('div.frame', [image(art, 480, title, 'landscape'), watchedMark(item), progressBar(item)]),
      el('div.caption', [el('div.title', { text: title || '' }), el('div.sub', { text: String(sub) })]),
    ]);
    card._item = item;
    return card;
  }

  function episodeCard(item) {
    var card = el('div.card.episode.f', { dataset: { id: item.id, kind: 'episode' } }, [
      el('div.frame', [image(item.thumb, 480, 'E' + item.episode, 'landscape'), watchedMark(item), progressBar(item),
        el('div.ep-num', { text: 'E' + item.episode + (item.episode_end ? '–' + item.episode_end : '') })]),
      el('div.caption', [
        el('div.title', { text: item.title }),
        el('div.sub', { text: SM.util.runtime(item.duration) }),
      ]),
    ]);
    card._item = item;
    return card;
  }

  /** Horizontal row of cards. */
  function row(title, items, style, onSelect) {
    var track = el('div.row-track', { 'data-scroll': 'x', 'data-pad': '0' });
    items.forEach(function (it) {
      var card = style === 'landscape' ? landscapeCard(it) : posterCard(it);
      track.appendChild(card);
    });
    var r = el('section.row.' + style, { 'data-group': '', 'data-row': '' }, [el('h2', { text: title }), track]);
    r.addEventListener('click', function (e) {
      var card = e.target.closest('.card');
      if (card && onSelect) onSelect(card._item, card);
    });
    return r;
  }

  function button(label, iconName, onClick, cls) {
    var b = el('div.btn.f' + (cls ? '.' + cls : ''), { onclick: onClick }, [
      iconName ? icon(iconName) : null, label ? el('span', { text: label }) : null,
    ]);
    return b;
  }

  function badges(list) {
    if (!list || !list.length) return null;
    return el('div.badges', list.map(function (b) { return el('span.badge', { text: b }); }));
  }

  function spinner(text) {
    return el('div.loading', [el('div.spinner'), text ? el('div', { text: text }) : null]);
  }

  function errorBox(err, retry) {
    return el('div.error-box', [
      el('h3', { text: 'Something went wrong' }),
      el('p', { text: err && err.message ? err.message : String(err) }),
      retry ? button('Try again', 'restart', retry, 'primary autofocus') : null,
    ]);
  }

  // ── overlays ────────────────────────────────────────────────────

  var toastTimer = null;
  function toast(text, ms) {
    var t = document.getElementById('toast');
    t.textContent = text;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, ms || 3200);
  }

  /** Modal list menu. options: [{label, sub, selected, disabled, action}] */
  function menu(title, options, opts) {
    opts = opts || {};
    var list = el('div.menu-list', { 'data-scroll': 'y-near' });
    var layer = el('div.modal' + (opts.side ? '.side' : ''), [
      el('div.menu', [el('h3', { text: title }), list]),
    ]);
    var close = function () {
      if (!layer.parentNode) return;
      SM.focus.popLayer(layer);
      layer.parentNode.removeChild(layer);
      opts.onClose && opts.onClose();
    };
    options.forEach(function (o) {
      var item = el('div.menu-item.f' + (o.selected ? '.selected.autofocus' : '') + (o.disabled ? '.disabled' : ''), {
        onclick: function () {
          if (o.disabled) return;
          close();
          o.action && o.action();
        },
      }, [
        el('span.check', [o.selected ? icon('check') : null]),
        el('span.label', [el('div', { text: o.label }), o.sub ? el('div.sub', { text: o.sub }) : null]),
      ]);
      list.appendChild(item);
    });
    layer._close = close;
    document.getElementById('overlays').appendChild(layer);
    SM.focus.pushLayer(layer);
    return { close: close };
  }

  function confirm(title, text, okLabel) {
    return new Promise(function (resolve) {
      var done = false;
      var finish = function (v) { if (!done) { done = true; close(); resolve(v); } };
      var layer = el('div.modal', [el('div.dialog', [
        el('h3', { text: title }), text ? el('p', { text: text }) : null,
        el('div.actions', [button(okLabel || 'OK', null, function () { finish(true); }, 'primary autofocus'),
          button('Cancel', null, function () { finish(false); })]),
      ])]);
      layer._close = function () { finish(false); };
      function close() { SM.focus.popLayer(layer); layer.remove(); }
      document.getElementById('overlays').appendChild(layer);
      SM.focus.pushLayer(layer);
    });
  }

  /** Text entry with the on-screen keyboard. Resolves the text, or null when cancelled. */
  function prompt(title, initial, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var value = initial || '';
      var box = el('div.input-box', { text: value || opts.placeholder || '' });
      box.classList.toggle('empty', !value);
      function shown(v) {
        // Names read better capitalised: "sam" -> "Sam"
        return opts.capitalize ? v.replace(/(^|\s)\S/g, function (c) { return c.toUpperCase(); }) : v;
      }
      var done = false;
      function finish(v) {
        if (done) return;
        done = true;
        SM.focus.popLayer(layer);
        layer.remove();
        resolve(v);
      }
      var kb = keyboard('text', value, function (v) {
        value = shown(v);
        kb.setValue(value);
        box.textContent = value || opts.placeholder || '';
        box.classList.toggle('empty', !value);
      }, function () { finish(value.trim() ? value.trim().slice(0, opts.max || 24) : null); });
      var layer = el('div.modal', [el('div.dialog.prompt', [el('h3', { text: title }), box, kb])]);
      layer._close = function () { finish(null); };
      layer._digit = function (d) { kb.handleDigit(d); };
      document.getElementById('overlays').appendChild(layer);
      SM.focus.pushLayer(layer);
    });
  }

  function topModal() {
    var o = document.getElementById('overlays');
    return o.lastElementChild && o.lastElementChild.classList.contains('modal') ? o.lastElementChild : null;
  }

  // ── on-screen keyboards ─────────────────────────────────────────

  /** Grid keyboard. layout: 'text' | 'ip' | 'pin'. onChange(value) after every key. */
  function keyboard(layout, initial, onChange, onDone) {
    var value = initial || '';
    var keys;
    if (layout === 'ip') keys = '1 2 3 4 5 6 7 8 9 . 0 :'.split(' ');
    else if (layout === 'pin') keys = '1 2 3 4 5 6 7 8 9 0'.split(' ');
    else keys = 'a b c d e f g h i j k l m n o p q r s t u v w x y z 1 2 3 4 5 6 7 8 9 0'.split(' ');
    var grid = el('div.keyboard.' + layout, { 'data-group': '' });
    function press(k) {
      if (k === 'del') value = value.slice(0, -1);
      else if (k === 'clear') value = '';
      else if (k === 'space') value += ' ';
      else value += k;
      onChange(value);
    }
    keys.forEach(function (k) {
      grid.appendChild(el('div.key.f', { onclick: function () { press(k); }, text: k }));
    });
    var extras = el('div.keyboard-extras', { 'data-group': '' });
    if (layout === 'text') extras.appendChild(el('div.key.wide.f', { onclick: function () { press('space'); }, text: 'space' }));
    var del = el('div.key.wide.f', { onclick: function () { press('del'); } }, [icon('backspace')]);
    extras.appendChild(del);
    extras.appendChild(el('div.key.wide.f', { onclick: function () { press('clear'); }, text: 'clear' }));
    if (onDone) extras.appendChild(el('div.key.wide.primary.f', { onclick: function () { onDone(value); }, text: 'done' }));
    var root = el('div.keyboard-wrap', [grid, extras]);
    root.setValue = function (v) { value = v; };
    // Number keys on the remote type directly.
    root.handleDigit = function (d) { press(String(d)); };
    root.backspace = function () { press('del'); };
    return root;
  }

  SM.ui = {
    icon: icon, image: image, placeholder: placeholder, posterCard: posterCard, landscapeCard: landscapeCard,
    episodeCard: episodeCard, row: row, button: button, badges: badges, spinner: spinner, errorBox: errorBox,
    toast: toast, menu: menu, confirm: confirm, topModal: topModal, keyboard: keyboard, progressBar: progressBar,
    prompt: prompt,
  };
})();
