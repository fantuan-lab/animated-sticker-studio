#!/usr/bin/env python3
"""Render a sticker manifest into platform-ready animated stickers, verify them, and package a ZIP.

  python3 build_pack.py manifest.json out/ --platform wechat,telegram --mp4

Outputs (inside out/):
  <platform>/NNN-文案.<ext>     one file per sticker, sized and compressed for that platform
  <platform>/_extras/           thumbnails, icons, tab images the platform asks for
  review/motion-XX.png          4 frames per sticker side by side, so an agent can SEE the motion
  review/contact.png            one still per sticker with number + caption
  预览.html                     offline gallery: light/dark/checker backgrounds + chat mock-up
  report.json                   every check, every file size, pass/fail per platform
  <title>-<N>张.zip            everything a user needs, sources excluded
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageSequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sticker_core as core  # noqa: E402

NEAREST = Image.Resampling.NEAREST
LANCZOS = Image.Resampling.LANCZOS
BICUBIC = Image.Resampling.BICUBIC

# ------------------------------------------------------------------ platforms
# Public specs as of 2026-11. Each platform's console is the final authority.
PLATFORMS = {
    "generic":  dict(label="通用 GIF（微信/QQ/飞书/钉钉直接发）", fmt="gif", size=(320, 320), frames=24, delay=80,
                     loop=0, budget=1000_000, hard=False),
    "wechat":   dict(label="微信表情开放平台", fmt="gif", size=(240, 240), frames=24, delay=80, loop=0,
                     budget=500_000, hard=True, counts=list(range(8, 25))),
    "telegram": dict(label="Telegram 视频贴纸", fmt="webm", size=(512, 512), frames=24, delay=80, loop=0,
                     budget=256_000, hard=True, max_seconds=3.0),
    "line":     dict(label="LINE 动态贴图", fmt="apng", size=(320, 270), frames=12, delay=160, loop=2,
                     budget=300_000, hard=True, counts=[8, 16, 24], max_frames=20, max_seconds=4.0),
    "discord":  dict(label="Discord 贴纸", fmt="apng", size=(320, 320), frames=24, delay=80, loop=0,
                     budget=512_000, hard=True),
    "slack":    dict(label="Slack 自定义表情", fmt="gif", size=(128, 128), frames=12, delay=160, loop=0,
                     budget=128_000, hard=True),
    "whatsapp": dict(label="WhatsApp 动态贴纸", fmt="webp", size=(512, 512), frames=24, delay=80, loop=0,
                     budget=500_000, hard=True),
}
EXT = {"gif": "gif", "apng": "png", "webm": "webm", "webp": "webp"}
CAPTION_FX = {"static", "pop", "type", "wave", "shake"}


def clean_name(text):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f\s]', "_", text).strip("_") or "sticker"


# ------------------------------------------------------------------ manifest

@dataclass
class Entry:
    number: int
    group: str
    group_index: int
    text: str
    motion: str
    icon: str
    sprites: list
    timing: list
    caption_fx: str
    amp: float
    style: str
    ink: str
    accent: str
    outline: str
    caption_pos: str
    font: tuple
    stem: str = ""


def load_manifest(path: Path, font_arg, font_index):
    m = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    style = m.get("style", "smooth")
    if style not in ("smooth", "pixel"):
        raise SystemExit("style 只能是 smooth 或 pixel")
    pal = m.get("palette", {})
    cap = m.get("caption", {})
    entries, problems, texts = [], [], []
    for gi, g in enumerate(m["groups"], 1):
        for e in g["entries"]:
            texts.append(e.get("text", ""))
    font = core.find_font([t for t in texts if t], font_arg, font_index)
    core.set_icon_font(*font)
    seen = {}
    for gi, g in enumerate(m["groups"], 1):
        for e in g["entries"]:
            n = len(entries) + 1
            text = e.get("text", "").strip()
            if text:
                if text in seen:
                    problems.append(f"#{n} 文案「{text}」和 #{seen[text]} 重复")
                seen[text] = n
            sprites = e.get("sprites") or []
            if isinstance(sprites, str):
                sprites = [sprites]
            if not sprites:
                problems.append(f"#{n}「{text}」没有 sprites（先跑 cut_atlas.py）")
                continue
            paths = []
            for s in sprites:
                p = (base / s).resolve()
                if not p.exists():
                    problems.append(f"#{n} 找不到 {s}")
                paths.append(str(p))
            motion = e.get("motion", "breathe")
            if motion not in core.MOTIONS:
                problems.append(f"#{n} 未知动作 {motion}")
            icon = e.get("icon", "none")
            if icon not in core.ICONS and icon != "none":
                problems.append(f"#{n} 未知小特效 {icon}")
            fx = e.get("caption_fx", cap.get("fx", "pop"))
            if fx not in CAPTION_FX:
                problems.append(f"#{n} 未知文字动效 {fx}")
            timing = e.get("timing") or [1] * len(paths)
            if len(timing) != len(paths):
                problems.append(f"#{n} timing 数量要和 sprites 一样")
            entries.append(Entry(n, g["name"], gi, text, motion, icon, paths, timing, fx, float(e.get("amp", 1.0)),
                                 style, g.get("ink", pal.get("ink", "#3B2A5A")),
                                 g.get("accent", pal.get("accent", "#FF7AA8")),
                                 pal.get("outline", "#FFFFFF"), cap.get("pos", "bottom"), font))
    if problems:
        raise SystemExit("清单有问题：\n  " + "\n  ".join(problems))
    count = m.get("count")
    if count is not None and count != len(entries):
        raise SystemExit(f"count 写的是 {count}，实际有 {len(entries)} 条")
    for e in entries:
        e.stem = f"{e.number:03d}-{clean_name(e.text) if e.text else 'sticker'}"
    return m, entries


# ------------------------------------------------------------------ rendering

def body_anchor(sprite: Image.Image) -> float:
    """x of the body's centre of mass in the bottom 35% (keeps keyframes from sliding sideways)."""
    w, h = sprite.size
    band = sprite.getchannel("A").crop((0, int(h * 0.65), w, h))
    cols = list(band.resize((w, 1), Image.Resampling.BOX).getdata())
    total = sum(cols)
    if not total:
        return w / 2
    return sum(i * v for i, v in enumerate(cols)) / total + 0.5


def load_keys(entry: Entry, box_w: float, box_h: float, pixel: bool):
    raw = []
    for p in entry.sprites:
        im = Image.open(p).convert("RGBA")
        a = im.getchannel("A")
        if pixel:
            a = a.point(lambda v: 255 if v >= 128 else 0)
            im.putalpha(a)
        bb = a.getbbox()
        if bb is None:
            raise SystemExit(f"#{entry.number} {p} 是空图")
        raw.append(im.crop(bb))
    mw = max(i.width for i in raw)
    mh = max(i.height for i in raw)
    k = min(box_w / mw, box_h / mh)
    keys = []
    for im in raw:
        size = (max(1, round(im.width * k)), max(1, round(im.height * k)))
        s = im.resize(size, NEAREST if pixel else LANCZOS)
        keys.append((s, body_anchor(s)))
    return keys


def key_at(timing, t):
    total = sum(timing)
    acc = 0
    for i, w in enumerate(timing):
        acc += w / total
        if t < acc - 1e-9:
            return i
    return len(timing) - 1


def render_frames(entry: Entry, S: int, n_frames: int, shrink: float = 1.0):
    core.set_icon_font(*entry.font)  # worker processes start fresh
    pixel = entry.style == "pixel"
    caption = bool(entry.text)
    if pixel:
        scale = max(2, round(S / 150))
        G = S // scale
    else:
        scale = 2
        G = S * 2  # supersample
    box_w = G * (0.78 if caption else 0.84) * shrink
    box_h = G * (0.62 if caption else 0.78) * shrink
    base_y = G * (0.76 if caption else 0.91)
    keys = load_keys(entry, box_w, box_h, pixel)
    outline_r = (1.6 if pixel else G * 0.013)
    resample = NEAREST if pixel else BICUBIC
    ink = core.hex_rgb(entry.ink)
    accent = core.hex_rgb(entry.accent)
    frames = []
    for k in range(n_frames):
        t = k / n_frames
        sprite, ax_local = keys[key_at(entry.timing, t)]
        pose = core.motion(entry.motion, t, entry.amp)
        h = sprite.height
        moved, (ax, ay) = core.transform_sprite(sprite, pose, resample)
        # sprite's anchor inside `moved` is at (pad + ax_local, pad + h) — transform anchored bottom-centre,
        # so shift by the body-centre offset to keep feet planted between keyframes.
        pad_x = ax - sprite.width / 2
        anchor_x = pad_x + ax_local
        cx = G / 2 + pose.dx * h
        cy = base_y + pose.dy * h
        layer = Image.new("RGBA", (G, G))
        layer.alpha_composite(moved, (round(cx - anchor_x), round(cy - ay)))
        left = cx - ax_local
        box = (left, cy - h, left + sprite.width, cy)
        ow = max(1, round(G / 160)) if not pixel else 1
        core.draw_icons(layer, core.icon_track(entry.icon, t, entry.number, box), accent, ink, ow)
        if pixel:
            layer.putalpha(layer.getchannel("A").point(lambda v: 255 if v >= 128 else 0))
        layer = core.die_cut(layer, outline_r, entry.outline, smooth=not pixel)
        if pixel:
            layer = layer.resize((S, S), NEAREST)
        else:
            layer = layer.resize((S, S), LANCZOS)
        cap = core.caption_layer(entry.text, S, ink, entry.font[0], entry.font[1], entry.caption_fx, t,
                                 entry.outline, entry.caption_pos)
        layer.alpha_composite(cap)
        frames.append(layer)
    return frames


def touches_edge(frames, margin):
    for f in frames:
        bb = f.getchannel("A").point(lambda v: 255 if v >= 128 else 0).getbbox()
        if bb and (bb[0] < margin or bb[1] < margin or bb[2] > f.width - margin or bb[3] > f.height - margin):
            return True
    return False


def render_fitted(entry: Entry, S: int, n_frames: int):
    """Render; if a big jump or accent leaves the canvas, shrink this sticker a little and try again."""
    shrink = 1.0
    frames = render_frames(entry, S, n_frames, shrink)
    if entry.motion in core.OFFSTAGE:
        return frames
    margin = max(2, S // 80)
    while touches_edge(frames, margin) and shrink > 0.7:
        shrink *= 0.92
        frames = render_frames(entry, S, n_frames, shrink)
    return frames


def fit_canvas(frames, size):
    """Square renders → platform canvas (e.g. LINE 320×270): scale to height, centre horizontally."""
    W, H = size
    if W == H:
        return frames
    s = min(W, H)
    out = []
    for f in frames:
        f2 = f.resize((s, s), LANCZOS) if f.width != s else f
        c = Image.new("RGBA", (W, H))
        c.alpha_composite(f2, ((W - s) // 2, (H - s) // 2))
        out.append(c)
    return out


# ------------------------------------------------------------------ encoders

def hard_alpha(im):
    a = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    out = im.copy()
    out.putalpha(a)
    return out


def encode_gif(frames, delay, loop, colors):
    W, H = frames[0].size
    cols = min(len(frames), 6)
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (W * cols, H * rows), (255, 255, 255))
    for j, f in enumerate(frames):
        sheet.paste(f.convert("RGB"), (W * (j % cols), H * (j // cols)), f.getchannel("A"))
    palette = sheet.quantize(colors=colors - 1, method=Image.Quantize.MEDIANCUT)
    out = []
    for f in frames:
        a = f.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        rgb = Image.new("RGB", f.size, (255, 255, 255))
        rgb.paste(f.convert("RGB"), (0, 0), a)
        q = rgb.quantize(palette=palette, dither=Image.Dither.NONE)
        q.paste(colors - 1, mask=ImageChops.invert(a))
        out.append(q)
    buf = io.BytesIO()
    out[0].save(buf, "GIF", save_all=True, append_images=out[1:], duration=delay, loop=loop, disposal=2,
                transparency=colors - 1, optimize=False)
    return buf.getvalue()


def encode_apng(frames, delay, loop, colors):
    fr = [f.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).convert("RGBA")
          for f in frames]
    buf = io.BytesIO()
    fr[0].save(buf, "PNG", save_all=True, append_images=fr[1:], duration=delay, loop=loop, disposal=1, blend=0,
               optimize=True)
    return buf.getvalue()


def encode_webp(frames, delay, loop, quality):
    buf = io.BytesIO()
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=delay, loop=loop,
                   quality=quality, method=6, lossless=False, alpha_quality=90)
    return buf.getvalue()


def encode_webm(frames, delay, crf, tmpdir: Path):
    tmpdir.mkdir(parents=True, exist_ok=True)
    out = tmpdir / "o.webm"
    W, H = frames[0].size
    fps = f"{1000}/{delay}"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-framerate", fps,
           "-i", "pipe:0", "-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", str(crf), "-b:v", "0",
           "-deadline", "good", "-auto-alt-ref", "0", str(out)]
    p = subprocess.run(cmd, input=b"".join(f.tobytes() for f in frames), capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode()[-400:])
    data = out.read_bytes()
    out.unlink()
    return data


def encode_with_budget(fmt, frames, spec, tmpdir):
    """Try progressively cheaper settings until the file fits the platform budget."""
    delay, loop, budget = spec["delay"], spec["loop"], spec["budget"]
    attempts = []
    if fmt == "gif":
        attempts = [("colors", c, frames, delay) for c in (256, 160, 96, 64)]
        half = frames[::2]
        attempts += [("colors+half", c, half, delay * 2) for c in (128, 64)]
    elif fmt == "apng":
        attempts = [("colors", c, frames, delay) for c in (256, 128, 64, 32)]
        attempts += [("colors+half", c, frames[::2], delay * 2) for c in (64, 32)]
    elif fmt == "webp":
        attempts = [("quality", q, frames, delay) for q in (85, 72, 60, 45, 30)]
    elif fmt == "webm":
        attempts = [("crf", c, frames, delay) for c in (30, 36, 42, 48, 54, 60)]
    last = None
    for label, val, fr, d in attempts:
        if fmt == "gif":
            data = encode_gif(fr, d, loop, val)
        elif fmt == "apng":
            data = encode_apng(fr, d, loop, val)
        elif fmt == "webp":
            data = encode_webp(fr, d, loop, val)
        else:
            data = encode_webm(fr, d, val, tmpdir)
        last = (data, f"{label}={val}")
        if len(data) <= budget:
            return data, last[1], True
    return last[0], last[1], False


# ------------------------------------------------------------------ verification

def decode(path: Path):
    """Decode any output back to RGBA frames + durations, the way a player would."""
    if path.suffix == ".webm":
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                               capture_output=True, text=True)
        info = json.loads(probe.stdout or "{}")
        st = info["streams"][0]
        W, H = st["width"], st["height"]
        p = subprocess.run(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", str(path), "-f", "rawvideo",
                            "-pix_fmt", "rgba", "pipe:1"], capture_output=True)
        raw = p.stdout
        n = len(raw) // (W * H * 4)
        frames = [Image.frombytes("RGBA", (W, H), raw[i * W * H * 4:(i + 1) * W * H * 4]) for i in range(n)]
        dur = float(info["format"]["duration"]) * 1000
        return frames, [dur / max(n, 1)] * n, 0
    with Image.open(path) as im:
        loop = im.info.get("loop")
        frames, durs = [], []
        for f in ImageSequence.Iterator(im):
            frames.append(f.convert("RGBA"))
            durs.append(f.info.get("duration", 0))
    return frames, durs, loop


def check_file(path: Path, spec, offstage: bool):
    frames, durs, loop = decode(path)
    W, H = spec["size"]
    issues = []
    size = path.stat().st_size
    if frames and frames[0].size != (W, H):
        issues.append(f"尺寸 {frames[0].size} ≠ {W}×{H}")
    if size > spec["budget"]:
        issues.append(f"体积 {size // 1000}KB 超过 {spec['budget'] // 1000}KB")
    if spec["fmt"] != "webm" and loop != spec["loop"]:
        issues.append(f"循环次数 {loop} ≠ {spec['loop']}")
    total = sum(durs)
    if spec.get("max_seconds") and total * (spec["loop"] or 1) / 1000 > spec["max_seconds"] + 0.05:
        issues.append(f"播放时长 {total / 1000:.2f}s×{spec['loop'] or 1} 超过 {spec['max_seconds']}s")
    if spec.get("max_frames") and len(frames) > spec["max_frames"]:
        issues.append(f"{len(frames)} 帧超过 {spec['max_frames']}")
    hashes = {hashlib.sha1(f.tobytes()).digest() for f in frames}
    if len(hashes) < 4:
        issues.append(f"只有 {len(hashes)} 个不同画面，几乎不动")
    a0 = frames[0].getchannel("A")
    lo, hi = a0.getextrema()
    if lo > 0:
        issues.append("没有透明背景")
    if not offstage:
        for f in frames:
            bb = f.getchannel("A").point(lambda v: 255 if v >= 128 else 0).getbbox()
            if bb and (bb[0] <= 0 or bb[1] <= 0 or bb[2] >= W or bb[3] >= H):
                issues.append("内容碰到画布边缘（可能被裁）")
                break
    # motion energy: mean absolute difference between consecutive frames
    energy = 0.0
    for a, b in zip(frames, frames[1:] + frames[:1]):
        d = ImageChops.difference(a.convert("L"), b.convert("L")).resize((32, 32), Image.Resampling.BOX)
        energy += sum(d.getdata()) / (32 * 32)
    energy /= max(len(frames), 1)
    return dict(file=path.name, bytes=size, frames=len(frames), ms=round(total), loop=loop,
                unique_frames=len(hashes), motion=round(energy, 2), ok=not issues, issues=issues)


# ------------------------------------------------------------------ per-sticker job

@dataclass
class Job:
    entry: Entry
    platforms: list
    out: str


def build_one(job: Job):
    e = job.entry
    out = Path(job.out)
    results = {}
    cache = {}
    for name in job.platforms:
        spec = PLATFORMS[name]
        W, H = spec["size"]
        S = min(W, H)
        key = (S, spec["frames"])
        if key not in cache:
            cache[key] = render_fitted(e, S, spec["frames"])
        frames = fit_canvas(cache[key], (W, H))
        if spec["fmt"] == "gif":
            frames = [hard_alpha(f) for f in frames]
        data, setting, fits = encode_with_budget(spec["fmt"], frames, spec, out / "_tmp" / f"{e.number}-{name}")
        path = out / name / f"{e.stem}.{EXT[spec['fmt']]}"
        path.write_bytes(data)
        r = check_file(path, spec, e.motion in core.OFFSTAGE)
        r["setting"] = setting
        results[name] = r
    # review material at the largest square render we made
    big = max(cache, key=lambda k: k[0])
    frames = cache[big]
    n = len(frames)
    picks = [frames[int(n * f)] for f in (0.0, 0.25, 0.5, 0.75)]
    still = frames[int(n * 0.3)]
    sprite_hash = core.dhash(Image.open(e.sprites[0]))
    rev = out / "_tmp" / "review"
    rev.mkdir(parents=True, exist_ok=True)
    strip = Image.new("RGBA", (picks[0].width * 4, picks[0].height))
    for i, p in enumerate(picks):
        strip.alpha_composite(p, (i * p.width, 0))
    strip.save(rev / f"{e.number:03d}-strip.png")
    still.save(rev / f"{e.number:03d}-still.png")
    return e.number, results, sprite_hash


# ------------------------------------------------------------------ sheets, extras, gallery

def checker(size, cell=12):
    W, H = size
    im = Image.new("RGB", size, (236, 236, 236))
    d = ImageDraw.Draw(im)
    for y in range(0, H, cell):
        for x in range(0, W, cell):
            if (x // cell + y // cell) % 2:
                d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(206, 206, 206))
    return im


def review_sheets(entries, out: Path, font):
    rev = out / "review"
    rev.mkdir(exist_ok=True)
    tmp = out / "_tmp" / "review"
    f = ImageFont.truetype(font[0], 22, index=font[1])
    # motion sheets: 8 stickers per sheet, 4 frames each, alternating light/dark rows so halos show up
    per = 8
    sheets = []
    for s in range(0, len(entries), per):
        chunk = entries[s:s + per]
        tile = 200
        W = 150 + tile * 4
        im = Image.new("RGB", (W, tile * len(chunk)), "white")
        d = ImageDraw.Draw(im)
        for r, e in enumerate(chunk):
            bg = (255, 255, 255) if r % 2 == 0 else (38, 38, 44)
            fg = (40, 40, 40) if r % 2 == 0 else (230, 230, 230)
            d.rectangle((0, r * tile, W, (r + 1) * tile), fill=bg)
            d.text((10, r * tile + 70), f"#{e.number:03d}\n{e.text}\n{e.motion}", font=f, fill=fg)
            strip = Image.open(tmp / f"{e.number:03d}-strip.png")
            strip = strip.resize((tile * 4, tile), LANCZOS)
            im.paste(strip, (150, r * tile), strip)
        p = rev / f"motion-{s // per + 1:02d}.png"
        im.save(p)
        sheets.append(p)
    # contact sheet
    cols = 8
    tile = 160
    rows = (len(entries) + cols - 1) // cols
    im = checker((cols * tile, rows * (tile + 28)))
    d = ImageDraw.Draw(im)
    small = ImageFont.truetype(font[0], 18, index=font[1])
    for i, e in enumerate(entries):
        x, y = (i % cols) * tile, (i // cols) * (tile + 28)
        st = Image.open(tmp / f"{e.number:03d}-still.png").resize((tile, tile), LANCZOS)
        im.paste(st, (x, y), st)
        d.text((x + 4, y + tile + 3), f"{e.number:03d} {e.text}", font=small, fill=(30, 30, 30))
    im.save(rev / "contact.png")
    return sheets


def clean_art(entry, reference):
    src = reference if reference and Path(reference).exists() else entry.sprites[0]
    im = Image.open(src).convert("RGBA")
    return im.crop(im.getchannel("A").getbbox())


def place(im, S, fill):
    k = min(S * fill / im.width, S * fill / im.height)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), LANCZOS)
    c = Image.new("RGBA", (S, S))
    c.alpha_composite(im, ((S - im.width) // 2, (S - im.height) // 2))
    return c


def extras(name, entries, out: Path, cover_no: int, reference=None):
    """Static companion images some platforms ask for."""
    tmp = out / "_tmp" / "review"
    ex = out / name / "_extras"
    made = []

    def still(n):
        return Image.open(tmp / f"{n:03d}-still.png").convert("RGBA")

    def save(im, rel):
        p = ex / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        im.save(p)
        made.append(p)

    cover = still(cover_no)
    if name == "wechat":
        for e in entries:
            save(still(e.number).resize((120, 120), LANCZOS), f"缩略图120/{e.stem}.png")
        # 封面/图标: the console asks for transparent background, NO white outline, NO text -> use the raw art
        art = clean_art(next(e for e in entries if e.number == cover_no), reference)
        save(place(art, 240, 0.92), "封面240.png")
        save(place(art, 50, 0.96), "聊天页图标50.png")
    elif name == "line":
        save(cover.resize((240, 240), LANCZOS), "main.png")
        tab = Image.new("RGBA", (96, 74))
        c = cover.resize((74, 74), LANCZOS)
        tab.alpha_composite(c, (11, 0))
        save(tab, "tab.png")
    elif name == "whatsapp":
        save(cover.resize((96, 96), LANCZOS), "tray96.png")
    elif name == "telegram":
        save(cover.resize((100, 100), LANCZOS), "pack-thumb100.png")
    return made


def gallery(title, entries, platforms, results, out: Path):
    first = platforms[0]
    fmt = PLATFORMS[first]["fmt"]
    playable = first if fmt != "webm" else next((p for p in platforms if PLATFORMS[p]["fmt"] != "webm"), None)
    groups = {}
    for e in entries:
        groups.setdefault((e.group_index, e.group), []).append(e)
    cards = []
    for (gi, gname), es in sorted(groups.items()):
        items = []
        for e in es:
            if playable:
                src = f"{playable}/{e.stem}.{EXT[PLATFORMS[playable]['fmt']]}"
                media = f'<img loading="lazy" src="{quote(src)}" alt="{html.escape(e.text)}">'
            else:
                src = f"{first}/{e.stem}.webm"
                media = f'<video src="{quote(src)}" autoplay loop muted playsinline></video>'
            sizes = " · ".join(f"{p} {results[e.number][p]['bytes'] // 1000}KB" for p in platforms)
            bad = [i for p in platforms for i in results[e.number][p]["issues"]]
            flag = f'<b class="bad" title="{html.escape("；".join(bad))}">!</b>' if bad else ""
            items.append(f'<figure data-src="{quote(src)}">{media}{flag}<figcaption>{e.number:03d} {html.escape(e.text)}'
                         f'<small>{html.escape(e.motion)} · {sizes}</small></figcaption></figure>')
        cards.append(f'<section><h2>{html.escape(gname)} <span>{len(es)}</span></h2><div class="grid">{"".join(items)}</div></section>')
    stats = []
    for p in platforms:
        rs = [results[e.number][p] for e in entries]
        ok = sum(r["ok"] for r in rs)
        biggest = max(r["bytes"] for r in rs) // 1000
        stats.append(f'<li><b>{html.escape(PLATFORMS[p]["label"])}</b> {ok}/{len(rs)} 通过 · 最大 {biggest}KB / 上限 '
                     f'{PLATFORMS[p]["budget"] // 1000}KB</li>')
    chat_src = []
    for e in entries[:6]:
        if playable:
            chat_src.append(f"{playable}/{e.stem}.{EXT[PLATFORMS[playable]['fmt']]}")
    chat = "".join(
        f'<div class="msg {"me" if i % 2 else ""}"><img src="{quote(s)}" alt=""></div>' for i, s in enumerate(chat_src))
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{--bg:#f6f4fb;--fg:#26213a;--muted:#6b6482;--card:#fff;--line:#e2dcef}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:1180px;margin:auto;padding:28px 16px 60px}}h1{{margin:0 0 6px;font-size:30px}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}}button{{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:6px 14px;cursor:pointer}}
button[aria-pressed=true]{{background:var(--fg);color:var(--bg)}}ul{{padding-left:18px;color:var(--muted)}}
h2{{font-size:18px;margin:28px 0 10px}}h2 span{{color:var(--muted);font-weight:400}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
figure{{margin:0;position:relative;border-radius:14px;padding:10px;background:var(--tile)}}
figure img,figure video{{width:100%;aspect-ratio:1;object-fit:contain;display:block}}
figcaption{{font-size:13px;text-align:center;color:var(--fg)}}small{{display:block;color:var(--muted);font-size:11px}}
.bad{{position:absolute;top:6px;right:8px;background:#e5484d;color:#fff;border-radius:50%;width:20px;height:20px;text-align:center;font-size:13px;line-height:20px}}
body[data-bg=light]{{--tile:#ffffff}}body[data-bg=dark]{{--tile:#1f1f24}}body[data-bg=dark] figcaption{{color:#ddd}}
body[data-bg=checker]{{--tile:repeating-conic-gradient(#ddd 0 25%,#fff 0 50%) 0 0/16px 16px}}
body[data-bg=pixel] figure img{{image-rendering:pixelated}}
.chat{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.phone{{border-radius:22px;padding:14px;min-height:260px}}
.phone.l{{background:#ededed}}.phone.d{{background:#111}}.msg{{display:flex;margin:8px 0}}.msg.me{{justify-content:flex-end}}
.msg img{{width:110px;height:110px;object-fit:contain}}
@media(max-width:640px){{.chat{{grid-template-columns:1fr}}}}
</style>
<body data-bg="light"><main>
<h1>{html.escape(title)}</h1><div style="color:var(--muted)">{len(entries)} 张 · 预览用的是「{html.escape(PLATFORMS[playable]["label"] if playable else first)}」版本</div>
<ul>{"".join(stats)}</ul>
<h2>放进聊天里的样子</h2><div class="chat"><div class="phone l">{chat}</div><div class="phone d">{chat}</div></div>
<div class="bar">背景：<button data-b="light">白</button><button data-b="dark">深色模式</button><button data-b="checker">透明格</button><button data-b="pixel">像素放大</button></div>
{"".join(cards)}
</main><script>
const bs=document.querySelectorAll('[data-b]');function set(b){{document.body.dataset.bg=b;bs.forEach(x=>x.setAttribute('aria-pressed',x.dataset.b===b))}}
bs.forEach(x=>x.onclick=()=>set(x.dataset.b));set('light');
</script></body></html>"""
    (out / "预览.html").write_text(page, encoding="utf-8")


def mp4_preview(entries, platform, out: Path, title, font):
    if not shutil.which("ffmpeg") or PLATFORMS[platform]["fmt"] == "webm":
        return None
    W, H = 1280, 720
    tile = 140
    path = out / "动态预览.mp4"
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-framerate", "25", "-i", "pipe:0", "-c:v", "libx264", "-crf", "20", "-pix_fmt",
                             "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
    tf = ImageFont.truetype(font[0], 34, index=font[1])
    sf = ImageFont.truetype(font[0], 16, index=font[1])
    spec = PLATFORMS[platform]
    per = 24
    try:
        for s in range(0, len(entries), per):
            chunk = entries[s:s + per]
            base = Image.new("RGB", (W, H), (246, 244, 251))
            d = ImageDraw.Draw(base)
            d.text((40, 24), f"{title}  {s + 1}–{s + len(chunk)} / {len(entries)}", font=tf, fill=(38, 33, 58))
            decoded = []
            for e in chunk:
                fr, durs, _ = decode(out / platform / f"{e.stem}.{EXT[spec['fmt']]}")
                seq = []
                for f, du in zip(fr, durs):
                    seq += [f.resize((tile, tile), LANCZOS)] * max(1, round(du / 40))
                decoded.append(seq)
            for i, e in enumerate(chunk):
                x, y = 40 + (i % 8) * 152, 90 + (i // 8) * 205
                d.rounded_rectangle((x, y, x + 144, y + 190), 12, fill=(255, 255, 255))
                d.text((x + 72, y + 168), f"{e.number:03d} {e.text}", font=sf, fill=(80, 74, 100), anchor="mm")
            length = max(len(q) for q in decoded) * 2
            for k in range(length):
                im = base.copy()
                for i, seq in enumerate(decoded):
                    x, y = 40 + (i % 8) * 152, 90 + (i // 8) * 205
                    f = seq[k % len(seq)]
                    im.paste(f, (x + 2, y + 10), f)
                proc.stdin.write(im.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    return path


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("out", type=Path, help="输出目录（会被清空重建）")
    ap.add_argument("--platform", default=None, help=f"逗号分隔：{','.join(PLATFORMS)}（默认读清单 platforms，再默认 generic）")
    ap.add_argument("--font", help="字体文件；不填则自动找系统中文字体")
    ap.add_argument("--font-index", type=int, default=None)
    ap.add_argument("--only", help="只渲染这些编号，例如 1,5,12-16（试做/返工用，不打包）")
    ap.add_argument("--jobs", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--mp4", action="store_true", help="另外导出一段可播放的 MP4 总览")
    ap.add_argument("--cover", type=int, default=1, help="哪一张做封面/图标（编号）")
    args = ap.parse_args()

    manifest, entries = load_manifest(args.manifest, args.font, args.font_index)
    platforms = (args.platform or ",".join(manifest.get("platforms", ["generic"]))).split(",")
    for p in platforms:
        if p not in PLATFORMS:
            raise SystemExit(f"未知平台 {p}，可选：{', '.join(PLATFORMS)}")
    if "telegram" in platforms and not shutil.which("ffmpeg"):
        raise SystemExit("Telegram 需要 ffmpeg（带 libvpx-vp9）")
    if args.only:
        keep = set()
        for part in args.only.split(","):
            a, _, b = part.partition("-")
            keep.update(range(int(a), int(b or a) + 1))
        entries = [e for e in entries if e.number in keep]
    title = manifest.get("title", "表情包")
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    for p in platforms:
        (out / p).mkdir(parents=True)

    jobs = [Job(e, platforms, str(out)) for e in entries]
    results, hashes = {}, {}
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for n, r, h in ex.map(build_one, jobs):
            results[n] = r
            hashes[n] = h
            bad = [f"{p}:{'；'.join(r[p]['issues'])}" for p in platforms if r[p]["issues"]]
            print(f"  #{n:03d} " + " ".join(f"{p} {r[p]['bytes'] // 1000}KB" for p in platforms) +
                  (f"  ⚠ {' | '.join(bad)}" if bad else ""), flush=True)

    # pack-level checks
    pack_issues = []
    nums = sorted(hashes)
    by_no = {e.number: e for e in entries}
    parent = {n: n for n in nums}

    def root(n):
        while parent[n] != n:
            n = parent[n]
        return n
    for i, a in enumerate(nums):
        for b in nums[i + 1:]:
            if core.hamming(hashes[a], hashes[b]) <= 10:
                parent[root(b)] = root(a)
    clusters = {}
    for n in nums:
        clusters.setdefault(root(n), []).append(n)
    for c in clusters.values():
        if len(c) > 1:
            pack_issues.append("这些姿势几乎一样，至少重画其中几张：" + "、".join(f"#{n}「{by_no[n].text}」" for n in c))
    for p in platforms:
        counts = PLATFORMS[p].get("counts")
        if counts and not args.only and len(entries) not in counts:
            pack_issues.append(f"{PLATFORMS[p]['label']} 一套只能是 {counts} 张，现在是 {len(entries)} 张")
    for e in entries:
        lo = min(results[e.number][p]["motion"] for p in platforms)
        if lo < 0.6:
            pack_issues.append(f"#{e.number}「{e.text}」动得太少（{lo}），小图里看不出在动")

    sheets = review_sheets(entries, out, entries[0].font)
    extra_files = []
    cover = args.cover if any(e.number == args.cover for e in entries) else entries[0].number
    for p in platforms:
        ref = manifest.get("character", {}).get("reference")
        extra_files += extras(p, entries, out, cover, str(args.manifest.parent / ref) if ref else None)
    gallery(title, entries, platforms, results, out)
    mp4 = None
    if args.mp4:
        mp4 = mp4_preview(entries, platforms[0], out, title, entries[0].font)

    report = dict(title=title, count=len(entries), platforms=platforms, pack_issues=pack_issues,
                  stickers={e.number: dict(text=e.text, motion=e.motion, keys=len(e.sprites), **{"by_platform": results[e.number]})
                            for e in entries})
    zip_path = None
    if not args.only:
        zip_path = out / f"{clean_name(title)}-{len(entries)}张.zip"
        files = [out / "预览.html"]
        for p in platforms:
            files += sorted((out / p).rglob("*.*"))
        if mp4:
            files.append(mp4)
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, f.relative_to(out).as_posix())
        with ZipFile(zip_path) as z:
            assert z.testzip() is None
            for p in platforms:
                n = len([x for x in z.namelist() if x.startswith(p + "/") and "/_extras/" not in x])
                assert n == len(entries), f"ZIP 里 {p} 只有 {n} 张"
    shutil.rmtree(out / "_tmp", ignore_errors=True)
    report["zip"] = str(zip_path) if zip_path else None
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    failing = {p: [e.number for e in entries if not results[e.number][p]["ok"]] for p in platforms}
    print(json.dumps(dict(count=len(entries), platforms=platforms,
                          failing={k: v for k, v in failing.items() if v}, pack_issues=pack_issues,
                          review=[str(s) for s in sheets] + [str(out / "review" / "contact.png")],
                          gallery=str(out / "预览.html"), zip=report["zip"], mp4=str(mp4) if mp4 else None),
                     ensure_ascii=False, indent=1))
    if any(failing.values()):
        sys.exit(2)


if __name__ == "__main__":
    main()
