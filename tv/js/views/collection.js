/* A collection (franchise folder, .nfo set or TMDB collection): its movies in Cover Flow, oldest first. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  SM.router.register('collection', function (params) {
    var title = el('h1.page-title', { text: '' });
    var count = el('span.page-count');
    var backdrop = SM.Backdrop();
    var shelf = el('div.shelf');
    var root = el('div.library.flow-mode.collection-page', [backdrop, el('div.page-head', [title, count]), shelf]);
    var view = { el: root, ownerId: params.id };
    var flow = null;

    function load(keepId) {
      SM.util.clear(shelf).appendChild(ui.spinner());
      return SM.api.collection(params.id).then(function (c) {
        title.textContent = c.title;
        count.textContent = SM.util.plural(c.items.length, 'movie') + (c.years ? ' · ' + c.years : '');
        SM.util.clear(shelf);
        if (!c.items.length) {
          shelf.appendChild(el('div.empty', [el('p', { text: 'Nothing left in this collection.' })]));
          return;
        }
        var start = 0;
        c.items.forEach(function (m, i) { if (m.id === keepId) start = i; });
        flow = SM.CoverFlow(c.items, {
          startIndex: start,
          onChange: function (it) { backdrop.set(it.scene || it.backdrop ? it : c); },
          onOpen: SM.openItem,
          onPlay: function (it) { SM.quickPlay(it); },
        });
        shelf.appendChild(flow.el);
        SM.focus.claim(view, flow.el);
      }, function (err) {
        SM.util.clear(shelf).appendChild(ui.errorBox(err, function () { load(); }));
        SM.focus.focusFirst(shelf);
      });
    }

    view.refresh = function () { load(flow && flow.current() ? flow.current().id : null); };
    view.onKey = function (action) {
      var f = SM.focus.get();
      if (flow && f && flow.el.contains(f) && flow.handleKey(action)) return true;
      return false;
    };
    load();
    return view;
  });
})();
