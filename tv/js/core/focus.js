/* Spatial D-pad navigation.
 *
 * Focusable elements carry class "f". Movement picks the nearest focusable in the pressed
 * direction, strongly preferring elements that overlap on the other axis (same row/column).
 * Containers with [data-group] remember their last focused child, so returning to a row
 * lands where you left it. Ancestors with [data-scroll="x" | "y" | "y-near"] are scrolled
 * to keep the focused element in view.
 *
 * Layers: modals push a layer so navigation stays inside them until popped.
 */
(function () {
  'use strict';

  var current = null;
  var layers = [];            // stack of root elements; last one is active
  var baseRoot = null;        // function returning the default root(s)

  function setBaseRoot(fn) { baseRoot = fn; }

  function roots() {
    if (layers.length) return [layers[layers.length - 1]];
    return baseRoot ? baseRoot() : [document.body];
  }

  function visible(node) {
    if (!node.isConnected || node.offsetParent === null) return false;
    if (node.classList.contains('disabled') || node.hasAttribute('disabled')) return false;
    return true;
  }

  function candidates() {
    var list = [];
    roots().forEach(function (r) {
      if (!r) return;
      var nodes = r.querySelectorAll('.f');
      for (var i = 0; i < nodes.length; i++) if (visible(nodes[i])) list.push(nodes[i]);
    });
    return list;
  }

  function inRoots(node) {
    return roots().some(function (r) { return r && r.contains(node); });
  }

  function set(node, opts) {
    if (!node) return;
    opts = opts || {};
    if (current && current !== node) {
      current.classList.remove('focused');
      current.dispatchEvent(new CustomEvent('blur:sk'));
    }
    current = node;
    node.classList.add('focused');
    var g = node.closest('[data-group]');
    if (g) g._skLast = node;
    if (!opts.noScroll) ensureVisible(node, opts.instant);
    node.dispatchEvent(new CustomEvent('focus:sk', { bubbles: true }));
  }

  function get() { return current; }

  /** Focus the remembered child of a group, else its first focusable. */
  function groupEntry(group) {
    if (group._skLast && visible(group._skLast) && group.contains(group._skLast)) return group._skLast;
    var items = group.querySelectorAll('.f');
    for (var i = 0; i < items.length; i++) if (visible(items[i])) return items[i];
    return null;
  }

  function overlap(a1, a2, b1, b2) { return Math.min(a2, b2) - Math.max(a1, b1); }

  function move(dir) {
    if (!current || !visible(current) || !inRoots(current)) {
      focusFirst();
      return true;
    }
    var from = current.getBoundingClientRect();
    var best = null, bestScore = Infinity;
    var horizontal = dir === 'left' || dir === 'right';
    candidates().forEach(function (c) {
      if (c === current) return;
      var r = c.getBoundingClientRect();
      var primary, cross;
      if (dir === 'right') { if (r.left < from.right - 2 && r.left <= from.left) return; primary = r.left - from.right; }
      if (dir === 'left') { if (r.right > from.left + 2 && r.right >= from.right) return; primary = from.left - r.right; }
      if (dir === 'down') { if (r.top < from.bottom - 2 && r.top <= from.top) return; primary = r.top - from.bottom; }
      if (dir === 'up') { if (r.bottom > from.top + 2 && r.bottom >= from.bottom) return; primary = from.top - r.bottom; }
      primary = Math.max(0, primary);
      var ov = horizontal ? overlap(from.top, from.bottom, r.top, r.bottom) : overlap(from.left, from.right, r.left, r.right);
      if (ov > 0) {
        cross = 0;
      } else {
        // Distance between centres on the cross axis.
        cross = horizontal ? Math.abs((r.top + r.bottom) / 2 - (from.top + from.bottom) / 2)
                           : Math.abs((r.left + r.right) / 2 - (from.left + from.right) / 2);
      }
      var score = primary + cross * 4 + (ov > 0 ? 0 : 400);
      if (score < bestScore) { bestScore = score; best = c; }
    });
    if (!best) return false;

    // Entering a different group: jump to its remembered child instead.
    var fromGroup = current.closest('[data-group]');
    var toGroup = best.closest('[data-group]');
    if (toGroup && toGroup !== fromGroup && !toGroup.hasAttribute('data-no-memory')) {
      var remembered = groupEntry(toGroup);
      if (remembered) best = remembered;
    }
    set(best);
    return true;
  }

  function focusFirst(scope) {
    var preferred = null;
    var rs = scope ? [scope] : roots();
    rs.some(function (r) {
      if (!r) return false;
      preferred = r.querySelector('.f.autofocus') || null;
      if (preferred && !visible(preferred)) preferred = null;
      if (!preferred) {
        var all = r.querySelectorAll('.f');
        for (var i = 0; i < all.length; i++) if (visible(all[i]) && !all[i].closest('.nav')) { preferred = all[i]; break; }
      }
      return !!preferred;
    });
    if (preferred) set(preferred, { instant: true });
  }

  function ensureVisible(node, instant) {
    var p = node.parentElement;
    while (p && p !== document.body) {
      var mode = p.getAttribute('data-scroll');
      if (mode) {
        var behavior = instant ? 'auto' : 'smooth';
        var pr = p.getBoundingClientRect(), nr = node.getBoundingClientRect();
        var padStart = parseInt(p.getAttribute('data-pad') || '0', 10);
        if (mode === 'x') {
          var targetX = p.scrollLeft + (nr.left - pr.left) - padStart;
          scrollTo(p, { left: Math.max(0, targetX), behavior: behavior });
        } else if (mode === 'y') {
          var anchor = node.closest('[data-row]') || node;
          var ar = anchor.getBoundingClientRect();
          scrollTo(p, { top: Math.max(0, p.scrollTop + (ar.top - pr.top) - padStart), behavior: behavior });
        } else if (mode === 'y-near') {
          var margin = padStart || 60;
          if (nr.top < pr.top + margin) scrollTo(p, { top: p.scrollTop - (pr.top + margin - nr.top), behavior: behavior });
          else if (nr.bottom > pr.bottom - margin) scrollTo(p, { top: p.scrollTop + (nr.bottom - pr.bottom + margin), behavior: behavior });
        }
      }
      p = p.parentElement;
    }
  }

  function scrollTo(node, opts) {
    try { node.scrollTo(opts); } catch (e) {
      if (opts.left !== undefined) node.scrollLeft = opts.left;
      if (opts.top !== undefined) node.scrollTop = opts.top;
    }
  }

  function pushLayer(root) {
    layers.push(root);
    root._skPrevFocus = current;
    focusFirst(root);
  }

  function popLayer(root) {
    var idx = layers.lastIndexOf(root);
    if (idx === -1) return;
    layers.splice(idx, 1);
    var prev = root._skPrevFocus;
    if (prev && visible(prev)) set(prev, { noScroll: true });
    else focusFirst();
  }

  function hasLayer() { return layers.length > 0; }

  /** Drop focus (e.g. leaving the nav rail) so content that loads later can claim it. */
  function release() {
    if (current) current.classList.remove('focused');
    current = null;
  }

  /** Async content may take focus only if the user isn't in the nav rail or a menu meanwhile. */
  function claim(view, node) {
    if (!node || SM.router.top() !== view || layers.length) return;
    if (current && current.isConnected && current.closest('.nav')) return;
    set(node, { instant: true });
  }

  SM.focus = {
    set: set, get: get, move: move, focusFirst: focusFirst, setBaseRoot: setBaseRoot,
    pushLayer: pushLayer, popLayer: popLayer, hasLayer: hasLayer, ensureVisible: ensureVisible,
    groupEntry: groupEntry, claim: claim, release: release,
  };
})();
