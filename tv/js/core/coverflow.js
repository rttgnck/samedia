/* Cover Flow shelf — a modern take on the iPod's Cover Flow.
 *
 * The centred cover faces the viewer; neighbours turn away in 3D and slide along as you
 * scroll, with a floor reflection. OK on the centre cover flips it over to its back, which
 * holds the details and Play / More info buttons (like flipping an album on the iPod).
 *
 * Only a window of covers around the centre exists in the DOM, so libraries with thousands
 * of titles stay smooth on the TV. Everything animates with transforms (GPU-composited).
 */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui;
  var WINDOW = 8;          // covers rendered on each side of the centre
  var FIRST_GAP = 250;     // px from the centre to the first side cover
  var STEP = 96;           // px between stacked side covers
  var ANGLE = 64;          // degrees side covers turn away
  var CENTER_Z = 170;      // centre cover pops towards the viewer
  var FLIP_Z = 270;        // ...and further when flipped

  function transformFor(d) {
    if (d === 0) return 'translate3d(0,0,' + CENTER_Z + 'px)';
    var s = d < 0 ? -1 : 1, a = Math.abs(d);
    return 'translate3d(' + (s * (FIRST_GAP + (a - 1) * STEP)) + 'px,0,0) rotateY(' + (-s * ANGLE) + 'deg)';
  }

  /**
   * opts: { startIndex, onChange(item), onOpen(item), onPlay(item, resume), backContent(item) -> Promise<{meta, plot, play}> }
   */
  function CoverFlow(items, opts) {
    opts = opts || {};
    var index = Math.max(0, Math.min(items.length - 1, opts.startIndex || 0));
    var nodes = {};                      // item index -> cover element
    var flipped = null;                  // cover currently showing its back
    var stage = el('div.cf-stage');
    var title = el('div.cf-title'), meta = el('div.cf-meta');
    var caption = el('div.cf-caption', [title, meta]);
    var scrubFill = el('i'), scrubLabel = el('span.cf-count');
    var scrub = el('div.cf-scrub', [el('div.cf-track', [scrubFill]), scrubLabel]);
    var root = el('div.coverflow.f', [stage, caption, scrub]);

    function cover(i) {
      var it = items[i];
      var isCol = it.kind === 'collection';
      var front = el('div.cf-front', [ui.image(it.poster, 400, it.title, 'poster'),
        it.watched ? el('div.watched', [ui.icon('check')]) : null, ui.progressBar(it),
        isCol ? el('div.count', { text: String(it.item_count) }) : null,
        it.kind === 'show' && it.unwatched ? el('div.count', { text: String(it.unwatched) }) : null]);
      var back = el('div.cf-back');
      var node = el('div.cf-cover' + (isCol ? '.stack' : ''), { dataset: { i: String(i) } }, [el('div.cf-card', [front, back])]);
      node.addEventListener('click', function (e) {
        if (e.target.closest('.cf-back')) return;
        if (i === index) toggleFlip();
        else setIndex(i);
      });
      return node;
    }

    function layout() {
      var lo = Math.max(0, index - WINDOW), hi = Math.min(items.length - 1, index + WINDOW);
      Object.keys(nodes).forEach(function (k) {
        var i = +k;
        if (i < lo || i > hi) { nodes[k].remove(); delete nodes[k]; }
      });
      for (var i = lo; i <= hi; i++) {
        var n = nodes[i];
        var fresh = !n;
        if (fresh) {
          n = nodes[i] = cover(i);
          // Enter from the edge already turned, so it slides in instead of popping.
          n.style.transition = 'none';
          n.style.transform = transformFor(i < index ? -WINDOW - 1 : WINDOW + 1);
          n.style.opacity = '0';
          stage.appendChild(n);
        }
        var d = i - index;
        n.style.zIndex = String(100 - Math.abs(d));
        n.classList.toggle('center', d === 0);
        if (fresh) void n.offsetWidth; // commit the start position before animating
        n.style.transition = '';
        n.style.transform = transformFor(d);
        n.style.opacity = Math.abs(d) > WINDOW - 1 ? '0' : '1';
      }
      var it = items[index];
      title.textContent = it ? it.title : '';
      var bits = [];
      if (it && it.kind === 'collection') {
        bits.push(it.item_count + ' movies');
        if (it.years) bits.push(it.years);
      } else if (it) {
        if (it.kind === 'episode') bits.push(it.show_title + ' · ' + SM.util.episodeCode(it));
        if (it.year) bits.push(String(it.year));
        if (it.certification) bits.push(it.certification);
        if (it.kind === 'show' && it.episode_count) bits.push(it.episode_count + ' episodes');
        if (it.duration) bits.push(SM.util.runtime(it.duration));
        if (it.rating) bits.push('★ ' + it.rating);
      }
      SM.util.clear(meta).appendChild(el('span', { text: bits.join('   ·   ') }));
      if (it && it.badges && it.badges.length) meta.appendChild(ui.badges(it.badges));
      scrubFill.style.width = items.length > 1 ? (100 * index / (items.length - 1)) + '%' : '100%';
      scrubLabel.textContent = (index + 1) + ' / ' + items.length;
      if (it && opts.onChange) opts.onChange(it);
    }

    function setIndex(i) {
      i = Math.max(0, Math.min(items.length - 1, i));
      if (i === index) return false;
      if (flipped) unflip();
      index = i;
      layout();
      return true;
    }

    // ── flip to the back of the centre cover ──
    function toggleFlip() { if (flipped) unflip(); else flip(); }

    function flip() {
      var node = nodes[index], it = items[index];
      if (!node || !it) return;
      var back = node.querySelector('.cf-back');
      var actions = el('div.cf-actions', { 'data-group': '' });
      var isCol = it.kind === 'collection';
      SM.util.clear(back).appendChild(el('div.cf-back-inner', [
        el('div.cf-back-title', { text: it.title }),
        el('div.cf-back-meta', { text: (isCol ? [it.item_count + ' movies', it.years]
          : [it.year, it.certification, it.kind === 'show' ? (it.episode_count + ' episodes') : SM.util.runtime(it.duration),
             (it.genres || []).slice(0, 2).join(', ')]).filter(Boolean).join('  ·  ') }),
        el('p.cf-back-plot', { text: it.plot || 'No description available.' }),
        actions,
      ]));
      var resumable = it.position > 30 && !it.watched;
      var play = el('div.cf-btn.f.primary.autofocus', { onclick: function () { opts.onPlay && opts.onPlay(it, true); } },
        [ui.icon('play'), el('span', { text: it.kind === 'show' ? 'Play' : (resumable ? 'Resume' : 'Play') })]);
      var info = el('div.cf-btn.f', { onclick: function () { unflip(); opts.onOpen && opts.onOpen(it); } },
        [ui.icon(it.kind === 'show' ? 'tv' : isCol ? 'stack' : 'info'),
         el('span', { text: it.kind === 'show' ? 'Episodes' : isCol ? 'All ' + it.item_count + ' movies' : 'Details' })]);
      actions.appendChild(play);
      actions.appendChild(info);
      node.classList.add('flipped');
      node.style.transform = 'translate3d(0,24px,' + FLIP_Z + 'px)';
      root.classList.add('is-flipped');
      flipped = node;
      SM.focus.pushLayer(back);
    }

    function unflip() {
      if (!flipped) return;
      var node = flipped;
      flipped = null;
      SM.focus.popLayer(node.querySelector('.cf-back'));
      node.classList.remove('flipped');
      root.classList.remove('is-flipped');
      var i = +node.dataset.i;
      node.style.transform = transformFor(i - index);
      SM.focus.set(root, { noScroll: true });
    }

    /** Called by the owning view for keys while the shelf (or a flipped back) has focus. */
    function handleKey(action) {
      if (flipped) {
        if (action === 'back') { unflip(); return true; }
        if (action === 'play' || action === 'playpause') { opts.onPlay && opts.onPlay(items[index], true); return true; }
        return false; // arrows / OK work inside the back face via the focus layer
      }
      switch (action) {
        case 'left': return setIndex(index - 1);   // false at the first cover -> focus moves to the rail
        case 'right': setIndex(index + 1); return true;
        case 'chup': setIndex(index - 10); return true;
        case 'chdown': setIndex(index + 10); return true;
        case 'rw': setIndex(index - 25); return true;
        case 'ff': setIndex(index + 25); return true;
        case 'enter': flip(); return true;
        case 'play': case 'playpause': if (items[index]) opts.onPlay && opts.onPlay(items[index], true); return true;
      }
      return false;
    }

    if (!items.length) {
      root.classList.remove('f');
      stage.appendChild(el('div.empty', [el('p', { text: 'Nothing here yet.' })]));
    } else {
      layout();
    }

    var api = {
      el: root, handleKey: handleKey, setIndex: setIndex,
      index: function () { return index; }, current: function () { return items[index]; },
      isFlipped: function () { return !!flipped; },
      jumpTo: function (id) {
        for (var i = 0; i < items.length; i++) if (items[i].id === id) { setIndex(i); return; }
      },
    };
    root._flow = api; // lets the title menu find the centre cover
    return api;
  }

  SM.CoverFlow = CoverFlow;
})();
