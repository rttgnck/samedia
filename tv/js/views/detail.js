/* Movie / episode detail page. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;

  function techLine(item) {
    var v = item.media && item.media.video;
    if (!v) return '';
    var parts = [];
    if (v.width) parts.push(v.width + '×' + v.height);
    if (v.codec) parts.push(v.codec.toUpperCase());
    if (v.hdr) parts.push(v.hdr.indexOf('dv') === 0 ? 'Dolby Vision ' + v.hdr.slice(2) : v.hdr.toUpperCase());
    if (item.media.container) parts.push(item.media.container.toUpperCase());
    if (item.media.bitrate) parts.push(Math.round(item.media.bitrate / 1e6) + ' Mb/s');
    return parts.join(' · ');
  }

  SM.router.register('detail', function (params) {
    var backdrop = SM.Backdrop();
    var body = el('div.detail-body', [ui.spinner()]);
    var root = el('div.detail', [backdrop, body]);
    var view = { el: root };
    var item = null;
    var choice = { audio: null, subtitle: undefined }; // undefined = automatic

    function play(resume) {
      SM.player.play(item, { resume: resume, audioIndex: choice.audio, subtitleId: choice.subtitle });
    }

    function chooseAudio() {
      var opts = item.audio_tracks.map(function (t) {
        return {
          label: t.label, sub: t.supported ? null : 'Converted to Dolby Digital+ for this TV',
          selected: choice.audio === null ? t.default : t.index === choice.audio,
          action: function () { choice.audio = t.index; render(); },
        };
      });
      ui.menu('Audio', opts, { side: true });
    }

    function chooseSubs() {
      var opts = [{ label: 'Automatic', sub: 'Based on your subtitle settings', selected: choice.subtitle === undefined,
                    action: function () { choice.subtitle = undefined; render(); } },
                  { label: 'Off', selected: choice.subtitle === null, action: function () { choice.subtitle = null; render(); } }];
      item.subtitle_tracks.forEach(function (t) {
        opts.push({ label: t.label, sub: t.supported ? (t.format === 'pgs' ? 'Image (Blu-ray)' : null) : 'Not supported',
                    disabled: !t.supported, selected: choice.subtitle === t.id,
                    action: function () { choice.subtitle = t.id; render(); } });
      });
      ui.menu('Subtitles', opts, { side: true });
    }

    function audioLabel() {
      if (!item.audio_tracks.length) return 'None';
      var t = item.audio_tracks.filter(function (a) { return choice.audio === null ? a.default : a.index === choice.audio; })[0] ||
              item.audio_tracks[0];
      return t.label.split(' — ')[0];
    }

    function subsLabel() {
      if (choice.subtitle === undefined) return 'Auto';
      if (choice.subtitle === null) return 'Off';
      var t = item.subtitle_tracks.filter(function (s) { return s.id === choice.subtitle; })[0];
      return t ? t.label : 'Auto';
    }

    function toggleWatched() {
      SM.api.watched(item.id, !item.watched).then(function () {
        item.watched = !item.watched;
        item.position = 0;
        SM.router.markStale();
        render();
      });
    }

    function credits(it) {
      var cast = (it.cast || []).slice(0, 6).map(function (c) { return c.name; });
      if (!it.director && !cast.length) return null;
      return el('div.detail-credits', [
        it.director ? el('div', [el('span.k', { text: 'Director' }), el('span', { text: it.director })]) : null,
        cast.length ? el('div', [el('span.k', { text: 'Starring' }), el('span', { text: cast.join(', ') })]) : null,
      ]);
    }

    function render() {
      var focusedLabel = SM.focus.get() && SM.focus.get().dataset ? SM.focus.get().dataset.k : null;
      var isEp = item.kind === 'episode';
      var resumable = !!SM.util.resumeAt(item);
      var buttons = [];
      var playBtn = resumable
        ? ui.button('Resume ' + SM.util.clock(item.position), 'play', function () { play(true); }, 'primary autofocus')
        : ui.button('Play', 'play', function () { play(false); }, 'primary autofocus');
      playBtn.dataset.k = 'play';
      buttons.push(playBtn);
      if (resumable) {
        var restart = ui.button('From start', 'restart', function () { play(false); });
        restart.dataset.k = 'restart';
        buttons.push(restart);
      }
      if ((SM.serverFeatures || []).indexOf('remote') !== -1) {
        var castBtn = ui.button('Play on…', 'cast', function () { SM.remote.playOn(item, SM.util.resumeAt(item)); });
        castBtn.dataset.k = 'cast';
        buttons.push(castBtn);
      }
      var aBtn = ui.button(audioLabel(), 'audio', chooseAudio);
      aBtn.dataset.k = 'audio';
      var sBtn = ui.button(subsLabel(), 'subs', chooseSubs);
      sBtn.dataset.k = 'subs';
      var wBtn = ui.button(item.watched ? 'Watched' : 'Mark watched', 'check', toggleWatched, item.watched ? 'active' : '');
      wBtn.dataset.k = 'watched';
      buttons.push(aBtn, sBtn, wBtn);
      if (isEp) {
        var showBtn = ui.button('Go to show', 'tv', function () { SM.router.push('show', { id: item.show_id }); });
        showBtn.dataset.k = 'show';
        buttons.push(showBtn);
      }
      // Same menu as holding OK: hide, collection, watched...
      if (item.bookmarks && item.bookmarks.length) {
        var marksBtn = ui.button(SM.util.plural(item.bookmarks.length, 'Bookmark'), 'bookmarks', function () {
          SM.context.bookmarksMenu(item);
        });
        marksBtn.dataset.k = 'bookmarks';
        buttons.push(marksBtn);
      }
      var moreBtn = ui.button('More', 'info', function () { SM.context.open(item); });
      moreBtn.dataset.k = 'more';
      buttons.push(moreBtn);

      var meta = [];
      if (isEp) meta.push(SM.util.episodeCode(item));
      if (item.year && !isEp) meta.push(String(item.year));
      if (item.certification) meta.push(item.certification);
      if (item.duration) meta.push(SM.util.runtime(item.duration));
      if (item.rating) meta.push('★ ' + item.rating);
      if (item.genres && item.genres.length) meta.push(item.genres.join(', '));
      if (item.duration) meta.push(SM.util.endsAt(item.duration - (resumable ? item.position : 0)));

      SM.util.clear(body);
      body.appendChild(el('div.detail-info', [
        isEp ? el('div.eyebrow', { text: item.show_title }) : null,
        el('h1.detail-title', { text: item.title }),
        item.tagline ? el('div.detail-tagline', { text: item.tagline }) : null,
        el('div.detail-meta', [el('span', { text: meta.join('   ·   ') }), ui.badges(item.badges)]),
        item.plot ? el('p.detail-plot' + (item.cast && item.cast.length ? '.short' : ''), { text: item.plot }) : null,
        credits(item),
        el('div.actions', { 'data-group': '' }, buttons),
        el('div.tech', { text: techLine(item) }),
        el('div.tech.file', { text: item.file }),
      ]));
      if (isEp && item.next) {
        var nextCard = ui.landscapeCard(item.next);
        nextCard.addEventListener('click', function () { SM.router.push('detail', { id: item.next.id }); });
        body.appendChild(el('section.row.landscape.detail-next', { 'data-group': '' }, [el('h2', { text: 'Next episode' }),
          el('div.row-track', [nextCard])]));
      }
      backdrop.set(item.thumb && isEp && !item.backdrop ? item.thumb : item.backdrop);
      var again = focusedLabel && body.querySelector('[data-k="' + focusedLabel + '"]');
      SM.focus.claim(view, again || playBtn);
    }

    function load() {
      return SM.api.item(params.id).then(function (data) {
        item = data;
        render();
      }, function (err) {
        SM.util.clear(body).appendChild(ui.errorBox(err, load));
        SM.focus.focusFirst(body);
      });
    }

    view.refresh = load;
    view.contextItem = function () { return item; };
    view.onKey = function (action) {
      if ((action === 'play' || action === 'playpause') && item) {
        play(item.position > 30);
        return true;
      }
      return false;
    };
    load();
    return view;
  });
})();
