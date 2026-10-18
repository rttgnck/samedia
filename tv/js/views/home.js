/* Home: backdrop hero that follows focus + rows (Continue Watching, Next Up, Recently Added, genres). */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  /** Shared full-bleed backdrop with crossfade, used by home and library screens. */
  function Backdrop() {
    var a = el('div.backdrop-layer'), b = el('div.backdrop-layer');
    var root = el('div.backdrop', [a, b, el('div.backdrop-shade')]);
    var front = a, currentUrl = null, pending = null;
    root.set = SM.util.debounce(function (url) {
      if (url === currentUrl) return;
      currentUrl = url;
      var back = front === a ? b : a;
      if (!url) {
        front.classList.remove('on');
        back.classList.remove('on');
        return;
      }
      var img = new Image();
      pending = img;
      img.onload = function () {
        if (pending !== img) return;
        back.style.backgroundImage = 'url("' + img.src + '")';
        back.classList.add('on');
        front.classList.remove('on');
        front = back;
      };
      img.src = SM.api.art(url, 1280);
    }, 220);
    return root;
  }
  SM.Backdrop = Backdrop;

  function heroInfo() {
    var title = el('h1.hero-title'), meta = el('div.hero-meta'), plot = el('p.hero-plot'), hint = el('div.hero-hint');
    var node = el('div.hero-info', [title, meta, plot, hint]);
    node.show = function (item) {
      if (!item) return;
      var isEp = item.kind === 'episode';
      title.textContent = isEp ? item.show_title : item.title;
      SM.util.clear(meta);
      var bits = [];
      if (isEp) bits.push(SM.util.episodeCode(item) + ' · ' + item.title);
      if (item.year && !isEp) bits.push(String(item.year));
      if (item.kind === 'show' && item.episode_count) bits.push(item.episode_count + ' episodes');
      if (item.duration) bits.push(SM.util.runtime(item.duration));
      if (item.rating) bits.push('★ ' + item.rating);
      if (item.genres && item.genres.length) bits.push(item.genres.slice(0, 3).join(', '));
      meta.appendChild(el('span', { text: bits.join('   ·   ') }));
      var b = ui.badges(item.badges);
      if (b) meta.appendChild(b);
      plot.textContent = item.plot || '';
      hint.textContent = item.position && !item.watched ? 'OK  details     ▶  resume from ' + SM.util.clock(item.position) : 'OK  details     ▶  play';
    };
    return node;
  }

  function open(item) {
    if (item.kind === 'show') SM.router.push('show', { id: item.id });
    else SM.router.push('detail', { id: item.id });
  }
  SM.openItem = open;

  /** ▶ on a focused card plays immediately (resuming); shows open their next-up episode. */
  function quickPlay(item) {
    if (item.kind === 'show') {
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
    var backdrop = Backdrop();
    var info = heroInfo();
    var rows = el('div.rows', { 'data-scroll': 'y', 'data-pad': '0' });
    var body = el('div.home-body', [ui.spinner()]);
    var root = el('div.home', [backdrop, info, body]);
    var view = { el: root, section: 'home' };

    root.addEventListener('focus:sk', function (e) {
      var card = e.target.closest && e.target.closest('.card');
      if (!card || !card._item) return;
      info.show(card._item);
      backdrop.set(card._item.backdrop);
    });

    function render(data) {
      SM.util.clear(body);
      SM.util.clear(rows);
      if (!data.rows.length) {
        body.appendChild(el('div.empty', [
          el('h2', { text: 'Your library is empty' }),
          el('p', { text: 'Add media folders in the server admin page (' + SM.api.base() + ') and run a scan.' }),
          ui.button('Refresh', 'restart', load, 'primary autofocus'),
        ]));
        SM.focus.focusFirst(body);
        return;
      }
      data.rows.forEach(function (r) { rows.appendChild(ui.row(r.title, r.items, r.style, open)); });
      body.appendChild(rows);
      var first = rows.querySelector('.card');
      SM.focus.claim(view, first);
    }

    function load() {
      return SM.api.home().then(render, function (err) {
        SM.util.clear(body).appendChild(ui.errorBox(err, load));
        SM.focus.focusFirst(body);
      });
    }

    view.refresh = function () {
      var focused = SM.focus.get();
      var id = focused && focused.dataset ? focused.dataset.id : null;
      SM.api.home().then(function (data) {
        render(data);
        var again = id && rows.querySelector('.card[data-id="' + id + '"]');
        if (again) SM.focus.set(again, { instant: true });
      }, function () {});
    };
    view.onKey = function (action) {
      var f = SM.focus.get();
      if ((action === 'play' || action === 'playpause') && f && f._item) {
        quickPlay(f._item);
        return true;
      }
      return false;
    };
    load();
    return view;
  });
})();
