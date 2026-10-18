/* "Who's watching?": pick a profile, add one, or manage them (rename, kids mode, colour, delete). */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui, S = SM.settings;
  var COLORS = ['#5b8cff', '#ff6b6b', '#3ecf8e', '#ffb547', '#b46bff', '#33c3ff', '#ff7ac6', '#8a93a6'];
  var COLOR_NAMES = ['Blue', 'Red', 'Green', 'Amber', 'Purple', 'Sky', 'Pink', 'Grey'];

  SM.router.register('profiles', function () {
    var tiles = el('div.profile-tiles', { 'data-group': '' });
    var manageBtn = ui.button('Manage profiles', 'gear', toggleManage, 'ghost');
    var hint = el('p.profiles-hint', { text: '' });
    var root = el('div.profiles', [
      el('h1', { text: "Who's watching?" }), tiles, hint, el('div.profiles-actions', { 'data-group': '' }, [manageBtn]),
    ]);
    var view = { el: root, fullscreen: true };
    var profiles = [], managing = false;

    function tile(p) {
      var t = el('div.profile-tile.f', { onclick: function () { managing ? manage(p) : choose(p); } }, [
        el('div.profile-avatar', { style: { background: p.color }, text: p.name.charAt(0).toUpperCase() },
          managing ? [el('span.profile-edit', [ui.icon('gear')])] : null),
        el('div.profile-name', { text: p.name }),
        p.kids ? el('div.profile-kids', { text: 'Kids' }) : null,
      ]);
      t.dataset.id = p.id;
      return t;
    }

    function render(focusId) {
      SM.util.clear(tiles);
      profiles.forEach(function (p) { tiles.appendChild(tile(p)); });
      if (profiles.length < 12) {
        var add = el('div.profile-tile.add.f', { onclick: addProfile }, [
          el('div.profile-avatar', [ui.icon('plus')]), el('div.profile-name', { text: 'Add profile' }),
        ]);
        add.dataset.id = 'add';
        tiles.appendChild(add);
      }
      root.classList.toggle('managing', managing);
      manageBtn.lastChild.textContent = managing ? 'Done' : 'Manage profiles';
      hint.textContent = managing ? 'Select a profile to rename it, change its colour, turn kids mode on or off, or delete it.'
        : 'Kids profiles only show titles rated G, PG, TV-Y, TV-Y7, TV-G or TV-PG.';
      var target = (focusId && tiles.querySelector('[data-id="' + focusId + '"]')) ||
        tiles.querySelector('[data-id="' + S.get('profileId') + '"]') || tiles.firstChild;
      SM.focus.claim(view, target);
    }

    function load(focusId) {
      return SM.api.profiles().then(function (r) {
        profiles = r.profiles;
        render(focusId);
      }, function (err) {
        SM.util.clear(tiles).appendChild(ui.errorBox(err, function () { load(); }));
        SM.focus.focusFirst(tiles);
      });
    }

    function choose(p) {
      SM.app.selectProfile(p);
      SM.app.goHome();
    }

    function toggleManage() {
      managing = !managing;
      render();
    }

    function addProfile() {
      ui.prompt('New profile name', '', { capitalize: true, placeholder: 'e.g. Nick, Kids' }).then(function (name) {
        if (!name) return;
        ui.menu('Is this a kids profile?', [
          { label: 'Regular profile', sub: 'Sees the whole library', action: function () { create(name, false); } },
          { label: 'Kids profile', sub: 'Only titles rated G, PG, TV-Y, TV-Y7, TV-G or TV-PG', action: function () { create(name, true); } },
        ]);
      });
    }

    function create(name, kids) {
      var used = profiles.map(function (p) { return p.color; });
      var color = COLORS.filter(function (c) { return used.indexOf(c) === -1; })[0] || COLORS[profiles.length % COLORS.length];
      SM.api.createProfile({ name: name, kids: kids, color: color }).then(function (p) {
        ui.toast('Added ' + p.name + (p.kids ? ' (kids)' : ''));
        load(p.id);
      }, function (err) { ui.toast('Could not add profile: ' + err.message); });
    }

    function update(p, changes) {
      SM.api.updateProfile(p.id, changes).then(function (updated) {
        if (updated.id === S.get('profileId')) SM.app.selectProfile(updated);
        load(p.id);
      }, function (err) { ui.toast(err.message); });
    }

    function manage(p) {
      ui.menu(p.name, [
        { label: 'Rename', action: function () {
          ui.prompt('Rename ' + p.name, p.name, { capitalize: true }).then(function (name) { if (name) update(p, { name: name }); });
        } },
        { label: p.kids ? 'Turn kids mode off' : 'Turn kids mode on',
          sub: p.kids ? 'Show the whole library' : 'Only titles rated G, PG, TV-Y, TV-Y7, TV-G or TV-PG',
          action: function () { update(p, { kids: !p.kids }); } },
        { label: 'Colour', action: function () {
          ui.menu('Colour', COLORS.map(function (c, i) {
            return { label: COLOR_NAMES[i], selected: c === p.color, action: function () { update(p, { color: c }); } };
          }), { side: true });
        } },
        { label: 'Delete profile', sub: 'Removes its watch history and hidden titles', disabled: profiles.length <= 1,
          action: function () {
            ui.confirm('Delete ' + p.name + '?', 'Its watch history and hidden titles are removed. Movies stay on the server.', 'Delete')
              .then(function (ok) {
                if (!ok) return;
                SM.api.deleteProfile(p.id).then(function () {
                  if (p.id === S.get('profileId')) { S.set('profileId', ''); S.set('profileName', ''); SM.events.emit('profile'); }
                  load();
                }, function (err) { ui.toast(err.message); });
              });
          } },
      ], { side: true });
    }

    view.onKey = function (action) {
      if (action === 'back' && managing) { toggleManage(); return true; }
      if (action === 'back' && S.get('profileId') && SM.router.depth() === 1) { SM.app.goHome(); return true; }
      return false;
    };
    view.refresh = function () { load(); };
    load();
    return view;
  });
})();
