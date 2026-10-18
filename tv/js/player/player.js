/* Full-screen player view: OSD, scrubbing, audio/subtitle menus, resume, next episode.
 *
 * Timeline: the server either serves the file directly (seekable; decoder time == media time)
 * or an on-the-fly remux starting at `start_offset` (not seekable; media time == offset +
 * decoder time). Seeking a remux re-requests the stream from the new position.
 */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui, S = SM.settings;
  var PROGRESS_EVERY = 10; // seconds between progress reports
  // Scrubbing speeds up while you keep pressing: seconds per press
  var SCRUB_STEPS = [10, 10, 30, 30, 60, 60, 120, 120, 300];
  var PICTURE = [['fit', 'Fit', 'Whole picture, black bars if needed'], ['fill', 'Fill', 'Fill the screen, crops the edges'],
                 ['stretch', 'Stretch', 'Fill the screen, distorts the picture']];

  function play(item, opts) {
    if (item.kind === 'episode' && item.next === undefined) {
      // Row cards are summaries; the player needs the full item to know the next episode.
      SM.api.item(item.id).then(function (full) { play(full, opts); }, function () {
        item.next = null;
        play(item, opts);
      });
      return;
    }
    SM.router.push('player', { item: item, opts: opts || {} });
  }

  function langMatches(trackLang, pref) {
    if (!trackLang || !pref) return false;
    return trackLang.toLowerCase().slice(0, 2) === pref.toLowerCase().slice(0, 2);
  }

  /** Choose the subtitle track to start with, following the user's subtitle settings. */
  function autoSubtitle(tracks, audioTrack) {
    var mode = S.get('subtitleMode'), lang = S.get('subtitleLanguage');
    var usable = tracks.filter(function (t) { return t.supported && (!lang || langMatches(t.language, lang) || !t.language); });
    var forced = usable.filter(function (t) { return t.forced; })[0];
    var full = usable.filter(function (t) { return !t.forced; });
    // Prefer text over bitmaps (crisper, cheaper), external files over embedded.
    full.sort(function (a, b) { return (a.format === 'pgs') - (b.format === 'pgs'); });
    if (mode === 'off') return null;
    if (mode === 'forced') return forced || null;
    if (mode === 'always') return full[0] || forced || null;
    // auto: full subtitles when the audio is in another language, forced otherwise
    if (audioTrack && audioTrack.language && !langMatches(audioTrack.language, lang)) return full[0] || forced || null;
    return forced || null;
  }

  SM.router.register('player', function (params) {
    var item = params.item, opts = params.opts;
    var session = SM.util.uid();
    var decision = null, backend = null, offset = 0, duration = item.duration || 0;
    var playing = false, buffering = false, ended = false, destroyed = false, retried = false;
    var subTrack = null, subRenderer = null;
    var lastProgressAt = 0, lastReported = -1;
    var scrubTarget = null, scrubTimer = null, osdTimer = null, tickTimer = null, nextTimer = null;
    var lastTime = 0, lastTimeAt = 0;

    // ── DOM ──
    var mount = el('div.av-mount');
    var subText = el('div.subs-text.size-' + S.get('subtitleSize') + (S.get('subtitleBackground') ? '.boxed' : ''));
    var subCanvas = el('canvas.subs-canvas', { width: 1920, height: 1080 });
    var spinner = el('div.player-spinner', [el('div.spinner')]);
    var titleEl = el('div.osd-title');
    var subtitleEl = el('div.osd-sub');
    var timeEl = el('span.osd-time'), remainEl = el('span.osd-remain'), endsEl = el('span.osd-ends');
    var fill = el('i.fill'), scrubMark = el('i.scrub'), ticks = el('div.osd-ticks');
    var bubbleImg = el('img.osd-bubble-img', { alt: '' });
    var bubbleTime = el('span');
    var bubble = el('div.osd-bubble', [bubbleImg, bubbleTime]);
    var hasFrames = (SM.serverFeatures || []).indexOf('frames') !== -1;
    var frameTimer = null, frameFor = null;
    bubbleImg.onload = function () { bubble.classList.add('has-frame'); };
    bubbleImg.onerror = function () { bubble.classList.remove('has-frame'); };
    var bar = el('div.osd-bar.f', [fill, ticks, scrubMark, bubble]);
    var clockEl = el('div.osd-clock');
    var playBtn = ui.button(null, 'pause', togglePlay, 'round autofocus');
    var audioBtn = ui.button('Audio', 'audio', chooseAudio);
    var subsBtn = ui.button('Subtitles', 'subs', chooseSubs);
    var markBtn = ui.button('Bookmark', 'bookmark', addBookmark);
    var marksBtn = ui.button('Bookmarks', 'bookmarks', chooseBookmark);
    var pictureBtn = ui.button('Fit', 'aspect', choosePicture);
    var episodesBtn = ui.button('Episodes', 'list', chooseEpisode);
    var infoBtn = ui.button(null, 'info', toggleInfo, 'round');
    var nextBtn = ui.button('Next episode', 'next', function () { playNext(); });
    var controls = el('div.osd-controls', { 'data-group': '' }, [
      ui.button(null, 'restart', function () { seekTo(0); showOsd(); }, 'round'),
      ui.button(null, 'back10', function () { seekBy(-10); }, 'round'), playBtn,
      ui.button(null, 'fwd30', function () { seekBy(30); }, 'round'),
      audioBtn, subsBtn, markBtn, marksBtn, pictureBtn, episodesBtn, nextBtn, infoBtn,
    ]);
    var osd = el('div.osd', [
      el('div.osd-top', [el('div.osd-top-row', [el('div', [titleEl, subtitleEl]), clockEl])]),
      el('div.osd-bottom', [el('div.osd-bar-wrap', { 'data-group': '' }, [bar]),
        el('div.osd-times', [timeEl, el('span.spacer'), endsEl, remainEl]), controls]),
    ]);
    var infoBox = el('div.playback-info.hidden');
    var upNext = el('div.up-next.hidden');
    var root = el('div.player', [mount, subCanvas, subText, spinner, osd, infoBox, upNext]);
    var view = { el: root, fullscreen: true };

    var isEp = item.kind === 'episode';
    titleEl.textContent = isEp ? (item.show_title || '') : item.title;
    subtitleEl.textContent = isEp ? SM.util.episodeCode(item) + ' · ' + item.title : (item.year || '');
    if (!item.next) nextBtn.classList.add('hidden');
    if (!isEp) episodesBtn.classList.add('hidden');
    var bookmarks = item.bookmarks || [];
    var scrubStreak = 0, lastScrubAt = 0;

    // ── time ──
    function decoderTime() {
      if (!backend) return 0;
      if (!playing) return lastTime;
      // Interpolate between decoder callbacks for smooth subtitles.
      var t = backend.time();
      if (t !== lastTime) { lastTime = t; lastTimeAt = Date.now(); return t; }
      return lastTime + Math.min(1, (Date.now() - lastTimeAt) / 1000);
    }
    function now() { return offset + decoderTime(); }

    // ── start / restart ──
    function start(startSec, audioIndex, force) {
      ended = false;
      setBuffering(true);
      // On TVs that can't seek in a file, starting mid-way means letting the server start there
      if (!force && startSec > 1 && S.get('avSeekBroken')) force = 'remux';
      var body = {
        capabilities: S.capabilities(), start: startSec, session: session,
        audio_index: audioIndex === undefined ? null : audioIndex,
        prefer_audio_lang: S.get('audioLanguage'), force: force || null,
      };
      return SM.api.playback(item.id, body).then(function (d) {
        if (destroyed) return;
        var first = !decision;
        decision = d;
        SM.devlog.log('player.decision', { mode: d.mode, seekable: d.seekable, offset: d.start_offset, reasons: d.reasons,
                                          video: d.video, startSec: startSec });
        duration = d.duration || duration;
        renderTicks();
        if (first) {
          (d.warnings || []).forEach(function (w) { ui.toast(w, 5000); });
          initSubtitles();
        }
        offset = d.start_offset || 0;
        lastTime = 0;
        var url = SM.api.abs(d.url);
        var uhd = d.video && d.video.width > 1920;
        return backend.open(url, { uhd: uhd, bufferSec: d.seekable ? 0 : 6, displayMode: S.get('pictureMode') }).then(function () {
          if (destroyed) return;
          var after = Promise.resolve();
          if (d.seekable && startSec > 1) {
            after = backend.seek(startSec).catch(function (e) {
              // Remember for next time and restart from the right place on the server
              S.set('avSeekBroken', true);
              SM.devlog.log('player.resumeFallback', { startSec: startSec });
              return start(startSec, audioIndex, 'remux').then(function () { throw 'restarted'; });
            });
          }
          return after.then(function () {
            if (d.mode === 'direct' && d.audio_ordinal > 0) {
              if (!backend.selectAudio(d.audio_ordinal)) {
                // Native track switching failed; let the server pick the track instead.
                return start(startSec, d.audio_index, 'remux');
              }
            }
            backend.play();
            playing = true;
            lastTimeAt = Date.now();
            updatePlayIcon();
            renderInfo();
          });
        });
      }).catch(function (err) { if (err !== 'restarted') onError(err); });
    }

    function onError(err) {
      if (destroyed) return;
      var pos = Math.max(0, now() - 2);
      if (decision && decision.mode === 'direct' && !retried) {
        // The TV refused the original file: retry with the server converting audio/container.
        retried = true;
        ui.toast('This TV could not play the file directly — converting audio on the server…', 4500);
        start(pos, decision.audio_index, 'remux');
        return;
      }
      setBuffering(false);
      showOsd(true);
      ui.menu('Playback failed', [
        { label: err && err.message ? err.message : 'Unknown error', disabled: true },
        { label: 'Try again', action: function () { retried = false; start(pos, decision ? decision.audio_index : undefined); } },
        { label: 'Try with full conversion (slow)', action: function () { start(pos, decision ? decision.audio_index : undefined, 'transcode'); } },
        { label: 'Close player', action: function () { SM.router.pop(); } },
      ]);
    }

    // ── subtitles ──
    function initSubtitles() {
      subRenderer = new SM.subtitles.Renderer(subText, subCanvas);
      var tracks = decision.subtitle_tracks || [];
      var audio = (decision.audio_tracks || []).filter(function (a) { return a.index === decision.audio_index; })[0];
      var chosen;
      if (opts.subtitleId === null) chosen = null;
      else if (opts.subtitleId) chosen = tracks.filter(function (t) { return t.id === opts.subtitleId; })[0] || null;
      else chosen = autoSubtitle(tracks, audio);
      selectSubtitle(chosen, true);
    }

    function selectSubtitle(track, quiet) {
      subTrack = track;
      subRenderer.setTrack(null);
      if (!track) return;
      var waitingShown = false;
      SM.subtitles.load(track, function () {
        if (!waitingShown && !quiet) ui.toast('Preparing subtitles… (large files take a moment)', 4000);
        waitingShown = true;
      }).then(function (data) {
        if (subTrack === track && !destroyed) subRenderer.setTrack(data);
      }, function (err) {
        if (subTrack === track) ui.toast('Subtitles unavailable: ' + err.message);
      });
    }

    // ── controls ──
    function togglePlay() {
      if (!backend) return;
      if (ended) { start(0, decision.audio_index); return; }
      if (playing) { backend.pause(); playing = false; reportProgress(true); }
      else { backend.play(); playing = true; lastTimeAt = Date.now(); }
      updatePlayIcon();
      showOsd();
    }

    function updatePlayIcon() {
      var icon = ui.icon(playing ? 'pause' : 'play');
      playBtn.replaceChild(icon, playBtn.firstChild);
    }

    function seekTo(target) {
      SM.devlog.log('player.seekTo', { target: target, now: now(), seekable: decision && decision.seekable, mode: decision && decision.mode });
      target = Math.max(0, Math.min(duration ? duration - 3 : target, target));
      if (!decision) return;
      if (decision.seekable && S.get('avSeekBroken')) {
        start(target, decision.audio_index, 'remux');
      } else if (decision.seekable) {
        setBuffering(true);
        backend.seek(target).then(function () { lastTime = target; lastTimeAt = Date.now(); setBuffering(false); },
          function () {
            // The TV refused to seek in the file: let the server stream from the new position
            S.set('avSeekBroken', true);
            SM.devlog.log('player.seekFallback', { target: target });
            start(target, decision.audio_index, 'remux');
          });
      } else {
        start(target, decision.audio_index, decision.mode === 'transcode' ? 'transcode' : (decision.mode === 'remux' ? 'remux' : null));
      }
      subRenderer && subRenderer.setTrack(subRenderer.track); // force redraw
    }

    /** Accumulate presses, commit after a short pause. */
    function seekBy(delta) {
      if (scrubTarget === null) scrubTarget = now();
      scrubTarget = Math.max(0, Math.min(duration || Infinity, scrubTarget + delta));
      showOsd();
      renderBar();
      clearTimeout(scrubTimer);
      scrubTimer = setTimeout(commitScrub, 900);
    }

    /** Left/right on the time bar: the longer you keep pressing, the bigger the jumps. */
    function scrub(dir) {
      var t = Date.now();
      scrubStreak = t - lastScrubAt < 700 ? scrubStreak + 1 : 0;
      lastScrubAt = t;
      seekBy(dir * SCRUB_STEPS[Math.min(scrubStreak, SCRUB_STEPS.length - 1)]);
    }

    function commitScrub() {
      clearTimeout(scrubTimer);
      if (scrubTarget === null) return;
      var t = scrubTarget;
      scrubTarget = null;
      scrubStreak = 0;
      seekTo(t);
    }

    function cancelScrub() {
      clearTimeout(scrubTimer);
      scrubTarget = null;
      scrubStreak = 0;
      renderBar();
    }

    /** Preview still for the scrub target (the server snaps to 10 s; debounced while pressing). */
    function requestFrame(t) {
      if (!hasFrames) return;
      var snapped = Math.max(0, Math.round(t / 10) * 10);
      if (snapped === frameFor) return;
      clearTimeout(frameTimer);
      frameTimer = setTimeout(function () {
        frameFor = snapped;
        bubbleImg.src = SM.api.abs('/api/v1/items/' + item.id + '/frame?t=' + snapped + '&w=320');
      }, 180);
    }

    // ── bookmarks ──
    function renderTicks() {
      SM.util.clear(ticks);
      if (!duration) return;
      bookmarks.forEach(function (b) {
        ticks.appendChild(el('i', { style: { left: Math.min(100, 100 * b.position / duration) + '%' } }));
      });
      marksBtn.classList.toggle('hidden', !bookmarks.length);
      marksBtn.lastChild.textContent = 'Bookmarks (' + bookmarks.length + ')';
    }

    function bookmarkLabel(b) { return SM.util.clock(b.position) + (b.label ? '  ·  ' + b.label : ''); }

    function addBookmark() {
      var pos = scrubTarget !== null ? scrubTarget : now();
      SM.api.addBookmark(item.id, pos).then(function (r) {
        bookmarks = r.bookmarks;
        renderTicks();
        ui.toast('Bookmarked ' + SM.util.clock(r.bookmark.position) + ' — find it under Bookmarks', 3500);
      }, function (err) { ui.toast('Could not bookmark: ' + err.message); });
    }

    function chooseBookmark() {
      if (!bookmarks.length) { ui.toast('No bookmarks yet — press the blue button (or Bookmark) to add one'); return; }
      var opts = bookmarks.map(function (b) {
        return { label: bookmarkLabel(b), action: function () { cancelScrub(); seekTo(b.position); showOsd(); } };
      });
      opts.push({ label: 'Name a bookmark…', action: function () { pickBookmark('Name which bookmark?', renameBookmark); } });
      opts.push({ label: 'Delete a bookmark…', action: function () { pickBookmark('Delete which bookmark?', deleteBookmark); } });
      ui.menu('Bookmarks', opts, { side: true });
    }

    function pickBookmark(title, fn) {
      ui.menu(title, bookmarks.map(function (b) { return { label: bookmarkLabel(b), action: function () { fn(b); } }; }), { side: true });
    }

    function renameBookmark(b) {
      ui.prompt('Name for ' + SM.util.clock(b.position), b.label || '', { capitalize: true, max: 60 }).then(function (label) {
        if (label === null) return;
        SM.api.renameBookmark(b.id, label).then(function (u) { b.label = u.label; }, function (err) { ui.toast(err.message); });
      });
    }

    function deleteBookmark(b) {
      SM.api.deleteBookmark(b.id).then(function () {
        bookmarks = bookmarks.filter(function (x) { return x.id !== b.id; });
        renderTicks();
        ui.toast('Bookmark removed');
      }, function (err) { ui.toast(err.message); });
    }

    // ── picture / episodes ──
    function pictureLabel() {
      var m = PICTURE.filter(function (p) { return p[0] === (S.get('pictureMode') || 'fit'); })[0] || PICTURE[0];
      return m[1];
    }

    function choosePicture() {
      ui.menu('Picture', PICTURE.map(function (p) {
        return { label: p[1], sub: p[2], selected: p[0] === (S.get('pictureMode') || 'fit'), action: function () {
          S.set('pictureMode', p[0]);
          if (backend) backend.setDisplayMode(p[0]);
          pictureBtn.lastChild.textContent = p[1];
        } };
      }), { side: true });
    }

    function chooseEpisode() {
      SM.api.show(item.show_id).then(function (show) {
        var eps = show.episodes.filter(function (e) { return e.season === item.season; });
        ui.menu(show.title + ' · Season ' + item.season, eps.map(function (e) {
          return { label: SM.util.episodeCode(e) + '  ' + e.title, selected: e.id === item.id,
                   sub: e.watched ? 'Watched' : (SM.util.resumeAt(e) ? 'Resume at ' + SM.util.clock(e.position) : null),
                   action: function () {
                     if (e.id === item.id) return;
                     reportProgress(true);
                     SM.api.item(e.id).then(function (full) { SM.router.pop(); play(full, { resume: true }); });
                   } };
        }), { side: true });
      }, function (err) { ui.toast(err.message); });
    }

    function chooseAudio() {
      var tracks = decision ? decision.audio_tracks : [];
      ui.menu('Audio', tracks.map(function (t) {
        return {
          label: t.label, sub: t.supported ? null : 'Converted to Dolby Digital+ 5.1 by the server',
          selected: t.index === decision.audio_index,
          action: function () {
            if (t.index === decision.audio_index) return;
            var pos = now();
            if (decision.mode === 'direct' && t.supported) {
              var ordinal = tracks.indexOf(t);
              if (backend.selectAudio(ordinal)) {
                decision.audio_index = t.index;
                decision.audio_ordinal = ordinal;
                renderInfo();
                return;
              }
            }
            start(pos, t.index);
          },
        };
      }), { side: true });
    }

    function chooseSubs() {
      var tracks = decision ? decision.subtitle_tracks : [];
      var options = [{ label: 'Off', selected: !subTrack, action: function () { selectSubtitle(null); } }];
      tracks.forEach(function (t) {
        options.push({
          label: t.label, sub: t.supported ? (t.format === 'pgs' ? 'Image subtitles (Blu-ray)' : null) : 'Format not supported',
          disabled: !t.supported, selected: subTrack && subTrack.id === t.id,
          action: function () { selectSubtitle(t); },
        });
      });
      if (subTrack && subTrack.format === 'text') {
        options.push({ label: 'Subtitle timing…', sub: 'Shift subtitles earlier / later', action: chooseDelay });
      }
      ui.menu('Subtitles', options, { side: true });
    }

    function chooseDelay() {
      var current = (subRenderer.track && subRenderer.track.delay) || 0;
      var steps = [-2, -1, -0.5, -0.25, 0, 0.25, 0.5, 1, 2];
      ui.menu('Subtitle timing', steps.map(function (s) {
        var label = s === 0 ? 'In sync' : (s > 0 ? 'Show ' + s + 's earlier' : 'Show ' + (-s) + 's later');
        return { label: label, selected: current === s, action: function () {
          if (subRenderer.track) { subRenderer.track.delay = s; subRenderer.lastKey = null; }
        } };
      }), { side: true });
    }

    function toggleInfo() {
      S.set('showPlaybackInfo', !S.get('showPlaybackInfo'));
      renderInfo();
    }

    function renderInfo() {
      infoBox.classList.toggle('hidden', !S.get('showPlaybackInfo') || !decision);
      if (!decision || !S.get('showPlaybackInfo')) return;
      var v = decision.video || {};
      var audio = (decision.audio_tracks || []).filter(function (a) { return a.index === decision.audio_index; })[0];
      var modeLabel = { direct: 'Direct play', remux: 'Remux (video untouched)', transcode: 'Transcoding video' }[decision.mode];
      SM.util.clear(infoBox).appendChild(el('div', [
        el('div.pi-mode.' + decision.mode, { text: modeLabel }),
        el('div', { text: 'Video  ' + [v.codec, v.width && v.width + '×' + v.height, v.hdr].filter(Boolean).join(' · ') }),
        el('div', { text: 'Audio  ' + (audio ? audio.label : 'none') + (audio && !audio.supported ? '  →  E-AC3' : '') }),
        el('div', { text: 'Subtitles  ' + (subTrack ? subTrack.label : 'off') }),
        decision.reasons && decision.reasons.length ? el('div.pi-reasons', { text: decision.reasons.join('; ') }) : null,
      ]));
    }

    // ── OSD ──
    function showOsd(sticky) {
      root.classList.add('osd-visible');
      if (!osd.contains(SM.focus.get()) && !SM.focus.hasLayer()) SM.focus.set(playBtn, { noScroll: true });
      clearTimeout(osdTimer);
      if (!sticky) osdTimer = setTimeout(hideOsd, 5000);
      renderBar();
    }

    function hideOsd() {
      if (!playing || SM.focus.hasLayer()) { osdTimer = setTimeout(hideOsd, 5000); return; }
      root.classList.remove('osd-visible');
    }

    function osdVisible() { return root.classList.contains('osd-visible'); }

    function renderBar() {
      var t = scrubTarget !== null ? scrubTarget : now();
      var pct = duration ? Math.min(100, 100 * now() / duration) : 0;
      fill.style.width = pct + '%';
      var at = (duration ? Math.min(100, 100 * t / duration) : 0) + '%';
      scrubMark.style.left = at;
      scrubMark.style.display = scrubTarget !== null || SM.focus.get() === bar ? 'block' : 'none';
      bubble.style.left = at;
      bubbleTime.textContent = SM.util.clock(t);
      bubble.classList.toggle('on', scrubTarget !== null);
      if (scrubTarget !== null) requestFrame(scrubTarget);
      else bubble.classList.remove('has-frame');
      clockEl.textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      timeEl.textContent = SM.util.clock(t);
      remainEl.textContent = duration ? '−' + SM.util.clock(duration - t) : '';
      endsEl.textContent = duration ? SM.util.endsAt(duration - t) : '';
    }

    function setBuffering(b) {
      if (b !== buffering) SM.devlog.log('player.buffering', b);
      buffering = b;
      spinner.classList.toggle('on', b);
    }

    // ── progress / next episode ──
    function reportProgress(force) {
      if (!decision) return;
      var t = now();
      if (!force && (Date.now() - lastProgressAt < PROGRESS_EVERY * 1000 || Math.abs(t - lastReported) < 2)) return;
      lastProgressAt = Date.now();
      lastReported = t;
      SM.api.progress(item.id, t, duration).catch(function () {});
    }

    function onEnded() {
      ended = true;
      playing = false;
      updatePlayIcon();
      SM.api.progress(item.id, duration, duration).catch(function () {});
      SM.router.markStale();
      if (item.next && S.get('autoplayNext')) showUpNext(10);
      else SM.router.pop();
    }

    function showUpNext(seconds) {
      var n = item.next;
      var count = el('span', { text: String(seconds) });
      SM.util.clear(upNext).appendChild(el('div.up-next-card', [
        el('div.eyebrow', [el('span', { text: 'Up next in ' }), count]),
        el('h3', { text: SM.util.episodeCode(n) + ' · ' + n.title }),
        el('div.actions', { 'data-group': '' }, [
          ui.button('Play now', 'play', playNext, 'primary autofocus'),
          ui.button('Cancel', null, function () { SM.router.pop(); }),
        ]),
      ]));
      upNext.classList.remove('hidden');
      SM.focus.focusFirst(upNext);
      var left = seconds;
      nextTimer = setInterval(function () {
        left--;
        count.textContent = String(left);
        if (left <= 0) playNext();
      }, 1000);
    }

    function playNext() {
      if (!item.next) return;
      clearInterval(nextTimer);
      reportProgress(true);
      var nextItem = item.next;
      // Fetch full detail so the next player knows its own "next".
      SM.api.item(nextItem.id).then(function (full) {
        SM.router.pop();
        play(full, {});
      }, function () {
        SM.router.pop();
        play(nextItem, {});
      });
    }

    var snapEvery = 0, lastTickTime = -1;
    function tick() {
      if (!backend || destroyed) return;
      if (buffering && playing) {
        // Some TVs never send "buffering complete": the clock advancing is proof enough.
        var bt = backend.time();
        if (lastTickTime >= 0 && bt > lastTickTime + 0.15) setBuffering(false);
        lastTickTime = bt;
      } else {
        lastTickTime = -1;
      }
      if (SM.devlog.on && ++snapEvery % 25 === 0) {   // every ~5 s
        SM.devlog.log('player.snapshot', { t: now(), playing: playing, buffering: buffering,
          state: backend.state ? backend.state() : null, osd: osdVisible(),
          center: SM.devlog.at(960, 540), near: SM.devlog.near(960, 540, 200), focus: SM.devlog.describe(SM.focus.get()) });
      }
      if (SM.devlog.on) devMarkTest();
      var t = now();
      if (subRenderer) subRenderer.update(t);
      if (osdVisible()) renderBar();
      if (playing && !buffering) reportProgress(false);
    }

    // ── keys ──
    view.onKey = function (action) {
      if (SM.focus.hasLayer()) return false; // menus handle themselves
      var upNextOpen = !upNext.classList.contains('hidden');
      switch (action) {
        case 'back':
          if (upNextOpen) { SM.router.pop(); return true; }
          if (scrubTarget !== null) { cancelScrub(); return true; }
          if (osdVisible()) { root.classList.remove('osd-visible'); return true; }
          return false; // router pops the player
        case 'play': if (!playing) togglePlay(); return true;
        case 'pause': if (playing) togglePlay(); return true;
        case 'playpause': togglePlay(); return true;
        case 'stop': SM.router.pop(); return true;
        case 'ff': seekBy(30); return true;
        case 'rw': seekBy(-10); return true;
        case 'info': case 'green': toggleInfo(); return true;
        case 'red': chooseAudio(); return true;
        case 'yellow': chooseSubs(); return true;
        case 'blue': addBookmark(); return true;
        case 'chup': if (item.next) playNext(); return true;
      }
      if (upNextOpen) return false;
      if (!osdVisible()) {
        if (action === 'left') { scrub(-1); return true; }
        if (action === 'right') { scrub(1); return true; }
        if (action === 'enter') { togglePlay(); return true; }
        // Up: straight to the time bar for scrubbing; Down: the buttons
        if (action === 'up') { showOsd(); SM.focus.set(bar, { noScroll: true }); renderBar(); return true; }
        if (action === 'down') { showOsd(); SM.focus.set(playBtn, { noScroll: true }); return true; }
      } else {
        showOsd();
        if (SM.focus.get() === bar) {
          if (action === 'left' || action === 'right') { scrub(action === 'left' ? -1 : 1); return true; }
          if (action === 'enter') { if (scrubTarget !== null) commitScrub(); else togglePlay(); return true; }
          if (action === 'up') return true;
        }
      }
      return false;
    };

    // Developer builds: a labelled two-step test, 10 s after the controls hide, to find what
    // draws a mark in the middle of the picture. 1: the picture shrinks to the top-left corner
    // (a mark from the video itself moves with it). 2: the picture is full again but the
    // <object> the TV's player is attached to moves to a corner (a mark it draws goes with it).
    var devTicks = 0, devStep = 0, devLabel = null;
    function devSetStep(step, text) {
      if (step === devStep) return;
      devStep = step;
      var obj = backend.obj, av = backend.av;
      try {
        if (av) av.setDisplayRect.apply(av, step === 1 ? [0, 0, 960, 540] : [0, 0, 1920, 1080]);
      } catch (e) { SM.devlog.log('dev.test.rect.fail', String(e && e.name)); }
      if (obj) obj.style.cssText = step === 2 ? 'left:1904px;top:1064px;width:16px;height:16px;' : '';
      if (!devLabel) {
        devLabel = el('div', { style: { position: 'absolute', left: '40px', top: '40px', zIndex: 50, padding: '14px 24px',
          borderRadius: '12px', background: 'rgba(0,0,0,.8)', color: '#fff', fontSize: '34px', fontWeight: 700 } });
        root.appendChild(devLabel);
      }
      devLabel.textContent = text || '';
      devLabel.style.display = text ? 'block' : 'none';
      SM.devlog.log('dev.test', { step: step, label: text || '' });
    }
    function devMarkTest() {
      if (devTicks < 0) return;                              // finished or abandoned
      if (!playing || buffering || osdVisible()) {
        if (devStep) { devSetStep(0, ''); devTicks = -1; SM.devlog.log('dev.test', 'stopped (controls or pause)'); }
        return;
      }
      var n = ++devTicks;
      if (n === 50) devSetStep(1, 'Test 1 of 2: picture moved to top-left');
      else if (n === 100) devSetStep(2, 'Test 2 of 2: video element moved to a corner');
      else if (n === 150) devSetStep(3, 'Tests done');
      else if (n === 165) { devSetStep(0, ''); devTicks = -1; }
    }

    function setPlayingClass(on) {
      document.documentElement.classList.toggle('playing', on);
      document.body.classList.toggle('playing', on);
    }
    view.onShow = function () { setPlayingClass(true); };
    view.onHide = function () { setPlayingClass(false); };

    function onVisibility() {
      if (!backend) return;
      if (document.hidden) {
        reportProgress(true);
        if (playing) { backend.pause(); playing = false; updatePlayIcon(); }
      }
    }

    view.destroy = function () {
      SM.devlog.log('player.destroy', { t: now() });
      setTimeout(function () {
        SM.devlog.log('after-player', { view: (SM.router.top() || {}).name, focus: SM.devlog.describe(SM.focus.get()),
          connected: !!(SM.focus.get() && SM.focus.get().isConnected), layers: SM.focus.hasLayer(),
          active: SM.devlog.describe(document.activeElement), center: SM.devlog.at(960, 540) });
      }, 2500);
      destroyed = true;
      reportProgress(true);
      clearInterval(tickTimer);
      clearInterval(nextTimer);
      clearTimeout(osdTimer);
      clearTimeout(scrubTimer);
      document.removeEventListener('visibilitychange', onVisibility);
      if (backend) backend.stop();
      setPlayingClass(false);
      SM.router.markStale();
    };

    // ── boot ──
    backend = SM.backends.create(mount);
    backend.on('time', function () { if (buffering && playing) setBuffering(false); });
    backend.on('buffering', setBuffering);
    backend.on('ended', onEnded);
    backend.on('error', onError);
    document.addEventListener('visibilitychange', onVisibility);
    tickTimer = setInterval(tick, 200);

    var resumeAt = opts.resume ? SM.util.resumeAt(item) : 0;
    if (opts.startAt !== undefined) resumeAt = opts.startAt;   // e.g. a bookmark
    pictureBtn.lastChild.textContent = pictureLabel();
    renderTicks();
    if (!item.bookmarks) {
      SM.api.bookmarks(item.id).then(function (r) { bookmarks = r.bookmarks; renderTicks(); }, function () {});
    }
    start(resumeAt, opts.audioIndex === null ? undefined : opts.audioIndex);
    showOsd();
    return view;
  });

  SM.player = { play: play };
})();
