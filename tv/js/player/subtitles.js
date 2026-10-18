/* Subtitle rendering done by the app itself, so subtitles never force a video transcode.
 *   - WebVTT (the server converts SRT/ASS/embedded text to VTT) -> text cues in a <div>
 *   - PGS / .sup (Blu-ray bitmap subtitles) -> decoded here and drawn on a <canvas>
 */
(function () {
  'use strict';

  // ── WebVTT ──────────────────────────────────────────────────────

  function parseTimestamp(s) {
    var m = /(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})/.exec(s);
    if (!m) return null;
    return (parseInt(m[1] || '0', 10) * 3600) + parseInt(m[2], 10) * 60 + parseInt(m[3], 10) +
      parseInt((m[4] + '00').slice(0, 3), 10) / 1000;
  }

  function parseVTT(text) {
    var cues = [];
    var blocks = text.replace(/\r/g, '').split(/\n{2,}/);
    blocks.forEach(function (block) {
      var lines = block.split('\n');
      var i = 0;
      while (i < lines.length && lines[i].indexOf('-->') === -1) i++;
      if (i >= lines.length) return;
      var parts = lines[i].split('-->');
      var start = parseTimestamp(parts[0]), end = parseTimestamp(parts[1]);
      if (start === null || end === null) return;
      var body = lines.slice(i + 1).join('\n').trim();
      if (!body) return;
      var top = /line:\s*(?:[0-3]?\d(?:\.\d+)?%|[0-5](?![\d.%]))/.test(parts[1]);
      cues.push({ start: start, end: end, html: sanitize(body), top: top });
    });
    cues.sort(function (a, b) { return a.start - b.start; });
    return cues;
  }

  /** Keep <i>, <b>, <u>; drop everything else (including <c.class>, <v Speaker>, ASS {\tags}). */
  function sanitize(s) {
    s = s.replace(/\{\\[^}]*\}/g, '');
    s = s.replace(/&(?!amp;|lt;|gt;|nbsp;|quot;|#\d+;)/g, '&amp;');
    s = s.replace(/<(\/?)([a-z]+)[^>]*>/gi, function (_, close, tag) {
      tag = tag.toLowerCase();
      return (tag === 'i' || tag === 'b' || tag === 'u') ? '<' + close + tag + '>' : '';
    });
    return s.replace(/\n/g, '<br>');
  }

  /** Binary search: all cues active at time t (cues may overlap). */
  function activeCues(cues, t) {
    var lo = 0, hi = cues.length - 1, first = cues.length;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (cues[mid].start <= t) lo = mid + 1;
      else { first = mid; hi = mid - 1; }
    }
    var out = [];
    // Scan back a little: earlier-starting cues that are still on screen.
    for (var i = first - 1; i >= 0 && i >= first - 12; i--) if (cues[i].end > t) out.unshift(cues[i]);
    return out;
  }

  // ── PGS (Presentation Graphic Stream) ───────────────────────────

  var SEG_PDS = 0x14, SEG_ODS = 0x15, SEG_PCS = 0x16, SEG_WDS = 0x17, SEG_END = 0x80;

  /** Parse a .sup file into display events: [{time, width, height, objects:[{x,y,w,h,data,palette}]}] */
  function parsePGS(buffer) {
    var d = new DataView(buffer);
    var pos = 0, len = buffer.byteLength;
    var palettes = {}, objects = {}, pending = null, events = [];

    while (pos + 13 <= len) {
      if (d.getUint8(pos) !== 0x50 || d.getUint8(pos + 1) !== 0x47) { pos++; continue; } // resync on "PG"
      var pts = d.getUint32(pos + 2) / 90000;
      var type = d.getUint8(pos + 10);
      var size = d.getUint16(pos + 11);
      var p = pos + 13;
      if (p + size > len) break;

      if (type === SEG_PCS) {
        var compState = d.getUint8(p + 7);
        if (compState === 0x80) objects = {}; // epoch start: forget old objects
        var count = d.getUint8(p + 10);
        var comp = { time: pts, width: d.getUint16(p), height: d.getUint16(p + 2), paletteId: d.getUint8(p + 9), refs: [] };
        var q = p + 11;
        for (var i = 0; i < count; i++) {
          var cropped = d.getUint8(q + 3) & 0x80;
          comp.refs.push({ id: d.getUint16(q), x: d.getUint16(q + 4), y: d.getUint16(q + 6) });
          q += cropped ? 16 : 8;
        }
        pending = comp;
      } else if (type === SEG_PDS) {
        var pid = d.getUint8(p);
        var pal = palettes[pid] || (palettes[pid] = new Uint32Array(256));
        palettes[pid] = pal = new Uint32Array(pal); // copy: earlier events keep their colours
        for (var e = p + 2; e + 5 <= p + size; e += 5) {
          pal[d.getUint8(e)] = ycbcrToRGBA(d.getUint8(e + 1), d.getUint8(e + 3), d.getUint8(e + 2), d.getUint8(e + 4));
        }
      } else if (type === SEG_ODS) {
        var oid = d.getUint16(p);
        var seq = d.getUint8(p + 3);
        if (seq & 0x80) { // first fragment carries the dimensions
          var obj = { w: d.getUint16(p + 7), h: d.getUint16(p + 9), chunks: [new Uint8Array(buffer, p + 11, size - 11)] };
          objects[oid] = obj;
        } else if (objects[oid]) {
          objects[oid].chunks.push(new Uint8Array(buffer, p + 4, size - 4));
        }
      } else if (type === SEG_END && pending) {
        var pal2 = palettes[pending.paletteId];
        var ev = { time: pending.time, width: pending.width, height: pending.height, objects: [] };
        pending.refs.forEach(function (r) {
          var o = objects[r.id];
          if (o && pal2) ev.objects.push({ x: r.x, y: r.y, w: o.w, h: o.h, chunks: o.chunks, palette: pal2 });
        });
        events.push(ev);
        pending = null;
      }
      // SEG_WDS (windows) is not needed for rendering.
      pos = p + size;
    }
    events.sort(function (a, b) { return a.time - b.time; });
    return events;
  }

  function clamp(v) { return v < 0 ? 0 : v > 255 ? 255 : v; }

  /** BT.709 YCbCr (studio range) to packed little-endian RGBA for ImageData. */
  function ycbcrToRGBA(y, cb, cr, a) {
    var Y = 1.164 * (y - 16), Cb = cb - 128, Cr = cr - 128;
    var r = clamp(Math.round(Y + 1.793 * Cr));
    var g = clamp(Math.round(Y - 0.213 * Cb - 0.533 * Cr));
    var b = clamp(Math.round(Y + 2.112 * Cb));
    return ((a << 24) | (b << 16) | (g << 8) | r) >>> 0;
  }

  /** Run-length decode a PGS object into 32-bit pixels. */
  function decodeObject(o) {
    var total = 0;
    o.chunks.forEach(function (c) { total += c.length; });
    var data = new Uint8Array(total), off = 0;
    o.chunks.forEach(function (c) { data.set(c, off); off += c.length; });
    var px = new Uint32Array(o.w * o.h);
    var i = 0, x = 0, y = 0, pal = o.palette;
    while (i < data.length && y < o.h) {
      var b = data[i++], color, run;
      if (b !== 0) { color = b; run = 1; } else {
        var f = data[i++];
        if (f === 0) { x = 0; y++; continue; } // end of line
        var flag = f >> 6;
        if (flag === 0) { run = f & 0x3f; color = 0; }
        else if (flag === 1) { run = ((f & 0x3f) << 8) | data[i++]; color = 0; }
        else if (flag === 2) { run = f & 0x3f; color = data[i++]; }
        else { run = ((f & 0x3f) << 8) | data[i++]; color = data[i++]; }
      }
      var rgba = pal[color];
      var start = y * o.w + x;
      for (var k = 0; k < run && x < o.w; k++, x++) px[start + k] = rgba;
    }
    return px;
  }

  // ── Renderer ────────────────────────────────────────────────────

  function Renderer(textEl, canvas) {
    this.textEl = textEl;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.track = null;
    this.lastKey = null;
  }

  Renderer.prototype.setTrack = function (track) {
    this.track = track; // {format:'text', cues} | {format:'pgs', events} | null
    this.lastKey = null;
    this.textEl.innerHTML = '';
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  };

  Renderer.prototype.update = function (t) {
    var tr = this.track;
    if (!tr) return;
    if (tr.format === 'text') {
      var cues = activeCues(tr.cues, t + (tr.delay || 0)).filter(hasText);
      var key = cues.map(function (c) { return c.start; }).join(',');
      if (key === this.lastKey) return;
      this.lastKey = key;
      var bottom = cues.filter(function (c) { return !c.top; }), top = cues.filter(function (c) { return c.top; });
      this.textEl.innerHTML =
        (top.length ? '<div class="cue-group top">' + top.map(cueHtml).join('') + '</div>' : '') +
        '<div class="cue-group">' + bottom.map(cueHtml).join('') + '</div>';
    } else if (tr.format === 'pgs') {
      var ev = null, evs = tr.events;
      var lo = 0, hi = evs.length - 1;
      while (lo <= hi) { var mid = (lo + hi) >> 1; if (evs[mid].time <= t) { ev = evs[mid]; lo = mid + 1; } else hi = mid - 1; }
      if (ev === this.lastKey) return;
      this.lastKey = ev;
      var ctx = this.ctx;
      if (!ev || !ev.objects.length) { ctx.clearRect(0, 0, this.canvas.width, this.canvas.height); return; }
      if (this.canvas.width !== ev.width || this.canvas.height !== ev.height) {
        this.canvas.width = ev.width;
        this.canvas.height = ev.height;
      }
      ctx.clearRect(0, 0, ev.width, ev.height);
      ev.objects.forEach(function (o) {
        if (!o.image) {
          var img = ctx.createImageData(o.w, o.h);
          img.data.set(new Uint8ClampedArray(decodeObject(o).buffer));
          o.image = img;
        }
        ctx.putImageData(o.image, o.x, o.y);
      });
    }
  };

  function cueHtml(c) { return '<span class="cue">' + c.html + '</span>'; }

  /** A cue with no visible text (only tags, spaces or &nbsp;) would draw an empty subtitle box. */
  function hasText(c) {
    return !!(c.html || '').replace(/<[^>]*>/g, '').replace(/&nbsp;|&#160;|\u00a0/gi, '').trim();
  }

  /** Fetch a subtitle track from the server, waiting while it is still being extracted (HTTP 202). */
  function load(track, onWaiting) {
    var url = SM.api.abs(track.url);
    var attempts = 0;
    function attempt() {
      return fetch(url).then(function (res) {
        if (res.status === 202) {
          if (++attempts > 40) throw new Error('Subtitle extraction is taking too long');
          onWaiting && onWaiting();
          return new Promise(function (r) { setTimeout(r, 3000); }).then(attempt);
        }
        if (!res.ok) throw new Error('Subtitle HTTP ' + res.status);
        if (track.format === 'pgs') return res.arrayBuffer().then(function (buf) { return { format: 'pgs', events: parsePGS(buf) }; });
        return res.text().then(function (txt) { return { format: 'text', cues: parseVTT(txt) }; });
      });
    }
    return attempt();
  }

  SM.subtitles = { Renderer: Renderer, load: load, parseVTT: parseVTT, parsePGS: parsePGS, decodeObject: decodeObject };
})();
