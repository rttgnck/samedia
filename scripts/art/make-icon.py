#!/usr/bin/env python3
"""Draws the Samedia icon, a Cover Flow, and writes every icon the apps use.

The geometry is the TV app's (tv/js/core/coverflow.js): 320×480 covers, perspective 1500, side
covers turned 64°, 250 px out then every 96 px, the centre cover 170 px forward, reflections
on a dark floor. Side covers carry geometric artwork and fade out towards the icon's edges.

    python3 scripts/art/make-icon.py              write all icons into the apps
    python3 scripts/art/make-icon.py preview.png  one 1024 px icon, to look at

Needs Pillow and numpy.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SS = 4                                  # supersampling
W, H = 320, 480                         # a cover (stage px)
PERSP = 1500.0
FIRST_GAP, STEP, ANGLE, CENTER_Z = 250, 96, 64, 170
FRONT = PERSP / (PERSP - CENTER_Z)      # how much bigger the centre cover looks

# side covers' palettes (background top, bottom, then shape colours), by side and depth
PALETTES = {
    (-1, 1): ((40, 58, 150), (18, 24, 70), (255, 196, 96), (92, 150, 255), (255, 255, 255)),
    (1, 1): ((70, 36, 140), (28, 16, 70), (255, 120, 170), (150, 110, 255), (255, 220, 120)),
    (-1, 2): ((16, 92, 108), (8, 36, 52), (80, 220, 200), (255, 150, 110), (240, 240, 230)),
    (1, 2): ((120, 30, 70), (50, 12, 36), (255, 170, 80), (255, 90, 120), (250, 220, 230)),
    (-1, 3): ((110, 60, 20), (48, 24, 10), (255, 210, 120), (230, 110, 60), (255, 240, 220)),
    (1, 3): ((18, 84, 64), (8, 34, 28), (120, 230, 170), (60, 160, 255), (230, 255, 240)),
}


def gradient(size, top, bottom, angle=0.0):
    w, h = size
    y = np.linspace(0, 1, h)[:, None]
    x = np.linspace(0, 1, w)[None, :]
    t = np.clip(y * math.cos(angle) + x * math.sin(angle), 0, 1)
    rgb = np.array(top)[None, None, :] * (1 - t[..., None]) + np.array(bottom)[None, None, :] * t[..., None]
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


# ── cover artwork ──

def art_rings(d, w, h, p):
    cx, cy = w * 0.5, h * 0.38
    for i, r in enumerate(np.linspace(0.46, 0.08, 7)):
        d.ellipse([cx - w * r, cy - w * r, cx + w * r, cy + w * r], fill=p[2 + i % 3] + (255,))


def art_sun(d, w, h, p):
    d.ellipse([w * 0.28, h * 0.14, w * 0.78, h * 0.47], fill=p[2] + (255,))
    d.polygon([(-w * 0.1, h * 0.78), (w * 0.38, h * 0.36), (w * 0.86, h * 0.78)], fill=p[3] + (255,))
    d.polygon([(w * 0.3, h * 0.78), (w * 0.74, h * 0.46), (w * 1.15, h * 0.78)], fill=p[4] + (220,))
    d.rectangle([0, h * 0.78, w, h], fill=p[3] + (255,))


def art_bauhaus(d, w, h, p):
    s = w / 2
    d.pieslice([-s, -s, s, s], 0, 90, fill=p[2] + (255,))
    d.rectangle([s, 0, w, s], fill=p[3] + (255,))
    d.ellipse([s * 0.15, s * 1.15, s * 0.85, s * 1.85], fill=p[4] + (255,))
    d.pieslice([s, s, s * 3, s * 3], 180, 270, fill=p[2] + (255,))
    d.polygon([(0, h), (s, s * 2.2), (s * 2, h)], fill=p[3] + (255,))


def art_stripes(d, w, h, p):
    for i in range(-6, 12):
        x = i * w * 0.2
        d.polygon([(x, h), (x + w * 0.1, h), (x + w * 0.1 + h * 0.6, 0), (x + h * 0.6, 0)],
                  fill=p[2 + i % 3] + (255,))


def art_waves(d, w, h, p):
    for i in range(6):
        base = h * (0.25 + i * 0.13)
        pts = [(x, base + math.sin(x / w * math.pi * 2 + i) * h * 0.04) for x in np.linspace(0, w, 40)]
        d.polygon(pts + [(w, h), (0, h)], fill=p[2 + i % 3] + (235,))


def art_triangles(d, w, h, p):
    d.polygon([(w * 0.5, h * 0.08), (w * 1.05, h * 0.9), (-w * 0.05, h * 0.9)], fill=p[2] + (230,))
    d.polygon([(w * 0.5, h * 0.9), (w * 0.95, h * 0.32), (w * 0.05, h * 0.32)], fill=p[3] + (200,))
    d.polygon([(w * 0.5, h * 0.36), (w * 0.72, h * 0.66), (w * 0.28, h * 0.66)], fill=p[4] + (255,))


DESIGNS = {(-1, 1): art_sun, (1, 1): art_rings, (-1, 2): art_bauhaus, (1, 2): art_waves,
           (-1, 3): art_stripes, (1, 3): art_triangles}


def centre_art(k):
    """The front cover: the brand's coral card with a play triangle and a gloss stripe."""
    w, h = W * k, H * k
    art = gradient((w, h), (255, 150, 140), (255, 138, 92), angle=0.5).convert("RGBA")
    gloss = Image.new("L", (w, h), 0)
    ImageDraw.Draw(gloss).polygon([(0, 0), (w * 0.62, 0), (0, h * 0.62)], fill=38)
    art = Image.composite(Image.new("RGBA", (w, h), (255, 255, 255, 255)), art, gloss)
    tri = h * 0.24
    cx, cy = w * 0.53, h * 0.5
    ImageDraw.Draw(art).polygon([(cx - tri * 0.42, cy - tri / 2), (cx - tri * 0.42, cy + tri / 2), (cx + tri * 0.5, cy)],
                                fill=(255, 255, 255, 255))
    art.putalpha(rounded_mask((w, h), 26 * k))
    return art


def side_art(k, side, depth):
    """A side cover: geometric artwork, dimmed with depth and darker towards the edge that turns
    away (as in Cover Flow)."""
    w, h = W * k, H * k
    p = PALETTES[(side, depth)]
    art = gradient((w, h), p[0], p[1], angle=0.3).convert("RGBA")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    DESIGNS[(side, depth)](ImageDraw.Draw(layer, "RGBA"), w, h, p)
    art = Image.alpha_composite(art, layer)
    x = np.linspace(0, 1, w)
    turn = (1 - x) if side > 0 else x                 # the far edge
    shade = 0.92 - 0.14 * (depth - 1)
    dark = (255 * (1 - shade * (1 - 0.5 * turn ** 1.4))).clip(0, 255).astype(np.uint8)
    art = Image.alpha_composite(art, Image.merge("RGBA", [Image.new("L", (w, h), 0)] * 3 +
                                                  [Image.fromarray(np.repeat(dark[None, :], h, 0))]))
    art.putalpha(rounded_mask((w, h), 22 * k))
    return art


# ── 3D ──

def coeffs(dst, src):
    """PIL perspective coefficients mapping destination points to source points."""
    rows = []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return np.linalg.solve(np.array(rows, float), np.array([c for p in src for c in p], float)).tolist()


class Stage:
    """Where the Cover Flow lands in an n×n picture: `scale` icon px per stage px, the centre
    cover's middle at (cx, cy)."""

    def __init__(self, n, scale, cx, cy):
        self.n, self.scale, self.cx, self.cy = n, scale, cx, cy

    def project(self, tx, tz, theta, x, y):
        t = math.radians(theta)
        X, Z = tx + x * math.cos(t), tz - x * math.sin(t)
        f = PERSP / (PERSP - Z)
        return self.cx + X * f * self.scale, self.cy + y * f * self.scale

    def place(self, canvas, art, corners):
        w, h = art.size
        warped = art.transform(canvas.size, Image.PERSPECTIVE, coeffs(corners, [(0, 0), (w, 0), (w, h), (0, h)]),
                               Image.BICUBIC)
        canvas.alpha_composite(warped)

    def cover(self, canvas, art, tx, tz, theta):
        quad = lambda y0, y1: [self.project(tx, tz, theta, x, y) for x, y in
                               ((-W / 2, y0), (W / 2, y0), (W / 2, y1), (-W / 2, y1))]
        flipped = art.transpose(Image.FLIP_TOP_BOTTOM)
        fade = np.clip(0.24 * (1 - np.linspace(0, 1, flipped.size[1]) / 0.38), 0, 1)
        flipped.putalpha(Image.fromarray((np.array(flipped.getchannel("A"), float) * fade[:, None]).astype(np.uint8)))
        self.place(canvas, flipped, quad(H / 2 + 6, H * 1.5 + 6))
        self.place(canvas, art, quad(-H / 2, H / 2))


def background(n):
    bg = gradient((n, n), (16, 20, 38), (6, 7, 12)).convert("RGBA")
    glow = Image.new("L", (n, n), 0)
    ImageDraw.Draw(glow).ellipse([n * 0.18, n * 0.02, n * 0.82, n * 0.62], fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(n * 0.09))
    return Image.composite(Image.new("RGBA", (n, n), (70, 92, 220, 255)), bg, glow.point(lambda v: v * 0.55))


def covers(n, cover_h, cy, fade_from=0.42, fade_to=0.95):
    """The Cover Flow on a transparent n×n layer: the centre cover cover_h px tall (of n),
    its middle at cy (fraction of n); side covers fade out from fade_from to fade_to of the way
    to the left/right edge."""
    k = SS
    stage = Stage(n, cover_h * n / (H * FRONT), n / 2, cy * n)
    sides = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    for a in (3, 2, 1):
        for s in (-1, 1):
            stage.cover(sides, side_art(k, s, a), s * (FIRST_GAP + (a - 1) * STEP), 0, -s * ANGLE)
    dist = np.abs(np.linspace(-1, 1, n))
    t = np.clip((dist - fade_from) / (fade_to - fade_from), 0, 1)
    keep = 1 - t * t * (3 - 2 * t)                        # smoothstep
    alpha = np.array(sides.getchannel("A"), float) * keep[None, :]
    sides.putalpha(Image.fromarray(alpha.astype(np.uint8)))
    layer = sides
    # a soft shadow under the centre cover, then the cover
    l, t0 = stage.project(0, CENTER_Z, 0, -W / 2, -H / 2)
    r, b = stage.project(0, CENTER_Z, 0, W / 2, H / 2)
    shadow = Image.new("L", (n, n), 0)
    off = 0.03 * n
    ImageDraw.Draw(shadow).rounded_rectangle([l, t0 + off, r, b + off], radius=0.04 * n, fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(0.028 * n))
    layer = Image.alpha_composite(layer, Image.merge("RGBA", [Image.new("L", (n, n), 0)] * 3 + [shadow]))
    stage.cover(layer, centre_art(k), 0, CENTER_Z, 0)
    return layer


def icon(size, cover_h=0.5, cy=0.47):
    """The full, square icon (iOS, Samsung TV, in-app logo): the centre cover half the height."""
    n = 1024 * SS
    pic = Image.alpha_composite(background(n), covers(n, cover_h, cy))
    return pic.convert("RGB").resize((size, size), Image.LANCZOS)


def adaptive(size):
    """Android adaptive icon layers (108 dp, of which the launcher shows the middle 72 dp, often
    as a circle): the same picture, sized to that circle and centred in it."""
    n = 1024 * SS
    visible = 72 / 108
    fg = covers(n, 0.5 * visible * 0.92, 0.5 - 0.03 * visible, fade_from=0.42 * visible, fade_to=0.95 * visible)
    return (background(n).convert("RGB").resize((size, size), Image.LANCZOS),
            fg.resize((size, size), Image.LANCZOS))


def banner(w, h, art):
    """Google TV's launcher banner: the icon and the name."""
    img = Image.new("RGB", (w, h), (8, 10, 18))
    img.paste(gradient((w, h), (16, 20, 38), (6, 7, 12)), (0, 0))
    s = int(h * 0.78)
    pic = art.resize((s, s), Image.LANCZOS)
    m = rounded_mask((s, s), int(s * 0.2))
    x0 = int(h * 0.11)
    img.paste(pic, (x0, (h - s) // 2), m)
    d = ImageDraw.Draw(img)
    font = None
    for f in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(f):
            font = ImageFont.truetype(f, int(h * 0.27))
            break
    text_x = x0 + s + int(h * 0.12)
    while font and d.textlength("Samedia", font=font) > w - text_x - h * 0.1:
        font = ImageFont.truetype(font.path, font.size - 2)
    d.text((text_x, h / 2), "Samedia", font=font, fill=(242, 244, 248), anchor="lm")
    return img


def write_all():
    out = lambda p: os.path.join(ROOT, p)
    full = icon(1024)
    full.save(out("ios/Samedia/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png"))
    full.resize((512, 512), Image.LANCZOS).save(out("ios/Samedia/Assets.xcassets/Logo.imageset/logo.png"))
    full.resize((512, 512), Image.LANCZOS).save(out("tv/icon.png"))
    res = "android/app/src/main/res"
    full.resize((512, 512), Image.LANCZOS).save(out(f"{res}/drawable-nodpi/logo.png"))
    bg, fg = adaptive(432)
    for name, dp in (("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)):
        layer = int(108 * dp)
        bg.resize((layer, layer), Image.LANCZOS).save(out(f"{res}/mipmap-{name}/ic_launcher_background.png"))
        fg.resize((layer, layer), Image.LANCZOS).save(out(f"{res}/mipmap-{name}/ic_launcher_foreground.png"))
        legacy = int(48 * dp)
        rounded = full.resize((legacy, legacy), Image.LANCZOS).convert("RGBA")
        rounded.putalpha(rounded_mask((legacy, legacy), int(legacy * 0.18)))
        rounded.save(out(f"{res}/mipmap-{name}/ic_launcher.png"))
    banner(320, 180, full).save(out(f"{res}/drawable-xhdpi/banner.png"))
    banner(640, 360, full).save(out(f"{res}/drawable-xxhdpi/banner.png"))
    print("icons written")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        icon(1024).save(sys.argv[1])
    else:
        write_all()
