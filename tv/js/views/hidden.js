/* Titles the current profile hid (long-press OK → Hide). OK on one offers Unhide. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  SM.router.register('hidden', function () {
    var grid = el('div.grid', { 'data-group': '' });
    var scroller = el('div.grid-scroll', { 'data-scroll': 'y-near', 'data-pad': '80' }, [grid]);
    var count = el('span.page-count');
    var root = el('div.library.hidden-page', [
      el('div.page-head', [el('h1.page-title', { text: 'Hidden titles' }), count]), scroller,
    ]);
    var view = { el: root, section: 'settings' };

    grid.addEventListener('click', function (e) {
      var card = e.target.closest('.card');
      if (card) SM.context.show(card._item, { hidden: true });
    });

    function load() {
      SM.util.clear(grid).appendChild(ui.spinner());
      return SM.api.hidden().then(function (r) {
        SM.util.clear(grid);
        count.textContent = (SM.settings.get('profileName') || '') + ' · ' + r.items.length + ' hidden';
        if (!r.items.length) {
          grid.appendChild(el('div.empty', [el('h2', { text: 'Nothing hidden' }),
            el('p', { text: 'Hold OK on any movie, show or collection and choose Hide to keep it out of this profile.' })]));
          SM.focus.claim(view, null);
          return;
        }
        r.items.forEach(function (it) { grid.appendChild(ui.posterCard(it)); });
        SM.focus.claim(view, grid.firstChild);
      }, function (err) {
        SM.util.clear(grid).appendChild(ui.errorBox(err, load));
        SM.focus.focusFirst(grid);
      });
    }

    view.refresh = load;
    load();
    return view;
  });
})();
