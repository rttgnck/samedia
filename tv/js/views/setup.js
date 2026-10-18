/* First-run / change-server screen: auto-discovery on the local network, manual IP entry, PIN pairing. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui, S = SM.settings;

  function normalise(addr) {
    addr = addr.trim();
    if (!addr) return '';
    if (!/^https?:\/\//.test(addr)) addr = 'http://' + addr;
    if (!/:\d+$/.test(addr.replace(/^https?:\/\//, ''))) addr += ':8097';
    return addr;
  }

  SM.router.register('setup', function (params) {
    var found = el('div.found-list', { 'data-group': '' });
    var status = el('div.setup-status', { text: '' });
    var netInfo = el('div.setup-net', { text: '' });
    var address = el('div.input-box', { text: '' });
    var manualValue = S.get('server') ? S.get('server').replace(/^http:\/\//, '').replace(/:8097$/, '') : '';
    address.textContent = manualValue || 'e.g. 192.168.1.20';
    address.classList.toggle('empty', !manualValue);
    var kb = ui.keyboard('ip', manualValue, function (v) {
      manualValue = v;
      address.textContent = v || 'e.g. 192.168.1.20';
      address.classList.toggle('empty', !v);
    }, function () { connect(normalise(manualValue)); });

    var root = el('div.setup', [
      el('div.setup-card', [
        el('div.brand', [el('span.logo', { text: 'S' }), el('span', { text: 'Samedia' })]),
        el('h1', { text: params.change ? 'Change server' : 'Connect to your media server' }),
        el('p.lead', { text: 'Run the Samedia server on your NAS (nasOS App Store → Samedia), then pick it below.' }),
        el('div.setup-cols', [
          el('div.setup-col', [el('h3', { text: 'On your network' }), found,
            ui.button('Search again', 'search', discover, 'ghost'), netInfo]),
          el('div.setup-col', [el('h3', { text: 'Or enter its address' }), address, kb]),
        ]),
        status,
      ]),
    ]);
    root.classList.add('fullscreen');
    var view = { el: root, fullscreen: true };

    function connect(url, info) {
      if (!url) return;
      status.textContent = 'Connecting to ' + url + '…';
      (info ? Promise.resolve(info) : SM.api.probe(url)).then(function (inf) {
        if (inf.pin_required) return askPin(url, inf);
        return finish(url, '', inf);
      }).catch(function (err) {
        status.textContent = 'Could not connect to ' + url + ': ' + err.message + (err.cause ? ' (' + err.cause + ')' : '');
      });
    }

    function askPin(url, info, wrong) {
      var pin = '';
      var box = el('div.input-box.pin', { text: '' });
      var msg = el('p', { text: wrong ? 'Wrong PIN, try again.' : 'Enter the PIN set in the server admin page.' });
      var pad = ui.keyboard('pin', '', function (v) { pin = v; box.textContent = v.replace(/./g, '●'); }, function () {
        modal.remove();
        SM.focus.popLayer(modal);
        SM.api.pair(url, pin).then(function (r) { finish(url, r.token, info); }, function () { askPin(url, info, true); });
      });
      var modal = el('div.modal', [el('div.dialog', [el('h3', { text: info.name + ' — PIN' }), msg, box, pad])]);
      modal._close = function () { modal.remove(); SM.focus.popLayer(modal); };
      modal._digit = function (d) { pad.handleDigit(d); };
      document.getElementById('overlays').appendChild(modal);
      SM.focus.pushLayer(modal);
    }

    function finish(url, token, info) {
      S.set('server', url);
      S.set('token', token);
      S.set('serverName', info.name);
      ui.toast('Connected to ' + info.name);
      SM.app.goHome();
    }

    function discover() {
      SM.util.clear(found);
      var scanning = el('div.found-empty', { text: 'Searching your network…' });
      found.appendChild(scanning);
      SM.api.discover(function (entry) {
        if (scanning.parentNode) scanning.remove();
        var row = el('div.found.f', { onclick: function () { connect(entry.url, entry.info); } }, [
          ui.icon('server'), el('div', [el('div.title', { text: entry.info.name }), el('div.sub', { text: entry.url.replace('http://', '') })]),
        ]);
        found.appendChild(row);
        if (found.children.length === 1) SM.focus.claim(view, row);
      }, null, function (net) {
        netInfo.textContent = net.ip
          ? 'This TV: ' + net.ip + ' · searching ' + net.prefix + '.1–254'
          : "Couldn't read this TV's address · trying " + net.prefix + '.1–254';
      }).then(function (all) {
        if (!all.length) scanning.textContent = 'No servers found automatically. Enter the address instead.';
      });
    }

    view.onKey = function (action) {
      if (action.indexOf('digit:') === 0) {
        var top = SM.ui.topModal();
        if (top && top._digit) top._digit(action.slice(6));
        else kb.handleDigit(action.slice(6));
        return true;
      }
      return false;
    };
    discover();
    return view;
  });
})();
