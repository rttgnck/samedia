/* Settings: playback preferences, codec overrides, server connection. */
(function () {
  'use strict';

  var el = SM.util.el, ui = SM.ui, S = SM.settings;

  var LANGS = [['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'], ['it', 'Italian'],
               ['pt', 'Portuguese'], ['ja', 'Japanese'], ['ko', 'Korean'], ['zh', 'Chinese'], ['nl', 'Dutch'],
               ['sv', 'Swedish'], ['ru', 'Russian'], ['hi', 'Hindi']];

  function langName(code) {
    var m = LANGS.filter(function (l) { return l[0] === code; })[0];
    return m ? m[1] : code;
  }

  SM.router.register('settings', function () {
    var list = el('div.settings-list', { 'data-group': '' });
    var scroller = el('div.settings-scroll', { 'data-scroll': 'y-near', 'data-pad': '120' }, [list]);
    var root = el('div.settings', [el('h1.page-title', { text: 'Settings' }), scroller]);
    var view = { el: root, section: 'settings' };

    function pick(title, key, options, after) {
      ui.menu(title, options.map(function (o) {
        return { label: o[1], sub: o[2], selected: S.get(key) === o[0], action: function () { S.set(key, o[0]); after && after(); render(); } };
      }), { side: true });
    }

    function toggle(key) { S.set(key, !S.get(key)); render(); }

    function rowItem(label, value, onClick, sub, k) {
      var r = el('div.setting.f', { onclick: onClick, dataset: { k: k || label } }, [
        el('div', [el('div.label', { text: label }), sub ? el('div.sub', { text: sub }) : null]),
        el('div.value', { text: value }),
      ]);
      return r;
    }

    function onOff(v) { return v ? 'On' : 'Off'; }

    function header(text) { return el('h2.settings-header', { text: text }); }

    function render() {
      var focusK = SM.focus.get() && SM.focus.get().dataset ? SM.focus.get().dataset.k : null;
      SM.util.clear(list);
      if (S.get('profileName')) {
        list.appendChild(header('Profile'));
        list.appendChild(rowItem("Who's watching", S.get('profileName') + (S.get('profileKids') ? ' · Kids' : ''), function () {
          SM.router.reset('profiles', {});
        }, 'Switch profile, add one, or turn kids mode on or off', 'profile'));
        list.appendChild(rowItem('Hidden titles', '', function () { SM.router.push('hidden', {}); },
          'Hold OK on a title and choose Hide to keep it out of this profile', 'hidden'));
      }
      list.appendChild(header('Playback'));
      list.appendChild(rowItem('Preferred audio language', langName(S.get('audioLanguage')), function () {
        pick('Audio language', 'audioLanguage', LANGS);
      }));
      list.appendChild(rowItem('Subtitles', {
        off: 'Off', forced: 'Forced only', auto: 'Automatic', always: 'Always on',
      }[S.get('subtitleMode')], function () {
        pick('Subtitles', 'subtitleMode', [
          ['auto', 'Automatic', 'On when the audio is not in your subtitle language; forced subtitles otherwise'],
          ['always', 'Always on'], ['forced', 'Forced only', 'Signs and foreign-language parts'], ['off', 'Off']]);
      }));
      list.appendChild(rowItem('Subtitle language', langName(S.get('subtitleLanguage')), function () {
        pick('Subtitle language', 'subtitleLanguage', LANGS);
      }));
      list.appendChild(rowItem('Subtitle size', { small: 'Small', medium: 'Medium', large: 'Large' }[S.get('subtitleSize')], function () {
        pick('Subtitle size', 'subtitleSize', [['small', 'Small'], ['medium', 'Medium'], ['large', 'Large']]);
      }));
      list.appendChild(rowItem('Subtitle background', onOff(S.get('subtitleBackground')), function () { toggle('subtitleBackground'); }));
      list.appendChild(rowItem('Autoplay next episode', onOff(S.get('autoplayNext')), function () { toggle('autoplayNext'); }));
      list.appendChild(rowItem('Show playback info', onOff(S.get('showPlaybackInfo')), function () { toggle('showPlaybackInfo'); },
        'Overlay showing direct play / conversion and why'));

      list.appendChild(header('Formats this TV plays natively'));
      list.appendChild(el('p.settings-note', { text: 'Anything switched off is converted on the server (audio only — video is never re-encoded unless the TV cannot decode it). If a format plays silently or fails, switch it off.' }));
      list.appendChild(rowItem('DTS / DTS-HD / DTS:X', onOff(S.get('capDTS')), function () { toggle('capDTS'); },
        'Samsung TVs since 2018 have no DTS decoder; leave off unless your model has one'));
      list.appendChild(rowItem('Dolby TrueHD / Atmos', onOff(S.get('capTrueHD')), function () { toggle('capTrueHD'); },
        'Try On if your soundbar is connected via eARC'));
      list.appendChild(rowItem('FLAC audio', onOff(S.get('capFLAC')), function () { toggle('capFLAC'); }));
      list.appendChild(rowItem('Opus audio', onOff(S.get('capOpus')), function () { toggle('capOpus'); }));
      list.appendChild(rowItem('AV1 video', onOff(S.get('capAV1')), function () { toggle('capAV1'); }));

      list.appendChild(header('Server'));
      list.appendChild(rowItem(S.get('serverName') || 'Samedia server', S.get('server'), function () {
        SM.router.push('setup', { change: true });
      }, 'Select to change server', 'server'));
      var model = '';
      try { model = webapis.productinfo.getRealModel() + ' · Tizen ' + tizen.systeminfo.getCapability('http://tizen.org/feature/platform.version'); } catch (e) { model = navigator.userAgent.slice(0, 60); }
      list.appendChild(rowItem('About', 'Samedia ' + SM.VERSION, null, model, 'about'));

      var again = focusK && list.querySelector('[data-k="' + focusK + '"]');
      SM.focus.claim(view, again || list.querySelector('.f'));
    }

    render();
    view.refresh = render;
    return view;
  });
})();
