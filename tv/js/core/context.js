/* Long-press OK (or the blue button) on a title: play / watched / hide menu. */
(function () {
  'use strict';

  var ui = SM.ui, S = SM.settings;

  /** The title the user is pointing at: a card, the centre cover of a Cover Flow, or the view's own item. */
  function itemFromFocus() {
    var f = SM.focus.get();
    if (f) {
      if (f._item) return f._item;
      var flow = f.closest && f.closest('.coverflow');
      if (flow && flow._flow && !flow._flow.isFlipped()) return flow._flow.current();
      var card = f.closest && f.closest('.card');
      if (card && card._item) return card._item;
    }
    var top = SM.router.top();
    return top && top.contextItem ? top.contextItem() : null;
  }

  function refreshAll() {
    SM.router.markStale();
    var top = SM.router.top();
    if (top && top.refresh) top.refresh();
  }

  function profileName() { return S.get('profileName') || 'this profile'; }

  function hide(item) {
    SM.api.hide(item.id).then(function () {
      ui.toast('Hidden from ' + profileName() + ' — undo in Settings → Hidden titles', 4500);
      // A hidden collection / show page has nothing left to show
      var top = SM.router.top();
      if (top && top.ownerId === item.id) SM.router.pop();
      refreshAll();
    }, function (err) { ui.toast('Could not hide: ' + err.message); });
  }

  function unhide(item) {
    SM.api.unhide(item.id).then(function () {
      ui.toast(item.title + ' is visible again');
      refreshAll();
    }, function (err) { ui.toast('Could not unhide: ' + err.message); });
  }

  function setWatched(item, watched) {
    var req = item.kind === 'show' ? SM.api.post('/api/v1/shows/' + item.id + '/watched', { watched: watched })
      : SM.api.watched(item.id, watched);
    req.then(function () { refreshAll(); }, function (err) { ui.toast(err.message); });
  }

  function open(item) {
    var opts = { hidden: false };
    show(item, opts);
  }

  function show(item, opts) {
    opts = opts || {};
    var isVideo = item.kind === 'movie' || item.kind === 'episode';
    var resumable = isVideo && !!SM.util.resumeAt(item);
    var options = [];
    if (opts.hidden) {
      options.push({ label: 'Unhide', sub: 'Show it again for ' + profileName(), action: function () { unhide(item); } });
    }
    if (isVideo) {
      options.push({ label: resumable ? 'Resume from ' + SM.util.clock(item.position) : 'Play',
                     action: function () { SM.player.play(item, { resume: resumable }); } });
      if (resumable) options.push({ label: 'Play from the beginning', action: function () { SM.player.play(item, { resume: false }); } });
      options.push({ label: item.watched ? 'Mark as unwatched' : 'Mark as watched',
                     action: function () { setWatched(item, !item.watched); } });
      options.push({ label: 'Details', action: function () { SM.router.push('detail', { id: item.id }); } });
      options.push({ label: 'Bookmarks…', sub: 'Play from a saved moment', action: function () { bookmarksMenu(item); } });
      if (item.collection_id) {
        options.push({ label: 'Open collection', action: function () { SM.openItem({ kind: 'collection', id: item.collection_id }); } });
      }
      if (item.kind === 'episode') {
        options.push({ label: 'Go to show', action: function () { SM.router.push('show', { id: item.show_id }); } });
      }
    } else if (item.kind === 'show') {
      options.push({ label: 'Play next episode', action: function () { SM.quickPlay(item); } });
      options.push({ label: 'Episodes', action: function () { SM.openItem(item); } });
      options.push({ label: item.unwatched === 0 ? 'Mark all as unwatched' : 'Mark all as watched',
                     action: function () { setWatched(item, item.unwatched !== 0); } });
    } else if (item.kind === 'collection') {
      options.push({ label: 'Open collection', action: function () { SM.openItem(item); } });
      options.push({ label: 'Play', sub: 'The first unwatched movie', action: function () { SM.quickPlay(item); } });
    }
    if (!opts.hidden) {
      var what = { show: 'show', collection: 'collection', episode: 'episode' }[item.kind] || 'movie';
      options.push({ label: 'Hide this ' + what, sub: 'From ' + profileName() + ' only — undo in Settings → Hidden titles',
                     action: function () { hide(item); } });
    }
    var title = item.kind === 'episode' && item.show_title ? item.show_title + ' · ' + item.title : item.title;
    ui.menu(title, options, { side: true });
  }

  /** Bookmarks of a title: pick one to play from there. */
  function bookmarksMenu(item) {
    SM.api.bookmarks(item.id).then(function (r) {
      if (!r.bookmarks.length) {
        ui.toast('No bookmarks yet — while watching, press the blue button to bookmark a moment', 4500);
        return;
      }
      ui.menu('Bookmarks · ' + item.title, r.bookmarks.map(function (b) {
        return { label: SM.util.clock(b.position) + (b.label ? '  ·  ' + b.label : ''),
                 action: function () { SM.player.play(item, { startAt: b.position }); } };
      }), { side: true });
    }, function (err) { ui.toast(err.message); });
  }

  SM.context = {
    bookmarksMenu: bookmarksMenu, open: open, show: show, itemFromFocus: itemFromFocus };
})();
