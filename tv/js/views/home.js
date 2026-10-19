/* Home: Cover Flow of one shelf at a time (Continue Watching, Next Up, New Movies, New TV,
 * Collections, genres). Shelf tabs sit above the flow; moving across them switches shelf. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  /** Shared full-bleed backdrop with crossfade, used by every browsing screen: a title card of
   *  what's in focus. Takes an item and uses a picture other than its poster (a text-free scene,
   *  else its backdrop) with its logo faded in; a poster or album cover (blur) is the fallback. */
  function Backdrop() {
    var a = el('div.backdrop-layer'), b = el('div.backdrop-layer');
    var logo = el('img.backdrop-logo', { alt: '' });
    var root = el('div.backdrop', [a, b, el('div.backdrop-shade'), logo]);
    var front = a, currentKey = null, pending = null;

    function pick(it) {
      if (!it) return null;
      if (typeof it === 'string') return { url: it };
      if (it.scene) return { url: it.scene, logo: it.logo };
      if (it.backdrop) return { url: it.backdrop, logo: it.logo };
      if (it.poster) return { url: it.poster, logo: it.logo, blur: true };
      return it.logo ? { url: null, logo: it.logo } : null;
    }

    root.set = SM.util.debounce(function (it) {
      var p = pick(it);
      var key = p ? (p.url || '') + '|' + (p.logo || '') : null;
      if (key === currentKey) return;
      currentKey = key;
      var back = front === a ? b : a;
      logo.classList.remove('on');
      if (p && p.logo) {
        var li = new Image();
        li.onload = function () { if (currentKey === key) { logo.src = li.src; logo.classList.add('on'); } };
        li.src = SM.api.art(p.logo, 960);
      }
      if (!p || !p.url) {
        front.classList.remove('on');
        back.classList.remove('on');
        return;
      }
      var img = new Image();
      pending = img;
      img.onload = function () {
        if (pending !== img) return;
        back.style.backgroundImage = 'url("' + img.src + '")';
        back.classList.toggle('blur', !!p.blur);
        back.classList.add('on');
        front.classList.remove('on');
        front = back;
      };
      img.src = SM.api.art(p.url, p.blur ? 640 : 1920);
    }, 220);
    return root;
  }
  SM.Backdrop = Backdrop;

  function open(item) {
    if (item.kind === 'show') SM.router.push('show', { id: item.id });
    else if (item.kind === 'collection') SM.router.push('collection', { id: item.id });
    else SM.router.push('detail', { id: item.id });
  }
  SM.openItem = open;

  /** ▶ on a focused card plays immediately (resuming); shows open their next-up episode. */
  function quickPlay(item) {
    if (item.kind === 'collection') {
      SM.api.collection(item.id).then(function (c) {
        var next = c.items.filter(function (m) { return !m.watched; })[0] || c.items[0];
        if (next) SM.player.play(next, { resume: true });
      });
    } else if (item.kind === 'show') {
      SM.api.show(item.id).then(function (s) {
        if (s.next_up) SM.player.play(s.next_up, { resume: true });
        else open(item);
      });
    } else {
      SM.player.play(item, { resume: true });
    }
  }
  SM.quickPlay = quickPlay;

  SM.router.register('home', function () {
    var S = SM.settings;
    var backdrop = Backdrop();
    var tabs = el('div.shelf-tabs', { 'data-group': '' });
    var stage = el('div.home-flow');
    var body = el('div.home-main', [el('div.home-head', [tabs]), stage]);
    var root = el('div.home.flow-home', [backdrop, body]);
    var view = { el: root, section: 'home' };
    var shelves = [], active = 0, flow = null, tabTimer = null;

    function showShelf(i, focusFlow, keepId) {
      if (!shelves[i]) return;
      active = i;
      S.set('homeShelf', shelves[i].id);
      Array.prototype.forEach.call(tabs.children, function (t, j) { t.classList.toggle('active', j === i); });
      var items = shelves[i].items, start = 0;
      if (keepId) items.forEach(function (it, j) { if (it.id === keepId) start = j; });
      var bookmarkShelf = shelves[i].id === 'bookmarks';
      flow = SM.CoverFlow(items, {
        startIndex: start,
        onChange: function (it) { backdrop.set(it); },
        onOpen: open,
        onPlay: function (it) { quickPlay(it); },
        // Bookmarks shelf: OK lists that title's bookmarks to play from
        onEnter: bookmarkShelf ? function (it) { SM.context.bookmarksMenu(it); } : null,
      });
      SM.util.clear(stage).appendChild(flow.el);
      if (focusFlow) SM.focus.set(flow.el, { noScroll: true });
    }

    function render(data, keepId) {
      shelves = data.shelves || data.rows || [];
      SM.util.clear(tabs);
      SM.util.clear(stage);
      flow = null;
      if (!shelves.length) {
        stage.appendChild(el('div.empty', [
          el('h2', { text: S.get('profileKids') ? 'Nothing for kids yet' : 'Your library is empty' }),
          el('p', { text: S.get('profileKids')
            ? 'Kids profiles show titles rated G, PG, TV-Y, TV-Y7, TV-G or TV-PG. Add a TMDB key in the server admin page so titles get their age rating.'
            : 'Add media folders in the server admin page (' + SM.api.base() + ') and run a scan.' }),
          ui.button('Refresh', 'restart', load, 'primary autofocus'),
        ]));
        SM.focus.focusFirst(stage);
        return;
      }
      shelves.forEach(function (sh, i) {
        var tab = el('div.tab.f', { text: sh.title, onclick: function () { showShelf(i, true); } });
        // Resting on a tab switches to its shelf (no OK needed), like the navigation rail.
        tab.addEventListener('focus:sk', function () {
          clearTimeout(tabTimer);
          tabTimer = setTimeout(function () { if (SM.focus.get() === tab && active !== i) showShelf(i, false); }, 300);
        });
        tabs.appendChild(tab);
      });
      var remembered = 0;
      shelves.forEach(function (sh, i) { if (sh.id === S.get('homeShelf')) remembered = i; });
      showShelf(remembered, false, keepId);
      SM.focus.claim(view, flow.el);
    }

    function load() {
      SM.util.clear(stage).appendChild(ui.spinner());
      return SM.api.home().then(function (d) { render(d); }, function (err) {
        SM.util.clear(stage).appendChild(ui.errorBox(err, load));
        SM.focus.focusFirst(stage);
      });
    }

    view.refresh = function () {
      var keep = flow && flow.current() ? flow.current().id : null;
      // Refresh runs as the view reappears (e.g. back from the player), before the router restores
      // focus: judge by what this view had focused when it was covered, not the current focus.
      var had = view.focus || SM.focus.get();
      var onTab = !!(had && tabs.contains(had));
      SM.api.home().then(function (d) {
        render(d, keep);                          // render() puts focus on the cover flow
        if (onTab && tabs.children[active]) SM.focus.set(tabs.children[active], { instant: true });
      }, function () {});
    };
    view.onKey = function (action) {
      var f = SM.focus.get();
      if (flow && f && flow.el.contains(f) && flow.handleKey(action)) return true;
      if (flow && f === flow.el && action === 'down' && shelves.length > 1) {
        // Down on the flow: next shelf (wraps), so every shelf is reachable without the tabs.
        showShelf((active + 1) % shelves.length, true);
        return true;
      }
      return false;
    };
    load();
    return view;
  });
})();
