/* Movies / TV Shows: Cover Flow shelf (default) or poster grid, with sort + filter. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  var SORTS = [
    { id: 'title', label: 'A–Z' },
    { id: 'added', label: 'Recently added' },
    { id: 'year', label: 'Release year' },
    { id: 'rating', label: 'Rating' },
  ];
  var BATCH = 70; // posters appended per chunk; keeps first paint fast on the TV

  SM.router.register('library', function (params) {
    var kind = params.kind; // 'movies' | 'shows'
    var state = { sort: 'title', genre: null, unwatched: false, genres: [] };
    var title = el('h1.page-title', { text: kind === 'movies' ? 'Movies' : 'TV Shows' });
    var count = el('span.page-count');
    var sortBtn = ui.button('Sort', 'sort', chooseSort, 'chip');
    var genreBtn = ui.button('Genre', 'filter', chooseGenre, 'chip');
    var unwatchedBtn = kind === 'movies' ? ui.button('Unwatched', 'eye', toggleUnwatched, 'chip') : null;
    var groupBtn = kind === 'movies' ? ui.button('Collections', 'stack', toggleGroup, 'chip') : null;
    var modeBtn = ui.button('View', 'film', toggleMode, 'chip');
    var toolbar = el('div.toolbar', { 'data-group': '' }, [sortBtn, genreBtn, unwatchedBtn, groupBtn, modeBtn]);
    var grid = el('div.grid', { 'data-group': '', 'data-no-memory': '' });
    var scroller = el('div.grid-scroll', { 'data-scroll': 'y-near', 'data-pad': '80' }, [grid]);
    var backdrop = SM.Backdrop();
    var shelf = el('div.shelf');
    var root = el('div.library', [backdrop, el('div.page-head', [title, count, toolbar]), scroller, shelf]);
    var view = { el: root, section: kind };
    var items = [], rendered = 0, flow = null;

    function flowMode() { return SM.settings.get('libraryView') !== 'grid'; }

    function label() {
      sortBtn.lastChild.textContent = SORTS.filter(function (s) { return s.id === state.sort; })[0].label;
      genreBtn.lastChild.textContent = state.genre || 'All genres';
      if (unwatchedBtn) unwatchedBtn.classList.toggle('active', state.unwatched);
      if (groupBtn) groupBtn.classList.toggle('active', !!SM.settings.get('groupCollections'));
      modeBtn.lastChild.textContent = flowMode() ? 'Cover Flow' : 'Grid';
      root.classList.toggle('flow-mode', flowMode());
    }

    function toggleMode() {
      var keep = flow && flowMode() ? flow.current() : null;
      SM.settings.set('libraryView', flowMode() ? 'grid' : 'flow');
      load(keep ? keep.id : null, true);
    }

    function buildFlow(keepFocusId) {
      var start = 0;
      if (keepFocusId) items.forEach(function (it, i) { if (it.id === keepFocusId) start = i; });
      flow = SM.CoverFlow(items, {
        startIndex: start,
        onChange: function (it) { backdrop.set(it); },
        onOpen: SM.openItem,
        onPlay: function (it) { SM.quickPlay(it); },
      });
      SM.util.clear(shelf).appendChild(flow.el);
    }

    function chooseSort() {
      ui.menu('Sort by', SORTS.map(function (s) {
        return { label: s.label, selected: s.id === state.sort, action: function () { state.sort = s.id; load(); } };
      }));
    }

    function chooseGenre() {
      var opts = [{ label: 'All genres', selected: !state.genre, action: function () { state.genre = null; load(); } }];
      state.genres.forEach(function (g) {
        opts.push({ label: g, selected: g === state.genre, action: function () { state.genre = g; load(); } });
      });
      ui.menu('Genre', opts);
    }

    /** Fold franchise movies into one collection cover (Movies only). */
    function toggleGroup() {
      SM.settings.set('groupCollections', !SM.settings.get('groupCollections'));
      load(null, true);
    }

    function toggleUnwatched() {
      state.unwatched = !state.unwatched;
      load();
    }

    function appendBatch() {
      var end = Math.min(items.length, rendered + BATCH);
      var frag = document.createDocumentFragment();
      for (var i = rendered; i < end; i++) frag.appendChild(ui.posterCard(items[i]));
      grid.appendChild(frag);
      rendered = end;
    }

    // Grow the grid as focus approaches the end.
    root.addEventListener('focus:sk', function (e) {
      var card = e.target.closest && e.target.closest('.card');
      if (!card) return;
      var idx = Array.prototype.indexOf.call(grid.children, card);
      if (idx > rendered - 22 && rendered < items.length) appendBatch();
    });
    grid.addEventListener('click', function (e) {
      var card = e.target.closest('.card');
      if (card) SM.openItem(card._item);
    });

    function load(keepFocusId, focusToolbar) {
      label();
      flow = null;
      SM.util.clear(shelf);
      backdrop.set(null);
      var q = '?sort=' + state.sort + (state.genre ? '&genre=' + encodeURIComponent(state.genre) : '') +
        (state.unwatched ? '&unwatched=true' : '') +
        (kind === 'movies' && SM.settings.get('groupCollections') && !state.unwatched ? '&group=true' : '');
      SM.util.clear(flowMode() ? shelf : grid).appendChild(ui.spinner());
      var req = kind === 'movies' ? SM.api.movies(q) : SM.api.shows(q);
      return req.then(function (data) {
        items = data.items;
        state.genres = data.genres;
        rendered = 0;
        SM.util.clear(grid);
        SM.util.clear(shelf);
        var titles = items.reduce(function (n, it) { return n + (it.kind === 'collection' ? it.item_count : 1); }, 0);
        count.textContent = SM.util.plural(titles, kind === 'movies' ? 'movie' : 'show');
        if (!items.length) {
          grid.appendChild(el('div.empty', [el('p', { text: 'Nothing here yet.' })]));
          return;
        }
        if (flowMode()) {
          buildFlow(keepFocusId);
          SM.focus.claim(view, focusToolbar ? modeBtn : flow.el);
          return;
        }
        appendBatch();
        var target = keepFocusId && grid.querySelector('.card[data-id="' + keepFocusId + '"]');
        SM.focus.claim(view, focusToolbar ? (groupBtn || modeBtn) : (target || grid.firstChild));
      }, function (err) {
        var box = flowMode() ? shelf : grid;
        SM.util.clear(box).appendChild(ui.errorBox(err, function () { load(); }));
        SM.focus.focusFirst(box);
      });
    }

    view.refresh = function () {
      var f = SM.focus.get();
      if (flow) load(flow.current() ? flow.current().id : null);
      else load(f && f.dataset ? f.dataset.id : null);
    };
    view.onKey = function (action) {
      var f = SM.focus.get();
      if (flow && f && flow.el.contains(f) && flow.handleKey(action)) return true;
      if ((action === 'play' || action === 'playpause') && f && f._item) {
        SM.quickPlay(f._item);
        return true;
      }
      if (action === 'chdown' || action === 'chup') {
        // Page through the grid quickly with CH+/CH−.
        var cards = grid.children, idx = Array.prototype.indexOf.call(cards, f);
        if (idx < 0) return false;
        var perRow = Math.max(1, Math.round(grid.clientWidth / (cards[0].offsetWidth + 28)));
        var target = idx + (action === 'chdown' ? perRow * 3 : -perRow * 3);
        while (target >= rendered && rendered < items.length) appendBatch();
        target = Math.max(0, Math.min(rendered - 1, target));
        SM.focus.set(cards[target]);
        return true;
      }
      return false;
    };
    load();
    return view;
  });
})();
