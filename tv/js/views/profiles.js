/* "Who's watching?": pick a profile; hold OK on one to change its picture. Profiles (and
 * which ones each TV offers) are managed in the Samedia admin page on the server. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui, S = SM.settings;

  function hasPictures() { return (SM.serverFeatures || []).indexOf('avatars') !== -1; }

  /** Grid of pictures for profile p (from the server); done(profile) after a change. */
  function pickPicture(p, done) {
    SM.api.avatars().then(function (r) {
      var grid = el('div.picture-grid');
      var layer = el('div.modal', [el('div.dialog.picture-picker', [
        el('h3', { text: 'Choose a picture for ' + p.name }), grid,
      ])]);
      var close = function () {
        if (!layer.parentNode) return;
        SM.focus.popLayer(layer);
        layer.parentNode.removeChild(layer);
      };
      var choose = function (a) {
        close();
        if (a === (p.avatar || '')) return;
        SM.api.setAvatar(p.id, a).then(function (np) {
          if (np.id === S.get('profileId')) {
            S.set('profileAvatar', np.avatar || '');
            SM.events.emit('profile', np);
          }
          if (done) done(np);
        }, function (err) { ui.toast((err && err.message) || "Couldn't change the picture"); });
      };
      // every picture, then "just the initial"
      r.avatars.concat(['']).forEach(function (a) {
        var current = a === (p.avatar || '');
        grid.appendChild(el('div.picture-choice.f' + (current ? '.selected.autofocus' : ''),
          { onclick: function () { choose(a); } }, [SM.app.avatar(p.name, p.color, false, a, 'picture')]));
      });
      layer._close = close;
      document.getElementById('overlays').appendChild(layer);
      SM.focus.pushLayer(layer);
    }, function (err) { ui.toast((err && err.message) || "Couldn't load the pictures"); });
  }

  /** Name shown for a picture in Settings. */
  function pictureName(a) { return a ? a.charAt(0).toUpperCase() + a.slice(1) : 'Initial'; }

  SM.profiles = { pickPicture: pickPicture, hasPictures: hasPictures, pictureName: pictureName };

  SM.router.register('profiles', function () {
    var tiles = el('div.profile-tiles', { 'data-group': '' });
    var hint = el('div.profiles-hint', { text: 'Hold OK on a profile to change its picture' });
    var root = el('div.profiles', [el('h1', { text: "Who's watching?" }), tiles, hint]);
    var view = { el: root, fullscreen: true };

    function tile(p) {
      var t = el('div.profile-tile.f', { onclick: function () { SM.app.selectProfile(p); SM.app.goHome(); } }, [
        SM.app.avatar(p.name, p.color, false, p.avatar, 'profile-avatar'),
        el('div.profile-name', { text: p.name }),
        p.kids ? el('div.profile-kids', { text: 'Kids' }) : null,
      ]);
      t.dataset.id = p.id;
      if (hasPictures()) t._hold = function () { pickPicture(p, function (np) { load(np.id); }); };
      return t;
    }

    function load(focusId) {
      hint.hidden = !hasPictures();
      return SM.api.profiles().then(function (r) {
        SM.util.clear(tiles);
        r.profiles.forEach(function (p) { tiles.appendChild(tile(p)); });
        var current = tiles.querySelector('[data-id="' + (focusId || S.get('profileId')) + '"]');
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
    view.refresh = function () { return load(); };
    load();
    return view;
  });
})();
