/* View stack. Views stay in the DOM (hidden) while covered, so Back restores scroll
 * position and focus instantly.
 *
 * A view factory is registered with SM.router.register(name, factory) and returns
 *   { el, section?, fullscreen?, onShow?(), onHide?(), onKey?(action, event) -> bool, destroy?() }
 */
(function () {
  'use strict';

  var factories = {};
  var stack = [];
  var container = null;

  function init(node) { container = node; }

  function register(name, factory) { factories[name] = factory; }

  function top() { return stack[stack.length - 1] || null; }

  function build(name, params) {
    var view = factories[name](params || {});
    view.name = name;
    view.params = params || {};
    view.el.classList.add('view');
    container.appendChild(view.el);
    return view;
  }

  function hide(entry) {
    entry.focus = SM.focus.get();
    // A flipped Cover Flow back face (or similar) must not keep the remote captive
    // while another screen (e.g. the player) is on top.
    SM.focus.dropLayersWithin(entry.el);
    entry.el.classList.add('hidden');
    entry.onHide && entry.onHide();
  }

  function show(entry, restoreFocus) {
    entry.el.classList.remove('hidden');
    document.body.classList.toggle('fullscreen-view', !!entry.fullscreen);
    SM.events.emit('view', entry);
    if (entry.stale && entry.refresh) {
      entry.stale = false;
      entry.refresh();
    }
    entry.onShow && entry.onShow();
    if (restoreFocus && entry.focus && entry.focus.isConnected && entry.el.contains(entry.focus)) {
      SM.focus.set(entry.focus, { instant: true });
    } else {
      SM.focus.focusFirst(entry.el);
    }
  }

  function push(name, params) {
    closeModals();
    var prev = top();
    if (prev) hide(prev);
    var view = build(name, params);
    stack.push(view);
    show(view, false);
    return view;
  }

  /** Menus and dialogs belong to the view that opened them. */
  function closeModals() {
    var modal;
    while ((modal = SM.ui.topModal())) {
      if (modal._close) modal._close();
      if (modal.parentNode) modal.parentNode.removeChild(modal);
    }
  }

  function destroy(entry) {
    entry.onHide && !entry.el.classList.contains('hidden') && entry.onHide();
    entry.destroy && entry.destroy();
    if (entry.el.parentNode) entry.el.parentNode.removeChild(entry.el);
  }

  function pop() {
    if (stack.length <= 1) return false;
    closeModals();
    destroy(stack.pop());
    show(top(), true);
    return true;
  }

  /** Replace the whole stack (used by the nav rail to switch sections). */
  function reset(name, params) {
    closeModals();
    while (stack.length) destroy(stack.pop());
    return push(name, params);
  }

  /** Re-render the top view in place (e.g. after marking something watched). */
  function refresh() {
    var t = top();
    if (t && t.refresh) t.refresh();
  }

  /** Refresh views below the top one when they become visible again. */
  function markStale() {
    stack.forEach(function (v) { v.stale = true; });
  }

  SM.router = { init: init, register: register, push: push, pop: pop, reset: reset, top: top, refresh: refresh,
                markStale: markStale, bottom: function () { return stack[0] || null; }, depth: function () { return stack.length; } };
})();
