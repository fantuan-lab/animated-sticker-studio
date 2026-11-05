"""Shared rendering core for the sticker pack scripts (Pillow only, no numpy)."""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from math import cos, exp, pi, radians, sin

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- fonts

FONT_CANDIDATES = [
    # (path or glob, preferred face index for a bold weight)
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
    ("/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 2),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
]


def _glyph(font, ch):
    im = Image.new("L", (64, 64))
    ImageDraw.Draw(im).text((8, 8), ch, font=font, fill=255)
    return im.tobytes()


def _missing_glyphs(font: ImageFont.FreeTypeFont, text: str) -> list[str]:
    tofu = {_glyph(font, "\uffff"), _glyph(font, "\U0010fffd")}
    out = []
    for ch in set(text):
        if ch.isspace():
            continue
        g = _glyph(font, ch)
        if g in tofu or not any(g):
            out.append(ch)
    return out


def find_font(texts: list[str], path: str | None = None, index: int | None = None):
    """Return (path, index) of a local font that renders every caption glyph."""
    joined = "".join(texts)
    tries = []
    if path:
        tries.append((path, index or 0))
    else:
        for pattern, idx in FONT_CANDIDATES:
            for p in sorted(glob.glob(pattern)):
                tries.append((p, idx))
    for p, idx in tries:
        try:
            f = ImageFont.truetype(p, 40, index=idx)
        except OSError:
            continue
        missing = _missing_glyphs(f, joined)
        if not missing:
            return p, idx
        if path:
            raise SystemExit(f"字体 {p} 缺字：{''.join(missing)}")
    raise SystemExit("没找到能显示全部文案的中文字体，请用 --font 指定一个 .ttf/.ttc/.otf")


# ---------------------------------------------------------------- motion
# Every motion is periodic in t∈[0,1) so the loop is seamless.
# Returns dx, dy (fraction of sprite height), sx, sy (scale), rot (degrees, + = clockwise),
# shear (fraction, top moves right by shear*height).

def _p(t, at, w):
    """Periodic gaussian bump centred at `at`."""
    d = min(abs(t - at), 1 - abs(t - at))
    return exp(-(d / w) ** 2)


def _hop(t, start, length):
    """Parabolic hop 0→1→0 between start and start+length (periodic)."""
    u = (t - start) % 1
    if u > length:
        return 0.0
    x = u / length
    return 4 * x * (1 - x)


@dataclass
class Pose:
    dx: float = 0.0
    dy: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rot: float = 0.0
    shear: float = 0.0


def motion(kind: str, t: float, amp: float = 1.0) -> Pose:
    w = sin(2 * pi * t)
    k = MOTIONS.get(kind)
    if k is None:
        raise ValueError(f"未知动作 {kind!r}，可用：{', '.join(MOTIONS)}")
    p = k(t, w)
    if amp != 1.0:
        p = Pose(p.dx * amp, p.dy * amp, 1 + (p.sx - 1) * amp, 1 + (p.sy - 1) * amp, p.rot * amp, p.shear * amp)
    return p


def _land(t, at):
    s = _p(t, at, 0.05)
    return 1 + 0.10 * s, 1 - 0.10 * s


def _m_jump(t, w):
    h = _hop(t, 0.18, 0.42)
    sx, sy = _land(t, 0.62)
    pre = _p(t, 0.13, 0.05)
    return Pose(dy=-0.16 * h, sx=sx + 0.06 * pre - 0.04 * h, sy=sy - 0.06 * pre + 0.05 * h)


def _m_hop2(t, w):
    h = _hop(t, 0.05, 0.3) + _hop(t, 0.45, 0.3)
    s = _p(t, 0.36, 0.04) + _p(t, 0.76, 0.04)
    return Pose(dy=-0.09 * h, sx=1 + 0.08 * s, sy=1 - 0.08 * s, rot=4 * sin(4 * pi * t))


def _m_nod(t, w):
    a = _p(t, 0.3, 0.09) + 0.6 * _p(t, 0.55, 0.08)
    return Pose(dy=0.025 * a, sx=1 + 0.04 * a, sy=1 - 0.05 * a, shear=0.05 * a)


def _m_shake_head(t, w):
    s = sin(6 * pi * t) * (0.5 + 0.5 * cos(2 * pi * t))
    return Pose(dx=0.025 * s, rot=-3 * s)


def _m_sway(t, w):
    return Pose(rot=6 * w, dx=0.012 * w, sy=1 + 0.012 * cos(4 * pi * t))


def _m_breathe(t, w):
    return Pose(sx=1 - 0.015 * w, sy=1 + 0.025 * w)


def _m_float(t, w):
    return Pose(dy=-0.05 - 0.04 * w, rot=2.5 * cos(2 * pi * t))


def _m_tremble(t, w):
    s = sin(16 * pi * t)
    c = cos(12 * pi * t)
    return Pose(dx=0.012 * s, dy=0.006 * c, rot=1.2 * c, sx=1 - 0.01 * s, sy=1 + 0.01 * s)


def _m_startle(t, w):
    h = _hop(t, 0.12, 0.26)
    after = _p(t, 0.45, 0.12)
    return Pose(dy=-0.12 * h, sx=1 - 0.06 * h + 0.03 * after, sy=1 + 0.10 * h - 0.04 * after,
                dx=0.01 * sin(20 * pi * t) * after)


def _m_pop(t, w):
    a = _p(t, 0.22, 0.07)
    b = _p(t, 0.34, 0.06)
    return Pose(sx=1 + 0.16 * a - 0.04 * b, sy=1 + 0.16 * a - 0.04 * b, dy=-0.02 * a)


def _m_heartbeat(t, w):
    a = _p(t, 0.18, 0.05) + 0.8 * _p(t, 0.34, 0.05)
    return Pose(sx=1 + 0.07 * a, sy=1 + 0.07 * a)


def _m_droop(t, w):
    a = 0.5 - 0.5 * cos(2 * pi * t)
    return Pose(dy=0.04 * a, sx=1 + 0.05 * a, sy=1 - 0.07 * a, rot=-2 * a)


def _m_lean(t, w):
    a = _p(t, 0.4, 0.2)
    return Pose(shear=0.12 * a, dx=0.03 * a, rot=2 * a)


def _m_bow(t, w):
    a = _p(t, 0.4, 0.15)
    return Pose(shear=0.18 * a, sy=1 - 0.10 * a, sx=1 + 0.03 * a)


def _m_rush(t, w):
    return Pose(dx=0.04 * sin(4 * pi * t), dy=-0.04 * abs(sin(4 * pi * t)), rot=6, shear=0.04)


def _m_dance(t, w):
    return Pose(rot=6 * w, dy=-0.05 * abs(sin(2 * pi * t)), sx=1 + 0.03 * cos(4 * pi * t),
                sy=1 - 0.03 * cos(4 * pi * t), dx=0.02 * w)


def _m_stomp(t, w):
    a = _p(t, 0.3, 0.05) + _p(t, 0.55, 0.05)
    lift = _hop(t, 0.18, 0.12) + _hop(t, 0.43, 0.12)
    return Pose(dy=-0.04 * lift, sx=1 + 0.10 * a, sy=1 - 0.10 * a, dx=0.01 * sin(30 * pi * t) * a)


def _m_wiggle(t, w):
    return Pose(sx=1 + 0.04 * sin(4 * pi * t), sy=1 - 0.04 * sin(4 * pi * t), rot=3 * w)


def _m_dizzy(t, w):
    return Pose(rot=7 * sin(2 * pi * t), dx=0.03 * cos(2 * pi * t), dy=0.015 * sin(4 * pi * t))


def _m_peek(t, w):
    a = 0.5 - 0.5 * cos(2 * pi * t)
    return Pose(dx=0.06 * (a - 0.5), rot=-5 * (a - 0.5), dy=0.02 * a)


def _m_slide(t, w):
    # glides in from the left, holds, glides out to the right
    if t < 0.25:
        x = -0.5 * (1 - t / 0.25) ** 2
    elif t < 0.8:
        x = 0.0
    else:
        x = 0.5 * ((t - 0.8) / 0.2) ** 2
    return Pose(dx=x, rot=-6 * x)


def _m_none(t, w):
    return Pose()


MOTIONS = {
    "none": _m_none, "breathe": _m_breathe, "float": _m_float, "nod": _m_nod, "shake_head": _m_shake_head,
    "sway": _m_sway, "jump": _m_jump, "hop2": _m_hop2, "startle": _m_startle, "pop": _m_pop,
    "heartbeat": _m_heartbeat, "tremble": _m_tremble, "droop": _m_droop, "lean": _m_lean, "bow": _m_bow,
    "rush": _m_rush, "dance": _m_dance, "stomp": _m_stomp, "wiggle": _m_wiggle, "dizzy": _m_dizzy,
    "peek": _m_peek, "slide": _m_slide,
}
# motions that leave the frame on purpose and skip the clipping check
OFFSTAGE = {"slide"}


def transform_sprite(sprite: Image.Image, pose: Pose, resample) -> tuple[Image.Image, tuple[float, float]]:
    """Apply scale/shear/rotation anchored at bottom-centre. Returns image and the new anchor position."""
    w, h = sprite.size
    pad = int(max(w, h) * 0.6) + 4
    big = Image.new("RGBA", (w + 2 * pad, h + 2 * pad))
    big.alpha_composite(sprite, (pad, pad))
    ax, ay = pad + w / 2, pad + h  # anchor (bottom centre)
    # forward matrix: translate(-a) -> scale -> shear -> rotate -> translate(+a)
    r = radians(pose.rot)
    cr, sr = cos(r), sin(r)
    # M = R * Sh * S
    a, b = pose.sx, pose.shear * -1 * pose.sy  # shear: x' = x - shear*y  (y up is negative)
    c, d = 0.0, pose.sy
    m00 = cr * a - sr * c
    m01 = cr * b - sr * d
    m10 = sr * a + cr * c
    m11 = sr * b + cr * d
    det = m00 * m11 - m01 * m10
    i00, i01, i10, i11 = m11 / det, -m01 / det, -m10 / det, m00 / det
    # inverse mapping for PIL: src = Minv*(dst - a) + a
    data = (i00, i01, ax - i00 * ax - i01 * ay, i10, i11, ay - i10 * ax - i11 * ay)
    out = big.transform(big.size, Image.Transform.AFFINE, data, resample=resample)
    return out, (ax, ay)


# ---------------------------------------------------------------- icons (vector, drawn at any scale)

def _star(d, cx, cy, r, fill, ink, ow):
    pts = []
    for i in range(8):
        rr = r if i % 2 == 0 else r * 0.32
        a = pi / 4 * i - pi / 2
        pts.append((cx + rr * cos(a), cy + rr * sin(a)))
    d.polygon(pts, fill=fill, outline=ink, width=ow)


def _heart(d, cx, cy, r, fill, ink, ow):
    pts = []
    for i in range(48):
        a = 2 * pi * i / 48
        x = 16 * sin(a) ** 3
        y = -(13 * cos(a) - 5 * cos(2 * a) - 2 * cos(3 * a) - cos(4 * a))
        pts.append((cx + x * r / 17, cy + y * r / 17))
    d.polygon(pts, fill=fill, outline=ink, width=ow)


def _drop(d, cx, cy, r, fill, ink, ow):
    pts = [(cx, cy - r * 1.2)]
    for i in range(25):
        a = pi * i / 24
        pts.append((cx + r * 0.7 * cos(a), cy + r * 0.25 + r * 0.7 * sin(a)))
    d.polygon(pts, fill=fill, outline=ink, width=ow)


def _anger(d, cx, cy, r, fill, ink, ow):
    """💢-style vein mark: four bracket arcs bowing toward the centre."""
    w = max(2, int(r * 0.28))
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        ox, oy = cx + sx * r * 0.62, cy + sy * r * 0.62
        q = r * 0.5
        box = (ox - q, oy - q, ox + q, oy + q)
        start = {(-1, -1): 0, (1, -1): 90, (1, 1): 180, (-1, 1): 270}[(sx, sy)]
        d.arc(box, start, start + 90, fill=ink, width=w + 2 * ow)
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        ox, oy = cx + sx * r * 0.62, cy + sy * r * 0.62
        q = r * 0.5
        box = (ox - q, oy - q, ox + q, oy + q)
        start = {(-1, -1): 0, (1, -1): 90, (1, 1): 180, (-1, 1): 270}[(sx, sy)]
        d.arc(box, start + 6, start + 84, fill=fill, width=w)


def _note(d, cx, cy, r, fill, ink, ow):
    """Eighth note drawn as shapes (fonts often lack ♪)."""
    hx, hy, q = cx - r * 0.25, cy + r * 0.45, r * 0.38
    stem_x = hx + q * 0.85
    w = max(2, int(r * 0.18))
    d.line([(stem_x, hy), (stem_x, cy - r * 0.8)], fill=ink, width=w + 2 * ow)
    d.polygon([(stem_x, cy - r * 0.8), (stem_x + r * 0.6, cy - r * 0.45), (stem_x + r * 0.55, cy - r * 0.2),
               (stem_x, cy - r * 0.5)], fill=fill, outline=ink, width=ow)
    d.ellipse((hx - q, hy - q * 0.75, hx + q, hy + q * 0.75), fill=fill, outline=ink, width=ow)
    d.line([(stem_x, hy), (stem_x, cy - r * 0.8)], fill=fill, width=w)


def _text_icon(ch):
    def draw(d, cx, cy, r, fill, ink, ow, _font_cache={}):
        size = max(8, int(r * 2.2))
        key = size
        font = _font_cache.get(key)
        if font is None:
            p, i = ICON_FONT
            font = ImageFont.truetype(p, size, index=i)
            _font_cache[key] = font
        d.text((cx, cy), ch, font=font, fill=fill, anchor="mm", stroke_width=max(1, ow), stroke_fill=ink)
    return draw


def _check(d, cx, cy, r, fill, ink, ow):
    pts = [(cx - r * 0.8, cy), (cx - r * 0.2, cy + r * 0.6), (cx + r * 0.9, cy - r * 0.7)]
    w = max(2, int(r * 0.35))
    d.line(pts, fill=ink, width=w + 2 * ow, joint="curve")
    d.line(pts, fill=fill, width=w, joint="curve")


def _cross(d, cx, cy, r, fill, ink, ow):
    w = max(2, int(r * 0.35))
    for a, b in (((cx - r * .7, cy - r * .7), (cx + r * .7, cy + r * .7)), ((cx + r * .7, cy - r * .7), (cx - r * .7, cy + r * .7))):
        d.line([a, b], fill=ink, width=w + 2 * ow)
    for a, b in (((cx - r * .7, cy - r * .7), (cx + r * .7, cy + r * .7)), ((cx + r * .7, cy - r * .7), (cx - r * .7, cy + r * .7))):
        d.line([a, b], fill=fill, width=w)


def _puff(d, cx, cy, r, fill, ink, ow):
    for ox, oy, rr in ((-0.45, 0.1, 0.5), (0.1, -0.25, 0.6), (0.5, 0.15, 0.45)):
        x, y, q = cx + ox * r, cy + oy * r, rr * r
        d.ellipse((x - q, y - q, x + q, y + q), fill=fill, outline=ink, width=ow)


def _swirl(d, cx, cy, r, fill, ink, ow):
    pts = []
    for i in range(60):
        a = i / 60 * 4 * pi
        rr = r * (0.15 + 0.85 * i / 60)
        pts.append((cx + rr * cos(a), cy + rr * sin(a) * 0.8))
    w = max(2, int(r * 0.2))
    d.line(pts, fill=ink, width=w + 2 * ow, joint="curve")
    d.line(pts, fill=fill, width=w, joint="curve")


def _bolt(d, cx, cy, r, fill, ink, ow):
    pts = [(cx + .2 * r, cy - r), (cx - .5 * r, cy + .1 * r), (cx, cy + .1 * r), (cx - .2 * r, cy + r),
           (cx + .5 * r, cy - .15 * r), (cx, cy - .15 * r)]
    d.polygon(pts, fill=fill, outline=ink, width=ow)


def _dots(d, cx, cy, r, fill, ink, ow):
    for i in (-1, 0, 1):
        x = cx + i * r * 0.75
        q = r * 0.24
        d.ellipse((x - q, cy - q, x + q, cy + q), fill=fill, outline=ink, width=ow)


def _lines(d, cx, cy, r, fill, ink, ow):
    w = max(2, int(r * 0.22))
    for i, a in enumerate((-30, 0, 30)):
        aa = radians(a - 90)
        p0 = (cx + r * 0.3 * cos(aa), cy + r * 0.3 * sin(aa))
        p1 = (cx + r * cos(aa), cy + r * sin(aa))
        d.line([p0, p1], fill=ink, width=w + 2 * ow)
        d.line([p0, p1], fill=fill, width=w)


def _flower(d, cx, cy, r, fill, ink, ow):
    for i in range(5):
        a = 2 * pi * i / 5 - pi / 2
        x, y, q = cx + r * .5 * cos(a), cy + r * .5 * sin(a), r * .42
        d.ellipse((x - q, y - q, x + q, y + q), fill=fill, outline=ink, width=ow)
    q = r * .3
    d.ellipse((cx - q, cy - q, cx + q, cy + q), fill=ink)


ICON_FONT = ("", 0)  # set by caller via set_icon_font()

ICONS = {
    "spark": _star, "heart": _heart, "tear": _drop, "sweat": _drop, "anger": _anger,
    "question": _text_icon("?"), "exclaim": _text_icon("!"), "zzz": _text_icon("z"), "note": _note,
    "check": _check, "cross": _cross, "steam": _puff, "swirl": _swirl, "bolt": _bolt, "dots": _dots,
    "lines": _lines, "flower": _flower,
}


def set_icon_font(path, index):
    global ICON_FONT
    ICON_FONT = (path, index)


def icon_track(icon: str, t: float, seed: int, box):
    """Yield (name, cx, cy, radius_fraction, alpha_scale) placements for one frame.
    box = (left, top, right, bottom) of the sprite in canvas units; radius in canvas units."""
    if icon in (None, "", "none"):
        return []
    L, T, R, B = box
    w, h = R - L, B - T
    side = 1 if seed % 2 else -1
    hx = (R + 0.02 * w) if side > 0 else (L - 0.02 * w)  # beside the head
    hy = T + 0.12 * h
    base = 0.11 * h
    out = []
    wv = sin(2 * pi * t)
    if icon in ("heart", "note", "flower", "zzz"):
        for j in range(3):
            ph = (t + j / 3) % 1
            grow = min(1, ph * 4) * (1 - max(0, ph - 0.75) * 4)
            out.append((icon, hx + side * (ph * 0.18 * w - 0.05 * w), hy - ph * 0.35 * h + 0.1 * h,
                        base * (0.6 + 0.5 * grow) * (1.1 if j == 0 else 0.85), grow))
    elif icon in ("tear",):
        for j in range(4):
            ph = (2 * t + j * 0.27) % 1
            sgn = 1 if j % 2 else -1
            out.append((icon, (L + R) / 2 + sgn * (0.22 * w + 0.12 * w * ph), T + 0.3 * h + ph * 0.25 * h,
                        base * 0.5, 1 - ph ** 3))
    elif icon == "sweat":
        ph = t
        out.append(("sweat", hx - side * 0.04 * w, hy + 0.04 * h + ph * 0.1 * h, base * 0.6, 1))
    elif icon == "spark":
        for j, (ox, oy) in enumerate(((0, 0), (0.1, 0.22), (-0.06, 0.4))):
            ph = (t * 2 + j * 0.33) % 1
            s = sin(pi * ph)
            out.append(("spark", hx + side * ox * w, hy + oy * h - 0.06 * h, base * (0.3 + 0.8 * s), 1))
            side = -side if j == 0 else side
            hx = (R + 0.02 * w) if side > 0 else (L - 0.02 * w)
    elif icon == "anger":
        a = 0.5 + 0.5 * abs(sin(4 * pi * t))
        out.append(("anger", hx, hy - 0.03 * h, base * (0.95 + 0.3 * a), 1))
    elif icon == "steam":
        for j in range(2):
            ph = (t + j * 0.5) % 1
            out.append(("steam", (L + R) / 2 + (j - 0.5) * 0.4 * w, T - 0.02 * h - ph * 0.15 * h,
                        base * (0.5 + 0.5 * ph), 1 - ph ** 2))
    elif icon == "swirl":
        out.append(("swirl", (L + R) / 2 + 0.02 * w * wv, T - 0.04 * h, base * 0.9, 1))
    elif icon == "lines":
        out.append(("lines", hx, hy - 0.06 * h, base * (0.8 + 0.25 * _p(t, 0.3, 0.1)), 1))
    elif icon == "dots":
        n = int(t * 4) % 4
        out.append(("dots", hx + side * 0.05 * w, hy - 0.02 * h, base * 1.1, 1 if n else 0.35))
    else:  # check, cross, question, exclaim, bolt: single bouncy badge
        hit = _p(t, 0.3, 0.12)
        out.append((icon, hx, hy - 0.06 * h - 0.05 * h * hit + 0.01 * h * wv, base * (0.9 + 0.35 * hit), 1))
    return out


def draw_icons(layer: Image.Image, placements, fill, ink, outline_w):
    if not placements:
        return
    d = ImageDraw.Draw(layer)
    W, H = layer.size
    m = W * 0.035
    for name, cx, cy, r, a in placements:
        if a <= 0.15 or r < 1:
            continue
        # keep every accent fully inside the canvas (plus room for the die-cut border)
        cx = min(max(cx, r * 1.2 + m), W - r * 1.2 - m)
        cy = min(max(cy, r * 1.3 + m), H * 0.72)
        ICONS[name](d, cx, cy, r, fill, ink, outline_w)


# ---------------------------------------------------------------- outline / caption

def die_cut(layer: Image.Image, radius: float, color, smooth: bool) -> Image.Image:
    """Put a sticker-style border behind every opaque pixel."""
    if radius <= 0:
        return layer
    alpha = layer.getchannel("A")
    if smooth:
        r = max(1, int(round(radius)))
        grown = alpha.filter(ImageFilter.MaxFilter(2 * (r // 2) + 1)) if r >= 2 else alpha
        if r >= 3:
            grown = grown.filter(ImageFilter.GaussianBlur(r / 2.2)).point(lambda v: 255 if v > 24 else int(v * 255 / 24))
            grown = ImageChops.lighter(grown, alpha.filter(ImageFilter.MaxFilter(2 * (r // 2) + 1)))
    else:
        r = max(1, int(round(radius)))
        grown = alpha.point(lambda v: 255 if v >= 128 else 0).filter(ImageFilter.MaxFilter(2 * r + 1))
    base = Image.new("RGBA", layer.size, color)
    base.putalpha(grown)
    base.alpha_composite(layer)
    return base


def fit_font(font_path, font_index, text, max_w, start):
    size = start
    while size > 10:
        f = ImageFont.truetype(font_path, size, index=font_index)
        if f.getlength(text) <= max_w:
            return f
        size -= 1
    return ImageFont.truetype(font_path, size, index=font_index)


def caption_layer(text, S, ink, font_path, font_index, fx, t, stroke_color="#FFFFFF", pos="bottom"):
    """Render the caption for time t. fx: static | pop | type | wave | shake."""
    layer = Image.new("RGBA", (S, S))
    if not text:
        return layer
    text = text.translate(str.maketrans({"！": "!", "？": "?", "～": "~"}))
    n = len(text)
    start = int(S * (0.14 if n <= 4 else 0.12 if n <= 6 else 0.10))
    font = fit_font(font_path, font_index, text, S * 0.88, start)
    cy = S * (0.885 if pos == "bottom" else 0.11)
    stroke = max(2, int(font.size * 0.14))
    d = ImageDraw.Draw(layer)
    if fx in ("static", "pop"):
        if fx == "pop":
            k = min(1.0, t / 0.18)
            scale = 0.5 + 0.5 * k + 0.12 * sin(pi * min(1, t / 0.28)) if t < 0.28 else 1.0
            f2 = ImageFont.truetype(font_path, max(8, int(font.size * scale)), index=font_index)
            d.text((S / 2, cy), text, font=f2, fill=ink, anchor="mm", stroke_width=stroke, stroke_fill=stroke_color)
        else:
            d.text((S / 2, cy), text, font=font, fill=ink, anchor="mm", stroke_width=stroke, stroke_fill=stroke_color)
        return layer
    # per-character effects
    widths = [font.getlength(c) for c in text]
    total = sum(widths)
    x = S / 2 - total / 2
    visible = n
    if fx == "type":
        visible = max(1, min(n, int(t / 0.5 * n) + 1))
    for i, (c, cw) in enumerate(zip(text, widths)):
        if i >= visible:
            break
        oy = ox = 0.0
        if fx == "wave":
            oy = -font.size * 0.12 * sin(2 * pi * (t - i / max(n, 1) * 0.5))
        elif fx == "shake":
            hit = _p(t, 0.3, 0.1)
            ox = font.size * 0.05 * sin(37 * t + i * 2.1) * hit
            oy = font.size * 0.05 * cos(29 * t + i * 1.7) * hit
        d.text((x + cw / 2 + ox, cy + oy), c, font=font, fill=ink, anchor="mm", stroke_width=stroke,
               stroke_fill=stroke_color)
        x += cw
    return layer


# ---------------------------------------------------------------- helpers

def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def dhash(img: Image.Image, size=12) -> int:
    g = img.convert("RGBA")
    bg = Image.new("RGBA", g.size, (255, 255, 255, 255))
    bg.alpha_composite(g)
    g = bg.convert("L").resize((size + 1, size), Image.Resampling.BILINEAR)
    px = list(g.getdata())
    bits = 0
    for y in range(size):
        for x in range(size):
            bits = (bits << 1) | (px[y * (size + 1) + x] > px[y * (size + 1) + x + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
