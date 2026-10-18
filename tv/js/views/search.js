/* Search with an on-screen keyboard (no system IME juggling). */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  SM.router.register('search', function () {
    var query = '';
    var field = el('div.search-field', [ui.icon('search'), el('span.q', { text: '' }), el('span.caret')]);
    var results = el('div.search-results', { 'data-scroll': 'y', 'data-pad': '0' });
    var hint = el('p.search-hint', { text: 'Type with the keyboard or the number keys on your remote.' });
    var run = SM.util.debounce(function () {
      if (!query.trim()) {
        SM.util.clear(results).appendChild(hint);
        return;
      }
      var q = query;
      SM.api.search(q).then(function (r) {
        if (q !== query) return;
        SM.util.clear(results);
        if (r.movies.length) results.appendChild(ui.row('Movies', r.movies, 'poster', SM.openItem));
        if (r.shows.length) results.appendChild(ui.row('TV Shows', r.shows, 'poster', SM.openItem));
        if (r.episodes.length) results.appendChild(ui.row('Episodes', r.episodes, 'landscape', SM.openItem));
        if (!results.children.length) results.appendChild(el('p.search-hint', { text: 'No results for “' + q + '”.' }));
      }, function (err) {
        SM.util.clear(results).appendChild(el('p.search-hint', { text: err.message }));
      });
    }, 350);
    var kb = ui.keyboard('text', '', function (v) {
      query = v;
      field.querySelector('.q').textContent = v;
      run();
    });
    var root = el('div.search', [
      el('div.search-left', [el('h1.page-title', { text: 'Search' }), field, kb]),
      results,
    ]);
    results.appendChild(hint);
    var view = { el: root, section: 'search' };
    view.onKey = function (action) {
      if (action.indexOf('digit:') === 0) {
        kb.handleDigit(action.slice(6));
        return true;
      }
      var f = SM.focus.get();
      if ((action === 'play' || action === 'playpause') && f && f._item) {
        SM.quickPlay(f._item);
        return true;
      }
      return false;
    };
    return view;
  });
})();
