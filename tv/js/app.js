/* App shell: navigation rail, global key dispatch, boot. */
(function () {
  'use strict';

  SM.VERSION = '0.1.0';
  var el = SM.util.el, ui = SM.ui;

  var SECTIONS = [
    { id: 'home', label: 'Home', icon: 'home', view: 'home' },
    { id: 'movies', label: 'Movies', icon: 'film', view: 'library', params: { kind: 'movies' } },
    { id: 'shows', label: 'TV Shows', icon: 'tv', view: 'library', params: { kind: 'shows' } },
    { id: 'search', label: 'Search', icon: 'search', view: 'search' },
    { id: 'settings', label: 'Settings', icon: 'gear', view: 'settings' },
  ];

  var nav, views, lastBack = 0;

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
    nav.appendChild(el('div.nav-brand', { text: 'S' }));
    return nav;
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
    if (!action) return;
    e.preventDefault();

    var modal = ui.topModal();
    if (modal && action === 'back') { modal._close && modal._close(); return; }

    var top = SM.router.top();
    if (top && top.onKey && top.onKey(action, e)) return;

    if (action === 'exit') { exitApp(); return; }

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

  function boot() {
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
    document.addEventListener('keydown', onKey);
    // Expand the rail while it has focus (CSS :has() is not available on Tizen 6.5's Chromium).
    document.addEventListener('focus:sk', function (e) {
      nav.classList.toggle('open', nav.contains(e.target));
    });
    // Mouse/pointer support (Samsung "Smart Remote" pointer, and desktop development).
    document.addEventListener('mouseover', function (e) {
      var f = e.target.closest && e.target.closest('.f');
      if (f && f !== SM.focus.get()) SM.focus.set(f, { noScroll: true });
    });

    if (!SM.settings.get('server')) {
      SM.router.push('setup', {});
      return;
    }
    SM.api.probe(SM.settings.get('server')).then(function (info) {
      SM.settings.set('serverName', info.name);
      goHome();
    }, function () {
      goHome(); // home shows the error with a retry button; settings still reachable via the rail
      ui.toast('Cannot reach ' + (SM.settings.get('serverName') || 'the server') + ' — is the NAS on?', 6000);
    });
  }

  SM.app = { goHome: goHome };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
