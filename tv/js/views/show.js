/* TV show page: info, next-up button, season tabs, episode row. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  SM.router.register('show', function (params) {
    var backdrop = SM.Backdrop();
    var body = el('div.show-body', [ui.spinner()]);
    var root = el('div.show', [backdrop, body]);
    var view = { el: root, ownerId: params.id };
    view.contextItem = function () { return show; };
    var show = null, season = null;
    var epInfo = el('div.ep-info');

    function episodesOf(s) {
      return show.episodes.filter(function (e) { return e.season === s; });
    }

    function renderEpisodes(track) {
      SM.util.clear(track);
      episodesOf(season).forEach(function (e) { track.appendChild(ui.episodeCard(e)); });
    }

    function describe(e) {
      SM.util.clear(epInfo);
      if (!e) return;
      epInfo.appendChild(el('h3', { text: SM.util.episodeCode(e) + '  ·  ' + e.title }));
      var meta = [SM.util.runtime(e.duration)];
      if (e.rating) meta.push('★ ' + e.rating);
      if (e.position && !e.watched) meta.push(SM.util.clock(e.position) + ' watched');
      epInfo.appendChild(el('div.sub', { text: meta.filter(Boolean).join('  ·  ') }));
      epInfo.appendChild(el('p', { text: e.plot || '' }));
    }

    function seasonName(s) { return s === 0 ? 'Specials' : 'Season ' + s; }

    function render(focusId) {
      var next = show.next_up;
      var actions = [];
      if (next) {
        var label = (next.position > 30 ? 'Resume ' : 'Play ') + SM.util.episodeCode(next);
        actions.push(ui.button(label, 'play', function () { SM.player.play(next, { resume: true }); }, 'primary autofocus'));
      }
      actions.push(ui.button(show.unwatched ? 'Mark show watched' : 'Mark unwatched', 'check', function () {
        SM.api.showWatched(show.id, !!show.unwatched).then(function () { SM.router.markStale(); load(); });
      }));

      var tabs = el('div.tabs', { 'data-group': '' });
      show.seasons.forEach(function (s) {
        var tab = el('div.tab.f' + (s.season === season ? '.active' : ''), {
          text: seasonName(s.season) + (s.unwatched ? '' : '  ✓'),
          onclick: function () { pickSeason(s.season); },
        });
        tab.addEventListener('focus:sk', function () {
          // Moving across tabs switches season immediately, like most TV apps.
          if (season !== s.season) pickSeason(s.season, true);
        });
        tabs.appendChild(tab);
      });

      var track = el('div.row-track', { 'data-scroll': 'x', 'data-pad': '0' });
      var episodes = el('section.row.episodes', { 'data-group': '' }, [track]);
      episodes.addEventListener('click', function (e) {
        var card = e.target.closest('.card');
        if (card) SM.router.push('detail', { id: card._item.id });
      });
      episodes.addEventListener('focus:sk', function (e) {
        var card = e.target.closest && e.target.closest('.card');
        if (card) describe(card._item);
      });

      SM.util.clear(body);
      body.appendChild(el('div.show-info', [
        el('h1.detail-title', { text: show.title }),
        el('div.detail-meta', [el('span', { text: [show.year, show.seasons.length + (show.seasons.length === 1 ? ' season' : ' seasons'),
          show.rating ? '★ ' + show.rating : null, (show.genres || []).join(', ')].filter(Boolean).join('   ·   ') })]),
        show.plot ? el('p.detail-plot.short', { text: show.plot }) : null,
        el('div.actions', { 'data-group': '' }, actions),
      ]));
      body.appendChild(tabs);
      body.appendChild(episodes);
      body.appendChild(epInfo);
      renderEpisodes(track);
      view._track = track;
      view._tabs = tabs;

      backdrop.set(show.backdrop);
      var target = focusId && body.querySelector('[data-id="' + focusId + '"]');
      SM.focus.claim(view, target || body.querySelector('.autofocus') || tabs.firstChild);
      if (!target) describe(next && next.season === season ? next : episodesOf(season)[0]);
    }

    function pickSeason(s, keepFocus) {
      season = s;
      Array.prototype.forEach.call(view._tabs.children, function (t, i) {
        t.classList.toggle('active', show.seasons[i].season === s);
      });
      renderEpisodes(view._track);
      view._track.scrollLeft = 0;
      describe(episodesOf(s)[0]);
      if (!keepFocus) SM.focus.set(view._track.firstChild);
    }

    function load(focusId) {
      return SM.api.show(params.id).then(function (data) {
        show = data;
        if (season === null || !show.seasons.some(function (s) { return s.season === season; })) {
          season = show.next_up ? show.next_up.season : (show.seasons[0] ? show.seasons[0].season : 1);
        }
        render(focusId);
      }, function (err) {
        SM.util.clear(body).appendChild(ui.errorBox(err, function () { load(); }));
        SM.focus.focusFirst(body);
      });
    }

    view.refresh = function () {
      var f = SM.focus.get();
      load(f && f.dataset ? f.dataset.id : null);
    };
    view.onKey = function (action) {
      var f = SM.focus.get();
      if ((action === 'play' || action === 'playpause') && f && f._item) {
        SM.player.play(f._item, { resume: true });
        return true;
      }
      return false;
    };
    load();
    return view;
  });
})();
