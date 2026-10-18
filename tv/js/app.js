/* App shell: navigation rail, global key dispatch, boot. */
(function () {
  'use strict';

  SM.VERSION = '0.4.1';
  var el = SM.util.el, ui = SM.ui;

  var SECTIONS = [
    { id: 'home', label: 'Home', icon: 'home', view: 'home' },
    { id: 'movies', label: 'Movies', icon: 'film', view: 'library', params: { kind: 'movies' } },
    { id: 'shows', label: 'TV Shows', icon: 'tv', view: 'library', params: { kind: 'shows' } },
    { id: 'search', label: 'Search', icon: 'search', view: 'search' },
    { id: 'settings', label: 'Settings', icon: 'gear', view: 'settings' },
  ];

  var nav, views, lastBack = 0, profileItem = null;
  var LONG_PRESS_MS = 600;
  var enter = { down: 0, timer: null, long: false };

  function buildNav() {
    nav = el('nav.nav', { 'data-group': '' });
    SECTIONS.forEach(function (s) {
      var item = el('div.nav-item.f', { dataset: { section: s.id }, onclick: function () { goSection(s); } },
        [ui.icon(s.icon), el('span', { text: s.label })]);
      // Moving onto a section in the rail switches to it (no need to press OK).
      item.addEventListener('focus:sk', function () {
        setTimeout(function () {
          if (SM.focus.get() !== item) return; // user kept moving
          var bottom = SM.router.bottom();
          if (!bottom || bottom.section !== s.id) goSection(s, true);
        }, 350);
      });
      nav.appendChild(item);
    });
    nav.appendChild(el('div.nav-brand', [el('img', { src: 'icon.png', alt: '' })]));
    // Who's watching: avatar at the bottom of the rail; selecting it switches profile.
    profileItem = el('div.nav-item.nav-profile.f', { onclick: function () { SM.router.reset('profiles', {}); } });
    nav.appendChild(profileItem);
    renderProfile();
    return nav;
  }

  /** A profile's picture (served by Samedia), or its initial on its color. */
  function avatar(name, color, kids, picture, cls) {
    var a = el('span.' + (cls || 'avatar') + (kids ? '.kids' : ''), { style: { background: color || 'var(--accent)' } });
    if (picture && /^[a-z0-9-]+$/.test(picture)) {
      a.appendChild(el('img', { src: SM.api.abs('/avatars/' + picture + '.svg'), alt: '' }));
    } else {
      a.textContent = (name || '?').trim().charAt(0).toUpperCase();
    }
    return a;
  }

  function renderProfile() {
    if (!profileItem) return;
    var name = SM.settings.get('profileName');
    profileItem.classList.toggle('hidden', !name);
    SM.util.clear(profileItem);
    profileItem.appendChild(avatar(name, SM.settings.get('profileColor'), SM.settings.get('profileKids'), SM.settings.get('profileAvatar')));
    var kidsTag = SM.settings.get('profileKids') && !/kid/i.test(name || '') ? ' · Kids' : '';
    profileItem.appendChild(el('span', { text: name + kidsTag }));
  }

  function goSection(s, keepFocusInNav) {
    var top = SM.router.top();
    if (top && top.section === s.id && SM.router.depth() === 1) {
      if (!keepFocusInNav) SM.focus.focusFirst(top.el);
      return;
    }
    var navFocus = SM.focus.get();
    if (!keepFocusInNav) SM.focus.release();
    SM.router.reset(s.view, s.params);
    if (keepFocusInNav && navFocus && nav.contains(navFocus)) SM.focus.set(navFocus, { noScroll: true });
  }

  function markActive() {
    // Pushed views (detail/show) belong to the section at the bottom of the stack.
    var bottom = SM.router.bottom();
    var section = bottom && bottom.section;
    Array.prototype.forEach.call(nav.children, function (n) {
      var on = n.dataset.section === section;
      n.classList.toggle('active', on);
      if (on) nav._skLast = n; // entering the rail lands on the current section
    });
  }

  function onKey(e) {
    var action = SM.keys.action(e);
    if (SM.devlog.on) {
      SM.devlog.log('key', { code: e.keyCode, action: action, repeat: e.repeat, view: (SM.router.top() || {}).name,
                             focus: SM.devlog.describe(SM.focus.get()), layers: SM.focus.hasLayer() });
    }
    if (!action) return;
    e.preventDefault();
    if (action === 'enter') {
      // OK acts on release so that holding it can open the title menu instead.
      if (e.repeat || (enter.down && Date.now() - enter.down < 5000)) return;
      enter.down = Date.now();
      enter.long = false;
      clearTimeout(enter.timer);
      enter.timer = setTimeout(function () {
        enter.long = true;
        longPress();
      }, LONG_PRESS_MS);
      return;
    }
    dispatch(action, e);
  }

  function onKeyUp(e) {
    if (SM.keys.action(e) !== 'enter' || !enter.down) return;
    e.preventDefault();
    clearTimeout(enter.timer);
    var wasLong = enter.long;
    enter.down = 0;
    enter.long = false;
    if (!wasLong) dispatch('enter', e);
  }

  /** Held OK / blue button: the title menu, when a title is focused and nothing else is open. */
  function longPress() {
    var item = !ui.topModal() && !SM.focus.hasLayer() ? SM.context.itemFromFocus() : null;
    if (item) SM.context.open(item);
    else dispatch('enter', null);
  }

  function dispatch(action, e) {
    var modal = ui.topModal();
    if (modal && action === 'back') { modal._close && modal._close(); return; }
    if (modal && modal._digit && action.indexOf('digit:') === 0) { modal._digit(action.slice(6)); return; }
    if (action === 'blue' && !modal && !SM.focus.hasLayer()) {
      var item = SM.context.itemFromFocus();
      if (item) { SM.context.open(item); return; }
    }

    var top = SM.router.top();
    if (top && top.onKey && top.onKey(action, e)) return;

    if (action === 'exit') { exitApp(); return; }

    // Up/down inside the rail walks the rail: the open rail overlaps the content, so geometric
    // focus movement could otherwise jump into the page (e.g. the search keyboard).
    var cur = SM.focus.get();
    if ((action === 'up' || action === 'down') && cur && nav.contains(cur) && !modal) {
      var items = Array.prototype.filter.call(nav.querySelectorAll('.nav-item.f'), function (n) {
        return !n.classList.contains('hidden');
      });
      var i = items.indexOf(cur) + (action === 'down' ? 1 : -1);
      if (i >= 0 && i < items.length) SM.focus.set(items[i]);
      return;
    }

    switch (action) {
      case 'left': case 'right': case 'up': case 'down':
        if (!SM.focus.move(action) && action === 'left' && !modal && top && !top.fullscreen) {
          // Left edge of the content opens the rail.
          var active = nav.querySelector('.nav-item.active') || nav.firstChild;
          SM.focus.set(active);
        }
        return;
      case 'enter':
        var f = SM.focus.get();
        if (f) f.click();
        return;
      case 'back':
        if (SM.router.pop()) return;
        // At the root: focus the rail first, then require a second Back to exit.
        var focused = SM.focus.get();
        if (focused && !nav.contains(focused) && top && !top.fullscreen) {
          SM.focus.set(nav.querySelector('.nav-item.active') || nav.firstChild);
          return;
        }
        if (Date.now() - lastBack < 2500) exitApp();
        else { lastBack = Date.now(); ui.toast('Press Back again to exit'); }
        return;
    }
  }

  function exitApp() {
    try { tizen.application.getCurrentApplication().exit(); } catch (e) { window.close(); }
  }

  function goHome() {
    SM.router.reset('home');
  }

  function selectProfile(p) {
    var S = SM.settings;
    S.set('profileId', p.id);
    S.set('profileName', p.name);
    S.set('profileColor', p.color);
    S.set('profileKids', !!p.kids);
    S.set('profileAvatar', p.avatar || '');
    SM.events.emit('profile', p);
  }

  /** After connecting: pick who's watching when there's more than one profile. */
  function start(info) {
    SM.serverFeatures = (info && info.features) || [];
    if (!info || (info.features || []).indexOf('profiles') === -1) { goHome(); return; }
    SM.api.profiles().then(function (r) {
      var list = r.profiles || [];
      if (list.length === 1) {
        selectProfile(list[0]);
        goHome();
      } else {
        SM.router.reset('profiles', {});
      }
    }, function () { goHome(); });
  }

  /**
   * What the TV gives us: the web canvas (usually 1920×1080, upscaled by the TV), the pixel
   * ratio and the physical panel. A canvas other than 1920×1080 gets the UI zoomed to fill it
   * (CSS zoom re-renders text sharply, unlike a transform), and artwork is fetched for the
   * real pixel density.
   */
  function detectDisplay() {
    var w = window.innerWidth || 1920, h = window.innerHeight || 1080;
    var d = { width: w, height: h, dpr: window.devicePixelRatio || 1, panel: null, uhd: false, zoom: 1 };
    try { d.uhd = !!webapis.productinfo.isUdPanelSupported(); } catch (e) { /* not a Samsung TV */ }
    try {
      tizen.systeminfo.getPropertyValue('DISPLAY', function (x) {
        d.panel = x.resolutionWidth + '×' + x.resolutionHeight;
      }, function () {});
    } catch (e) { /* not Tizen */ }
    if (SM.util.isTizen && (w !== 1920 || h !== 1080)) {
      d.zoom = Math.min(w / 1920, h / 1080);
      document.documentElement.style.zoom = String(d.zoom);
    }
    d.artScale = Math.max(1, Math.min(2, d.dpr * d.zoom));
    SM.display = d;
  }

  function boot() {
    detectDisplay();
    SM.keys.register();
    views = el('main.views');
    var shell = el('div.shell', [buildNav(), views]);
    document.getElementById('app').appendChild(shell);
    SM.router.init(views);
    SM.focus.setBaseRoot(function () {
      var top = SM.router.top();
      if (!top) return [document.body];
      return top.fullscreen ? [top.el] : [nav, top.el];
    });
    SM.events.on('view', function (v) {
      markActive(v);
      document.body.classList.toggle('no-nav', !!v.fullscreen);
    });
    SM.events.on('auth-required', function () {
      ui.toast('The server needs a PIN — reconnect in Settings', 5000);
      SM.settings.set('token', '');
      SM.router.reset('setup', { change: false });
    });
    // Capture phase on window: keys reach the app before any element (e.g. the video
    // <object>) can swallow them.
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('keyup', onKeyUp, true);
    window.addEventListener('blur', function () { clearTimeout(enter.timer); enter.down = 0; enter.long = false; });
    SM.events.on('profile', renderProfile);
    // Tizen keeps the app alive in the background: coming back after a while (e.g. once the
    // server has fetched posters and plots) should show fresh data without restarting the app.
    var hiddenAt = 0;
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      var top = SM.router.top();
      if (hiddenAt && Date.now() - hiddenAt > 30000 && top && top.refresh && top.name !== 'player') {
        SM.router.markStale();
        top.refresh();
      }
    });
    // Expand the rail while it has focus (CSS :has() is not available on Tizen 6.5's Chromium).
    document.addEventListener('focus:sk', function (e) {
      nav.classList.toggle('open', nav.contains(e.target));
    });
    // Mouse/pointer support (Samsung "Smart Remote" pointer, and desktop development).
    if (SM.util.isTizen) {
      document.documentElement.classList.add('tv');
    } else {
      // Desktop development: hovering focuses (on the TV a stray pointer must not move focus)
      document.addEventListener('mouseover', function (e) {
        var f = e.target.closest && e.target.closest('.f');
        if (f && f !== SM.focus.get()) SM.focus.set(f, { noScroll: true });
      });
    }

    if (!SM.settings.get('server')) {
      SM.router.push('setup', {});
      return;
    }
    SM.api.probe(SM.settings.get('server')).then(function (info) {
      SM.settings.set('serverName', info.name);
      start(info);
    }, function () {
      goHome(); // home shows the error with a retry button; settings still reachable via the rail
      ui.toast('Cannot reach ' + (SM.settings.get('serverName') || 'the server') + ' — is the NAS on?', 6000);
    });
  }

  SM.app = { goHome: goHome, start: start, selectProfile: selectProfile, avatar: avatar };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
