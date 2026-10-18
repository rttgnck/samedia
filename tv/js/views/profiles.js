/* "Who's watching?": pick a profile. Profiles (and which ones each TV offers) are managed
 * in the Samedia admin page on the server. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui, S = SM.settings;

  SM.router.register('profiles', function () {
    var tiles = el('div.profile-tiles', { 'data-group': '' });
    var root = el('div.profiles', [el('h1', { text: "Who's watching?" }), tiles]);
    var view = { el: root, fullscreen: true };

    function tile(p) {
      var t = el('div.profile-tile.f', { onclick: function () { SM.app.selectProfile(p); SM.app.goHome(); } }, [
        el('div.profile-avatar', { style: { background: p.color }, text: p.name.charAt(0).toUpperCase() }),
        el('div.profile-name', { text: p.name }),
        p.kids ? el('div.profile-kids', { text: 'Kids' }) : null,
      ]);
      t.dataset.id = p.id;
      return t;
    }

    function load() {
      return SM.api.profiles().then(function (r) {
        SM.util.clear(tiles);
        r.profiles.forEach(function (p) { tiles.appendChild(tile(p)); });
        var current = tiles.querySelector('[data-id="' + S.get('profileId') + '"]');
        SM.focus.claim(view, current || tiles.firstChild);
      }, function (err) {
        SM.util.clear(tiles).appendChild(ui.errorBox(err, load));
        SM.focus.focusFirst(tiles);
      });
    }

    view.onKey = function (action) {
      // Opened from the rail while already someone: Back returns to where we were
      if (action === 'back' && S.get('profileId') && SM.router.depth() === 1) { SM.app.goHome(); return true; }
      return false;
    };
    view.refresh = load;
    load();
    return view;
  });
})();
