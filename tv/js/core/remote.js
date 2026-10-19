/* Remote control. The TV keeps a WebSocket to the server while it runs, so a phone or tablet
 * can tell it what to play (and pause, seek, stop it), and it reports what it is playing.
 * It can also send what it plays to another screen ("Send to…") or start a title there
 * ("Play on…"). A phone can drive the TV's menus too (arrows, OK, Back) and turn it up/down. */
(function () {
  'use strict';

  var S = SM.settings, ui = SM.ui;
  var ws = null, retry = 1000, retryTimer = null, lastState = null;
  var handlers = null;      // the player's, while it is open: pause/resume/toggle/seek/skip/stop

  function socketUrl() {
    var base = SM.api.base();
    if (!base) return null;
    var q = 'device=' + encodeURIComponent(SM.api.deviceId()) + '&name=' + encodeURIComponent(SM.api.deviceName()) + '&kind=tv' +
            '&can=keys' + (audio() ? ',volume' : '') + '&app=' + encodeURIComponent(SM.api.appTag());
    if (S.get('token')) q += '&t=' + encodeURIComponent(S.get('token'));
    return base.replace(/^http/, 'ws') + '/api/v1/remote/ws?' + q;
  }

  function connect() {
    var url = socketUrl();
    if (!url || ws) return;
    try { ws = new WebSocket(url); } catch (e) { ws = null; schedule(); return; }
    ws.onopen = function () {
      retry = 1000;
      SM.devlog.log('remote.connected');
      if (lastState) send(lastState);
    };
    ws.onmessage = function (e) {
      var m;
      try { m = JSON.parse(e.data); } catch (x) { return; }
      if (m.type === 'command') command(m);
    };
    ws.onclose = function () { ws = null; schedule(); };
    ws.onerror = function () { try { ws.close(); } catch (x) { /* closing anyway */ } };
  }

  function schedule() {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(connect, retry);
    retry = Math.min(retry * 2, 30000);
  }

  function restart() {
    if (ws) { ws.onclose = null; try { ws.close(); } catch (e) { /* gone */ } ws = null; }
    retry = 1000;
    connect();
  }

  function send(obj) {
    if (ws && ws.readyState === 1) { try { ws.send(JSON.stringify(obj)); } catch (e) { /* reconnects */ } }
  }

  /** What the TV is playing now (null when it stops). */
  function report(state) {
    lastState = { type: 'state', item_id: null };
    if (state) for (var k in state) lastState[k] = state[k];
    send(lastState);
  }

  function command(m) {
    SM.devlog.log('remote.command', m);
    if (m.action === 'play') { playHere(m); return; }
    if (m.action === 'key') { SM.app.key(m.key); return; }
    if (m.action === 'volume') { volume(m.key); return; }
    if (handlers && handlers[m.action]) handlers[m.action](m);
  }

  function audio() {
    if (SM.util.native) return SM.util.native.canVolume() ? SM.util.native : null;
    return window.tizen && tizen.tvaudiocontrol ? tizen.tvaudiocontrol : null;
  }

  /** The TV's own volume, from a phone. */
  function volume(key) {
    if (SM.util.native) {
      var said = SM.util.native.volume(key);
      if (said) ui.toast(said);
      return;
    }
    var a = audio();
    if (!a) return;
    try {
      if (key === 'mute') {
        a.setMute(!a.isMute());
        ui.toast(a.isMute() ? 'Muted' : 'Sound on');
        return;
      }
      if (a.isMute()) a.setMute(false);
      if (key === 'up') a.setVolumeUp();
      else if (key === 'down') a.setVolumeDown();
      ui.toast('Volume ' + a.getVolume());
    } catch (e) {
      SM.devlog.log('remote.volume.error', { message: e && e.message });
    }
  }

  /** Another device asked this TV to play something, as a profile, from a time. */
  function playHere(m) {
    function go() {
      SM.api.item(m.item_id).then(function (item) {
        var top = SM.router.top();
        if (top && top.name === 'player') SM.router.pop();
        SM.player.play(item, { startAt: m.position || 0 });
      }, function (err) { ui.toast('Could not play it here: ' + (err && err.message || 'unknown error')); });
    }
    if (m.profile_id && m.profile_id !== S.get('profileId')) {
      SM.api.profiles().then(function (r) {
        var p = (r.profiles || []).filter(function (x) { return x.id === m.profile_id; })[0];
        if (p) SM.app.selectProfile(p);
        go();
      }, go);
    } else {
      go();
    }
  }

  /** Choose another screen that is on; cb(player). */
  function pickPlayer(title, cb) {
    SM.api.get('/api/v1/remote/players').then(function (r) {
      var players = r.players || [];
      if (!players.length) { ui.toast('No other Samedia screens are on right now'); return; }
      ui.menu(title, players.map(function (p) {
        var now = p.now_playing;
        return { label: p.name, sub: now ? (now.playing ? 'Playing ' : 'Paused · ') + now.title : 'Idle',
                 action: function () { cb(p); } };
      }), { side: true });
    }, function () { ui.toast('Could not list the other screens'); });
  }

  /** Start a title on another screen (from a card or details page). */
  function playOn(item, position) {
    pickPlayer('Play on', function (p) {
      SM.api.post('/api/v1/remote/players/' + encodeURIComponent(p.id) + '/command',
        { action: 'play', item_id: item.id, position: position || 0, profile_id: S.get('profileId') })
        .then(function () { ui.toast('Playing on ' + p.name); },
              function (err) { ui.toast((err && err.message) || 'That screen did not answer'); });
    });
  }

  SM.remote = {
    connect: connect, restart: restart, report: report, pickPlayer: pickPlayer, playOn: playOn,
    attach: function (h) { handlers = h; },
    detach: function (h) { if (handlers === h) handlers = null; },
  };
})();
