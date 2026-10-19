/* Music: albums in Cover Flow, artists, Spotify playlists, album and artist pages, and the
 * full-screen Now Playing with the visualizer. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  function asCover(a) {
    return { id: a.id, kind: 'album', title: a.title, artist: a.artist, poster: a.art, year: a.year,
             duration: a.duration, album: a };
  }

  function clock(s) { return SM.util.clock(Math.max(0, s || 0)); }

  /** Play a list of tracks here, or (onOther) on another screen. */
  function playTracks(tracks, start, opts) {
    SM.music.play(tracks, start, opts);
    SM.router.push('nowplaying', {});
  }

  function playOnOther(tracks, start) {
    SM.remote.pickPlayer('Play on', function (p) {
      SM.api.post('/api/v1/remote/players/' + encodeURIComponent(p.id) + '/command',
        { action: 'play_music', tracks: tracks.map(function (t) { return t.id; }), index: start || 0,
          profile_id: SM.settings.get('profileId') })
        .then(function () { ui.toast('Playing on ' + p.name); },
              function (err) { ui.toast((err && err.message) || 'That screen did not answer'); });
    });
  }

  function playAlbum(albumId, opts) {
    SM.api.music.album(albumId).then(function (a) { playTracks(a.tracks, opts && opts.shuffle ? undefined : 0, opts); });
  }

  /** A square card (album, playlist, artist). */
  function squareCard(title, sub, art, onClick, round) {
    var card = el('div.card.square.f' + (round ? '.round' : ''), { onclick: onClick }, [
      el('div.frame', [ui.image(art, 320, title, 'poster')]),
      el('div.caption', [el('div.title', { text: title }), sub ? el('div.sub', { text: sub }) : null]),
    ]);
    return card;
  }

  // ── Spotify: pick a device it should play on ──

  function spotifyDevice(cb) {
    SM.api.spotify.devices().then(function (r) {
      var list = r.devices || [];
      if (!list.length) { ui.toast('Open Spotify on a TV, phone or speaker first: it shows up here then', 5000); return; }
      var remembered = SM.settings.get('spotifyDevice');
      ui.menu('Play on Spotify device', list.map(function (d) {
        return { label: d.name, sub: (d.type || '') + (d.active ? ' · playing' : ''), selected: d.id === remembered,
                 action: function () { SM.settings.set('spotifyDevice', d.id); cb(d); } };
      }), { side: true });
    }, function (err) { ui.toast((err && err.message) || 'Spotify is not connected'); });
  }

  // ── the section ──

  SM.router.register('music', function () {
    var backdrop = SM.Backdrop();
    var tabs = el('div.shelf-tabs', { 'data-group': '' });
    var stage = el('div.home-flow');
    var nowBtn = ui.button('Now Playing', 'wave', function () { SM.router.push('nowplaying', {}); }, 'chip now-btn');
    var body = el('div.home-main', [el('div.home-head', [tabs, nowBtn]), stage]);
    var root = el('div.home.flow-home.music-home', [backdrop, body]);
    var view = { el: root, section: 'music' };
    var shelves = [], active = 0, tabTimer = null;
    var off = SM.music.on(function () { nowBtn.classList.toggle('hidden', !SM.music.active()); });
    nowBtn.classList.toggle('hidden', !SM.music.active());

    function flowOf(albums) {
      var flow = SM.CoverFlow(albums.map(asCover), {
        square: true,
        onChange: function (it) { backdrop.set({ poster: it.poster, blur: true }); },
        onEnter: function (it) { SM.router.push('album', { id: it.id }); },
        onOpen: function (it) { SM.router.push('album', { id: it.id }); },
        onPlay: function (it) { playAlbum(it.id); },
      });
      return flow;
    }

    function grid(nodes) {
      var g = el('div.grid.square-grid', { 'data-group': '' }, nodes);
      return el('div.grid-scroll.music-grid', { 'data-scroll': 'y-near', 'data-pad': '80' }, [g]);
    }

    function show(i, focusIt) {
      if (!shelves[i]) return;
      active = i;
      SM.settings.set('musicShelf', shelves[i].id);
      Array.prototype.forEach.call(tabs.children, function (t, j) { t.classList.toggle('active', j === i); });
      SM.util.clear(stage).appendChild(ui.spinner());
      Promise.resolve(shelves[i].load()).then(function (node) {
        if (active !== i) return;
        SM.util.clear(stage).appendChild(node.el || node);
        if (focusIt) SM.focus.focusFirst(stage);
      }, function (err) { SM.util.clear(stage).appendChild(ui.errorBox(err, function () { show(i, true); })); });
    }

    function render(home, spotifyOn) {
      shelves = (home.shelves || []).map(function (sh) {
        return { id: sh.id, title: sh.title, load: function () { return flowOf(sh.items); } };
      });
      shelves.push({ id: 'albums', title: 'Albums', load: function () {
        return SM.api.music.albums('artist').then(function (r) { return flowOf(r.albums); });
      } });
      shelves.push({ id: 'artists', title: 'Artists', load: function () {
        return SM.api.music.artists().then(function (r) {
          return grid(r.artists.map(function (a) {
            return squareCard(a.name, SM.util.plural(a.album_count, 'album'), a.art,
              function () { SM.router.push('artist', { id: a.id, name: a.name }); }, true);
          }));
        });
      } });
      if (spotifyOn) shelves.push({ id: 'spotify', title: 'Spotify', load: function () {
        return SM.api.spotify.playlists().then(function (r) {
          if (!r.playlists.length) return el('div.empty', [el('h2', { text: 'No playlists' })]);
          return grid(r.playlists.map(function (p) {
            return squareCard(p.title, (p.tracks || 0) + ' songs' + (p.owner ? ' · ' + p.owner : ''), p.image,
              function () { SM.router.push('splaylist', { id: p.id }); });
          }));
        });
      } });
      SM.util.clear(tabs);
      if (!home.stats || !home.stats.albums) {
        if (!spotifyOn) {
          SM.util.clear(stage).appendChild(el('div.empty', [el('h2', { text: 'No music yet' }),
            el('p', { text: 'Put music in a media folder (or set a folder to Music in the server admin page) and scan.' })]));
          return;
        }
        shelves = shelves.filter(function (s) { return s.id === 'spotify'; });
      }
      shelves.forEach(function (sh, i) {
        var tab = el('div.tab.f', { text: sh.title, onclick: function () { show(i, true); } });
        tab.addEventListener('focus:sk', function () {
          clearTimeout(tabTimer);
          tabTimer = setTimeout(function () { if (SM.focus.get() === tab && active !== i) show(i, false); }, 300);
        });
        tabs.appendChild(tab);
      });
      var remembered = 0;
      shelves.forEach(function (sh, i) { if (sh.id === SM.settings.get('musicShelf')) remembered = i; });
      show(remembered, true);
    }

    function load() {
      SM.util.clear(stage).appendChild(ui.spinner());
      var spot = SM.api.spotify.status().then(function (s) { return s.connected; }, function () { return false; });
      Promise.all([SM.api.music.home(), spot]).then(function (r) { render(r[0], r[1]); },
        function (err) { SM.util.clear(stage).appendChild(ui.errorBox(err, load)); SM.focus.focusFirst(stage); });
    }

    view.destroy = off;
    load();
    return view;
  });

  // ── an album ──

  function trackRows(tracks, onPick, showArtist) {
    var list = el('div.tracks', { 'data-group': '', 'data-scroll': 'y-near', 'data-pad': '120' });
    var rows = tracks.map(function (t, i) {
      var row = el('div.track.f', { onclick: function () { onPick(i); } }, [
        el('span.track-no', { text: t.track ? String(t.track) : String(i + 1) }),
        el('span.track-title', [el('b', { text: t.title }), showArtist && t.artist ? el('small', { text: t.artist }) : null]),
        el('span.track-time', { text: t.duration ? clock(t.duration) : '' }),
      ]);
      row._track = t;
      return row;
    });
    rows.forEach(function (r) { list.appendChild(r); });
    function mark() {
      var cur = SM.music.current();
      rows.forEach(function (r) { r.classList.toggle('playing', !!cur && r._track.id === cur.id); });
    }
    mark();
    return { el: list, mark: mark };
  }

  SM.router.register('album', function (params) {
    var backdrop = SM.Backdrop();
    var body = el('div.album-page', [ui.spinner()]);
    var root = el('div.album-view', [backdrop, body]);
    var view = { el: root, section: 'music' }, rows = null;
    var off = SM.music.on(function () { if (rows) rows.mark(); });

    SM.api.music.album(params.id).then(function (a) {
      backdrop.set({ poster: a.art, blur: true });
      rows = trackRows(a.tracks, function (i) { playTracks(a.tracks, i); }, a.artist === 'Various Artists');
      var actions = el('div.actions', { 'data-group': '' }, [
        ui.button('Play', 'play', function () { playTracks(a.tracks, 0); }, 'primary autofocus'),
        ui.button('Shuffle', 'shuffle', function () { playTracks(a.tracks, undefined, { shuffle: true }); }),
        SM.serverFeatures.indexOf('remote') !== -1 ? ui.button('Play on…', 'cast', function () { playOnOther(a.tracks, 0); }) : null,
        a.artist_id && a.artist !== 'Various Artists' ? ui.button(a.artist, 'user2', function () {
          SM.router.push('artist', { id: a.artist_id, name: a.artist }); }) : null,
      ]);
      SM.util.clear(body).appendChild(el('div.album-layout', [
        el('div.album-cover', [ui.image(a.art, 640, a.title, 'poster')]),
        el('div.album-info', [
          el('h1.album-title', { text: a.title }),
          el('div.album-artist', { text: a.artist }),
          el('div.album-meta', { text: [a.year, SM.util.plural(a.track_count, 'song'), SM.util.runtime(a.duration), a.genre]
            .filter(Boolean).join('   ·   ') }),
          actions, rows.el,
        ]),
      ]));
      SM.focus.claim(view, actions.querySelector('.autofocus'));
    }, function (err) { SM.util.clear(body).appendChild(ui.errorBox(err)); });

    view.destroy = off;
    return view;
  });

  // ── an artist ──

  SM.router.register('artist', function (params) {
    var backdrop = SM.Backdrop();
    var g = el('div.grid.square-grid', { 'data-group': '' });
    var root = el('div.artist-view', [backdrop, el('div.page-head', [el('h1.page-title', { text: params.name || '' })]),
      el('div.grid-scroll', { 'data-scroll': 'y-near', 'data-pad': '80' }, [g])]);
    var view = { el: root, section: 'music' };
    SM.api.music.artist(params.id).then(function (a) {
      backdrop.set({ poster: a.art, blur: true });
      a.albums.forEach(function (al) {
        g.appendChild(squareCard(al.title, [al.year, SM.util.plural(al.track_count, 'song')].filter(Boolean).join(' · '),
          al.art, function () { SM.router.push('album', { id: al.id }); }));
      });
      SM.focus.claim(view, g.firstChild);
    }, function (err) { g.appendChild(ui.errorBox(err)); });
    return view;
  });

  // ── a Spotify playlist ──

  SM.router.register('splaylist', function (params) {
    var backdrop = SM.Backdrop();
    var body = el('div.album-page', [ui.spinner()]);
    var root = el('div.album-view', [backdrop, body]);
    var view = { el: root, section: 'music' };

    function start(p, offset) {
      spotifyDevice(function (d) {
        SM.api.spotify.play({ device_id: d.id, context_uri: p.uri, offset: offset || 0 })
          .then(function () { ui.toast('Playing on ' + d.name); },
                function (err) { ui.toast((err && err.message) || 'Spotify did not start'); });
      });
    }

    SM.api.spotify.playlist(params.id).then(function (p) {
      backdrop.set({ poster: p.image, blur: true });
      var rows = trackRows(p.tracks, function (i) { start(p, i); }, true);
      // hold OK on a song: a radio of it
      Array.prototype.forEach.call(rows.el.children, function (r) {
        r._hold = function () {
          spotifyDevice(function (d) {
            SM.api.spotify.radio({ device_id: d.id, seed: r._track.uri })
              .then(function () { ui.toast('Radio from ' + r._track.title + ' on ' + d.name); },
                    function (err) { ui.toast((err && err.message) || 'No radio for that one'); });
          });
        };
      });
      var actions = el('div.actions', { 'data-group': '' }, [
        ui.button('Play on Spotify…', 'spotify', function () { start(p, 0); }, 'primary autofocus'),
      ]);
      SM.util.clear(body).appendChild(el('div.album-layout', [
        el('div.album-cover', [ui.image(p.image, 640, p.title, 'poster')]),
        el('div.album-info', [
          el('h1.album-title', { text: p.title }),
          el('div.album-artist', { text: p.owner ? 'by ' + p.owner : 'Spotify' }),
          el('div.album-meta', { text: SM.util.plural(p.tracks.length, 'song') + '   ·   hold OK on a song for a radio' }),
          actions, rows.el,
        ]),
      ]));
      SM.focus.claim(view, actions.firstChild);
    }, function (err) { SM.util.clear(body).appendChild(ui.errorBox(err)); });
    return view;
  });

  // ── now playing ──

  SM.router.register('nowplaying', function () {
    var canvas = el('canvas.viz');
    var viz = SM.Visualizer(canvas);
    var art = el('div.np-art'), title = el('div.np-title'), artist = el('div.np-artist'), album = el('div.np-album');
    var fill = el('i'), now = el('span'), total = el('span'), modeName = el('div.np-mode');
    var info = el('div.np-info', [art, el('div.np-text', [title, artist, album,
      el('div.np-bar', [fill]), el('div.np-times', [now, total]),
      el('div.np-hint', { text: 'OK  play/pause     ◀ ▶  previous/next     ▲ ▼  visualizer' })])]);
    var root = el('div.nowplaying', [canvas, modeName, info]);
    var view = { el: root, fullscreen: true, section: 'music', viz: viz };
    var hideTimer = null, tick = null;
    viz.setMode(SM.settings.get('vizMode') || 'bars');

    function wake() {
      root.classList.remove('idle');
      clearTimeout(hideTimer);
      hideTimer = setTimeout(function () { root.classList.add('idle'); }, 6000);
    }

    function render() {
      var t = SM.music.current();
      if (!t) { title.textContent = 'Nothing playing'; artist.textContent = ''; album.textContent = ''; return; }
      title.textContent = t.title; artist.textContent = t.artist || ''; album.textContent = t.album || '';
      SM.util.clear(art).appendChild(ui.image(t.art, 400, t.album, 'poster'));
      viz.setArt(t.art ? SM.api.art(t.art, 400) : null);
    }

    function times() {
      var d = SM.music.duration(), c = SM.music.time();
      fill.style.width = d ? (100 * c / d) + '%' : '0';
      now.textContent = clock(c); total.textContent = '-' + clock(d - c);
      root.classList.toggle('paused', !SM.music.playing());
    }

    var off = SM.music.on(function (what) { if (what === 'track') render(); times(); });

    view.onKey = function (action) {
      wake();
      switch (action) {
        case 'enter': SM.music.toggle(); return true;
        case 'left': SM.music.previous(); return true;
        case 'right': SM.music.next(); return true;
        case 'up': case 'down':
          modeName.textContent = viz.next(action === 'up' ? -1 : 1);
          SM.settings.set('vizMode', viz.mode());
          modeName.classList.add('show');
          setTimeout(function () { modeName.classList.remove('show'); }, 1600);
          return true;
      }
      return SM.music.key(action);
    };
    view.onShow = function () { render(); times(); viz.start(); wake(); tick = setInterval(times, 500); };
    view.onHide = function () { viz.stop(); clearInterval(tick); };
    view.destroy = function () { viz.stop(); clearInterval(tick); off(); };
    return view;
  });

  // ── the pill in the corner while music plays elsewhere ──

  SM.musicPill = function () {
    var art = el('div.pill-art'), text = el('div.pill-text');
    var pill = el('div.music-pill.hidden', [art, text, ui.icon('wave', 'pill-eq')]);
    function update() {
      var t = SM.music.current(), top = SM.router.top();
      var hide = !t || (top && (top.name === 'nowplaying' || top.name === 'player'));
      pill.classList.toggle('hidden', !!hide);
      pill.classList.toggle('paused', !SM.music.playing());
      if (!t) return;
      if (pill._id !== t.id) {
        pill._id = t.id;
        SM.util.clear(art).appendChild(ui.image(t.art, 160, t.album, 'poster'));
        text.textContent = t.title + (t.artist ? ' — ' + t.artist : '');
      }
    }
    SM.music.on(update);
    SM.events.on('view', update);
    return pill;
  };
})();
