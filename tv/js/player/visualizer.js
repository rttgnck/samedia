/* Music visualizer, the late-90s way: Winamp's spectrum analyser, an oscilloscope, a
 * MilkDrop-style feedback trip, and a spinning record with a radial spectrum. Draws on a
 * small canvas (scaled up by CSS) so TVs keep up. */
(function () {
  'use strict';

  var MODES = [
    { id: 'bars', name: 'Classic Spectrum' },
    { id: 'milk', name: 'Milkdrop' },
    { id: 'scope', name: 'Oscilloscope' },
    { id: 'disc', name: 'Vinyl' },
  ];

  function Visualizer(canvas, opts) {
    opts = opts || {};
    var W = canvas.width = opts.width || 960, H = canvas.height = opts.height || 540;
    var g = canvas.getContext('2d');
    var mode = 0, raf = 0, running = false, t0 = Date.now();
    var peaks = [], bassAvg = 0, hue = Math.random() * 360, spin = 0, art = null, artUrl = null;

    function setArt(url) {
      if (!url || url === artUrl) return;
      artUrl = url;
      var img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = function () { if (artUrl === url) art = img; };
      img.src = url;
    }

    function bass(b) { return (b[0] + b[1] + b[2] + b[3]) / 4; }

    // ── Winamp: segmented bars green → yellow → red, falling peak caps, a marquee ──
    function drawBars() {
      var n = 28, b = SM.music.bands(n);
      g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
      g.strokeStyle = 'rgba(40,80,40,.25)'; g.lineWidth = 1;
      for (var y = 60; y < H - 60; y += 24) { g.beginPath(); g.moveTo(40, y); g.lineTo(W - 40, y); g.stroke(); }
      var gap = 6, bw = (W - 80 - gap * (n - 1)) / n, base = H - 90, top = 70, seg = 9;
      var grad = g.createLinearGradient(0, base, 0, top);
      grad.addColorStop(0, '#00c800'); grad.addColorStop(0.55, '#d8e000'); grad.addColorStop(0.8, '#ff9a00'); grad.addColorStop(1, '#ff2000');
      for (var i = 0; i < n; i++) {
        var v = Math.pow(b[i], 1.3), h = v * (base - top), x = 40 + i * (bw + gap);
        for (var y2 = base - seg; y2 > base - h; y2 -= seg + 2) {
          g.fillStyle = grad; g.fillRect(x, y2, bw, seg);
        }
        // reflection
        g.globalAlpha = 0.18;
        for (var r = base + 4; r < base + 4 + h * 0.35; r += seg + 2) { g.fillStyle = grad; g.fillRect(x, r, bw, seg); }
        g.globalAlpha = 1;
        peaks[i] = Math.max((peaks[i] || 0) - 1.6, h);
        g.fillStyle = '#c8c8c8'; g.fillRect(x, base - peaks[i] - 4, bw, 3);
      }
      marquee();
    }

    function marquee() {
      var t = SM.music.current();
      if (!t) return;
      var text = (t.artist ? t.artist + ' - ' : '') + t.title + '  ***  ';
      g.font = 'bold 22px "Courier New", monospace';
      var w = g.measureText(text).width, x = 40 - ((Date.now() - t0) / 30) % w;
      g.save(); g.beginPath(); g.rect(40, 18, W - 80, 32); g.clip();
      g.fillStyle = '#00e000';
      for (var k = 0; k < 4; k++) g.fillText(text, x + k * w, 42);
      g.restore();
    }

    // ── oscilloscope with phosphor trails ──
    function drawScope() {
      g.fillStyle = 'rgba(0,10,4,.22)'; g.fillRect(0, 0, W, H);
      var w = SM.music.waveform(512), b = SM.music.bands(8), lvl = bass(b);
      g.strokeStyle = 'rgba(0,255,140,.08)'; g.lineWidth = 1;
      for (var gx = 0; gx <= W; gx += W / 10) { g.beginPath(); g.moveTo(gx, 0); g.lineTo(gx, H); g.stroke(); }
      for (var gy = 0; gy <= H; gy += H / 6) { g.beginPath(); g.moveTo(0, gy); g.lineTo(W, gy); g.stroke(); }
      g.lineWidth = 3; g.strokeStyle = 'hsl(' + (140 + lvl * 60) + ',100%,60%)';
      g.shadowColor = g.strokeStyle; g.shadowBlur = 14;
      g.beginPath();
      for (var i = 0; i < w.length; i++) {
        var x = i / (w.length - 1) * W, y = H / 2 + w[i] * H * 0.38;
        if (i) g.lineTo(x, y); else g.moveTo(x, y);
      }
      g.stroke(); g.shadowBlur = 0;
    }

    // ── MilkDrop-ish: the last frame zoomed and turned, waves on top, colours wandering ──
    function drawMilk() {
      var b = SM.music.bands(16), lvl = bass(b);
      bassAvg = bassAvg * 0.95 + lvl * 0.05;
      var beat = lvl > bassAvg * 1.35 && lvl > 0.3;
      hue = (hue + 0.6 + (beat ? 25 : 0)) % 360;
      var t = (Date.now() - t0) / 1000;
      g.save();
      g.globalAlpha = 0.93;
      g.translate(W / 2, H / 2);
      g.rotate(0.006 * Math.sin(t * 0.3) + (beat ? 0.02 : 0));
      var z = 1.018 + lvl * 0.03;
      g.scale(z, z);
      g.drawImage(canvas, -W / 2 + Math.sin(t * 0.7) * 2, -H / 2 + Math.cos(t * 0.5) * 2);
      g.restore();
      g.fillStyle = 'rgba(0,0,0,.04)'; g.fillRect(0, 0, W, H);
      var w = SM.music.waveform(180);
      g.globalCompositeOperation = 'lighter';
      g.lineWidth = 2.5;
      for (var ring = 0; ring < 2; ring++) {
        g.strokeStyle = 'hsla(' + ((hue + ring * 120) % 360) + ',100%,60%,.85)';
        g.beginPath();
        var R = H * (0.18 + ring * 0.1) + lvl * 60;
        for (var i = 0; i <= w.length; i++) {
          var a = i / w.length * Math.PI * 2 + t * (ring ? -0.4 : 0.3);
          var r = R + w[i % w.length] * 90;
          var x = W / 2 + Math.cos(a) * r * 1.3, y = H / 2 + Math.sin(a) * r;
          if (i) g.lineTo(x, y); else g.moveTo(x, y);
        }
        g.stroke();
      }
      if (beat) {
        g.fillStyle = 'hsla(' + hue + ',100%,70%,.25)';
        for (var s = 0; s < 6; s++) {
          g.beginPath(); g.arc(Math.random() * W, Math.random() * H, 3 + Math.random() * 10, 0, Math.PI * 2); g.fill();
        }
      }
      g.globalCompositeOperation = 'source-over';
    }

    // ── a record spinning, the album art on it, the spectrum around ──
    function drawDisc() {
      var n = 64, b = SM.music.bands(n / 2), lvl = bass(b);
      g.fillStyle = '#05060a'; g.fillRect(0, 0, W, H);
      if (art) {
        g.save(); g.globalAlpha = 0.18; g.filter = 'blur(20px)';
        g.drawImage(art, -60, -60 - H * 0.5, W + 120, W + 120);
        g.restore(); g.filter = 'none';
      }
      var cx = W / 2, cy = H / 2, R = H * 0.3;
      spin += SM.music.playing() ? 0.012 : 0;
      for (var i = 0; i < n; i++) {
        var v = b[i < n / 2 ? i : n - 1 - i], a = i / n * Math.PI * 2 - Math.PI / 2;
        var len = 12 + Math.pow(v, 1.2) * H * 0.22;
        g.strokeStyle = 'hsl(' + (200 + i / n * 160 + lvl * 40) + ',90%,' + (50 + v * 20) + '%)';
        g.lineWidth = 7;
        g.beginPath();
        g.moveTo(cx + Math.cos(a) * (R + 10), cy + Math.sin(a) * (R + 10));
        g.lineTo(cx + Math.cos(a) * (R + 10 + len), cy + Math.sin(a) * (R + 10 + len));
        g.stroke();
      }
      g.save();
      g.translate(cx, cy); g.rotate(spin);
      g.beginPath(); g.arc(0, 0, R * (1 + lvl * 0.04), 0, Math.PI * 2); g.fillStyle = '#111'; g.fill();
      for (var groove = R * 0.95; groove > R * 0.45; groove -= 6) {
        g.beginPath(); g.arc(0, 0, groove, 0, Math.PI * 2); g.strokeStyle = 'rgba(255,255,255,.05)'; g.lineWidth = 1; g.stroke();
      }
      if (art) {
        g.beginPath(); g.arc(0, 0, R * 0.42, 0, Math.PI * 2); g.clip();
        g.drawImage(art, -R * 0.42, -R * 0.42, R * 0.84, R * 0.84);
      }
      g.restore();
      g.beginPath(); g.arc(cx, cy, 5, 0, Math.PI * 2); g.fillStyle = '#ddd'; g.fill();
    }

    var DRAW = { bars: drawBars, scope: drawScope, milk: drawMilk, disc: drawDisc };

    function frame() {
      if (!running) return;
      try { DRAW[MODES[mode].id](); } catch (e) { /* keep going */ }
      raf = requestAnimationFrame(frame);
    }

    return {
      start: function () { if (running) return; running = true; g.fillStyle = '#000'; g.fillRect(0, 0, W, H); frame(); },
      stop: function () { running = false; cancelAnimationFrame(raf); },
      next: function (step) {
        mode = (mode + (step || 1) + MODES.length) % MODES.length;
        g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
        return MODES[mode].name;
      },
      setMode: function (id) { MODES.forEach(function (m, i) { if (m.id === id) mode = i; }); },
      step: function () { DRAW[MODES[mode].id](); },            // one frame (for checking)
      mode: function () { return MODES[mode].id; },
      setArt: setArt,
    };
  }

  SM.Visualizer = Visualizer;
  SM.Visualizer.MODES = MODES;
})();
