/* Remote-control key codes. Samsung remotes send the standard arrows/Enter plus
 * Tizen-specific codes, which must be registered before the app receives them. */
(function () {
  'use strict';

  var K = {
    LEFT: 37, UP: 38, RIGHT: 39, DOWN: 40, ENTER: 13,
    BACK: 10009, EXIT: 10182,
    PLAY: 415, PAUSE: 19, PLAY_PAUSE: 10252, STOP: 413, FF: 417, RW: 412,
    INFO: 457, RED: 403, GREEN: 404, YELLOW: 405, BLUE: 406,
    CH_UP: 427, CH_DOWN: 428,
    // Desktop browser equivalents for development.
    ESC: 27, BACKSPACE: 8, SPACE: 32, PAGE_UP: 33, PAGE_DOWN: 34,
  };

  var TIZEN_KEYS = [
    'MediaPlayPause', 'MediaPlay', 'MediaPause', 'MediaStop', 'MediaFastForward', 'MediaRewind',
    'MediaTrackPrevious', 'MediaTrackNext', 'Info', 'ColorF0Red', 'ColorF1Green', 'ColorF2Yellow',
    'ColorF3Blue', 'ChannelUp', 'ChannelDown', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
  ];

  function register() {
    if (!window.tizen || !tizen.tvinputdevice) return;
    try {
      if (tizen.tvinputdevice.registerKeyBatch) tizen.tvinputdevice.registerKeyBatch(TIZEN_KEYS);
      else TIZEN_KEYS.forEach(function (k) { tizen.tvinputdevice.registerKey(k); });
    } catch (e) {
      TIZEN_KEYS.forEach(function (k) { try { tizen.tvinputdevice.registerKey(k); } catch (_) {} });
    }
  }

  /** Normalise a KeyboardEvent to one of: left right up down enter back play pause playpause stop ff rw info red green yellow blue chup chdown digit:N */
  function action(e) {
    var c = e.keyCode;
    switch (c) {
      case K.LEFT: return 'left';
      case K.RIGHT: return 'right';
      case K.UP: return 'up';
      case K.DOWN: return 'down';
      case K.ENTER: return 'enter';
      case K.BACK: case K.ESC: return 'back';
      case K.BACKSPACE:
        // Backspace is "back" unless the user is typing into a real input (dev only).
        return e.target && e.target.tagName === 'INPUT' ? null : 'back';
      case K.PLAY: return 'play';
      case K.PAUSE: return 'pause';
      case K.PLAY_PAUSE: case K.SPACE: return 'playpause';
      case K.STOP: return 'stop';
      case K.FF: return 'ff';
      case K.RW: return 'rw';
      case K.INFO: return 'info';
      case K.RED: return 'red';
      case K.GREEN: return 'green';
      case K.YELLOW: return 'yellow';
      case K.BLUE: return 'blue';
      case K.CH_UP: case K.PAGE_UP: return 'chup';
      case K.CH_DOWN: case K.PAGE_DOWN: return 'chdown';
      case K.EXIT: return 'exit';
    }
    if (c >= 48 && c <= 57) return 'digit:' + (c - 48);
    if (c >= 96 && c <= 105) return 'digit:' + (c - 96);
    return null;
  }

  SM.keys = { codes: K, register: register, action: action };
})();
