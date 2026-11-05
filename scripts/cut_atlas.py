#!/usr/bin/env python3
"""Cut generated sprite sheets into one clean transparent PNG per pose.

Two ways to call it:

  # 1) whole manifest: cuts every group's atlas and writes `sprites` back into the manifest
  python3 cut_atlas.py manifest.json

  # 2) a single sheet
  python3 cut_atlas.py sheet.png --grid 4x4 --out sprites/

What it handles that a plain grid crop does not:
  * a solid or near-solid background (white, grey, chroma green…) → removed by edge flood-fill
  * a fake "transparent" checkerboard baked into the pixels → removed too
  * uneven gutters, sprites drifting across cell lines → each blob is assigned to the cell holding its centre
  * stray specks / leftover noise → dropped
For each sheet it also writes <sheet>.index.png: every cut sprite on a checkerboard with its number,
so you can confirm the cell→caption mapping by eye before rendering.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sticker_core as core  # noqa: E402


# ------------------------------------------------------------------ background removal

def _near(img_rgb: Image.Image, color, tol) -> Image.Image:
    """L mask: 255 where every channel is within tol of color."""
    diff = ImageChops.difference(img_rgb, Image.new("RGB", img_rgb.size, color))
    r, g, b = diff.split()
    m = ImageChops.lighter(ImageChops.lighter(r, g), b)
    return m.point(lambda v: 255 if v <= tol else 0)


def _border_colors(img_rgb: Image.Image, k=2):
    W, H = img_rgb.size
    small = img_rgb.resize((max(8, W // 4), max(8, H // 4)), Image.Resampling.NEAREST)
    w, h = small.size
    px = small.load()
    cnt = Counter()
    for x in range(w):
        cnt[tuple(v // 8 * 8 for v in px[x, 0])] += 1
        cnt[tuple(v // 8 * 8 for v in px[x, h - 1])] += 1
    for y in range(h):
        cnt[tuple(v // 8 * 8 for v in px[0, y])] += 1
        cnt[tuple(v // 8 * 8 for v in px[w - 1, y])] += 1
    total = sum(cnt.values())
    common = cnt.most_common(k)
    return [(tuple(c + 4 for c in col), n / total) for col, n in common]


def _flood_from_edges(mask: Image.Image) -> Image.Image:
    """Keep only the parts of a 255-mask that touch the image border (true background)."""
    W, H = mask.size
    m = mask.convert("L")
    seed_val, fill_val = 255, 128
    rgb = Image.merge("RGB", (m, m, m))
    d = ImageDraw.Draw(rgb)
    px = rgb.load()
    step = max(1, min(W, H) // 64)
    seeds = [(x, 0) for x in range(0, W, step)] + [(x, H - 1) for x in range(0, W, step)] + \
            [(0, y) for y in range(0, H, step)] + [(W - 1, y) for y in range(0, H, step)]
    for s in seeds:
        if px[s][0] == seed_val:
            ImageDraw.floodfill(rgb, s, (fill_val,) * 3, thresh=0)
    return rgb.getchannel("R").point(lambda v: 255 if v == fill_val else 0)


def remove_background(img: Image.Image, tol=28) -> tuple[Image.Image, str]:
    img = img.convert("RGBA")
    a = img.getchannel("A")
    lo, _ = a.getextrema()
    if lo < 200:
        # already has real transparency; just drop faint haze
        img.putalpha(a.point(lambda v: 0 if v < 24 else v))
        return img, "已有透明背景"
    rgb = img.convert("RGB")
    cols = _border_colors(rgb, 2)
    (c1, f1), (c2, f2) = cols[0], cols[1] if len(cols) > 1 else (cols[0][0], 0)
    checker = f2 > 0.2 and sum(abs(x - y) for x, y in zip(c1, c2)) > 12
    if checker:
        bgmask = ImageChops.lighter(_near(rgb, c1, 14), _near(rgb, c2, 14))
        how = f"去掉了假透明格子背景 {c1}/{c2}"
    else:
        bgmask = _near(rgb, c1, tol)
        how = f"去掉了纯色背景 {c1}"
    bg = _flood_from_edges(bgmask)
    # close pinholes inside the background, then feather the edge by one pixel
    bg = bg.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    alpha = ImageChops.invert(bg).filter(ImageFilter.GaussianBlur(0.6))
    img.putalpha(ImageChops.multiply(alpha, a))
    return img, how


# ------------------------------------------------------------------ components

def components(alpha: Image.Image, scale: int, min_frac=0.0006):
    """Connected blobs on a downscaled alpha. Returns list of (bbox_fullres, area_px)."""
    W, H = alpha.size
    w, h = max(1, W // scale), max(1, H // scale)
    small = alpha.resize((w, h), Image.Resampling.BOX).point(lambda v: 1 if v > 40 else 0)
    data = small.load()
    seen = bytearray(w * h)
    out = []
    for y in range(h):
        for x in range(w):
            if not data[x, y] or seen[y * w + x]:
                continue
            q = deque([(x, y)])
            seen[y * w + x] = 1
            x0 = x1 = x
            y0 = y1 = y
            area = 0
            while q:
                cx, cy = q.popleft()
                area += 1
                x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and data[nx, ny] and not seen[ny * w + nx]:
                        seen[ny * w + nx] = 1
                        q.append((nx, ny))
            if area >= min_frac * w * h:
                out.append(((x0 * scale, y0 * scale, (x1 + 1) * scale, (y1 + 1) * scale), area))
    return out


def cut_sheet(path: Path, cols: int, rows: int, out_dir: Path, prefix: str, tol=28):
    img, how = remove_background(Image.open(path), tol)
    W, H = img.size
    alpha = img.getchannel("A")
    blobs = components(alpha, scale=max(1, min(W, H) // 384))
    cw, ch = W / cols, H / rows
    cells = {(c, r): [] for r in range(rows) for c in range(cols)}
    warnings = []
    for (x0, y0, x1, y1), area in blobs:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        c, r = min(cols - 1, int(cx // cw)), min(rows - 1, int(cy // ch))
        cells[(c, r)].append(((x0, y0, x1, y1), area))
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for r in range(rows):
        for c in range(cols):
            parts = cells[(c, r)]
            idx = r * cols + c
            if not parts:
                warnings.append(f"格子 {idx + 1}（第 {r + 1} 行第 {c + 1} 列）是空的")
                results.append(None)
                continue
            biggest = max(a for _, a in parts)
            parts = [p for p in parts if p[1] >= biggest * 0.02]  # drop specks next to the main body
            x0 = min(p[0][0] for p in parts)
            y0 = min(p[0][1] for p in parts)
            x1 = max(p[0][2] for p in parts)
            y1 = max(p[0][3] for p in parts)
            pad = 4
            box = (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad))
            # only keep pixels of this cell's blobs (neighbours that overlap the box get masked out)
            mask = Image.new("L", (W, H))
            md = ImageDraw.Draw(mask)
            for (bx0, by0, bx1, by1), _ in parts:
                md.rectangle((bx0 - pad, by0 - pad, bx1 + pad, by1 + pad), fill=255)
            sprite = img.copy()
            sprite.putalpha(ImageChops.multiply(alpha, mask))
            sprite = sprite.crop(box)
            bb = sprite.getchannel("A").getbbox()
            sprite = sprite.crop(bb)
            if box[0] <= 0 or box[1] <= 0 or box[2] >= W or box[3] >= H:
                warnings.append(f"格子 {idx + 1} 碰到图片边缘，可能被画布截断")
            if x1 - x0 > cw * 1.15 or y1 - y0 > ch * 1.15:
                warnings.append(f"格子 {idx + 1} 比格子还大，可能和邻居粘在一起了")
            p = out_dir / f"{prefix}_{idx + 1:02d}.png"
            sprite.save(p)
            results.append(p)
    extra = sum(len(v) for v in cells.values()) - len([x for x in results if x])
    index_sheet(results, cols, rows, path.with_suffix(".index.png"))
    return results, how, warnings


def index_sheet(paths, cols, rows, dest: Path):
    tile = 220
    im = Image.new("RGB", (cols * tile, rows * tile), (236, 236, 236))
    d = ImageDraw.Draw(im)
    for y in range(0, rows * tile, 14):
        for x in range(0, cols * tile, 14):
            if (x // 14 + y // 14) % 2:
                d.rectangle((x, y, x + 13, y + 13), fill=(210, 210, 210))
    try:
        p, i = core.find_font(["0123456789"])
        f = core.ImageFont.truetype(p, 26, index=i)
    except SystemExit:
        f = ImageFont.load_default()
    for k, path in enumerate(paths):
        x, y = (k % cols) * tile, (k // cols) * tile
        if path:
            s = Image.open(path)
            s.thumbnail((tile - 30, tile - 30))
            im.paste(s, (x + (tile - s.width) // 2, y + 24 + (tile - 30 - s.height) // 2), s)
        d.rectangle((x, y, x + tile - 1, y + tile - 1), outline=(150, 150, 150))
        d.text((x + 8, y + 4), str(k + 1), font=f, fill=(200, 30, 60))
    im.save(dest)


# ------------------------------------------------------------------ manifest mode

def run_manifest(mpath: Path, tol):
    m = json.loads(mpath.read_text(encoding="utf-8"))
    base = mpath.parent
    report = []
    for gi, g in enumerate(m["groups"], 1):
        atlases = g.get("atlas")
        if not atlases:
            continue
        atlases = atlases if isinstance(atlases, list) else [atlases]
        cols, rows = g.get("grid", [4, 4])
        keys = int(g.get("keys", 1))
        cut = []
        for ai, a in enumerate(atlases):
            ap = base / a
            if not ap.exists():
                report.append(f"组 {g['name']}：还没有 {a}")
                continue
            prefix = f"g{gi:02d}" + (f"-{ai + 1}" if len(atlases) > 1 else "")
            sprites, how, warns = cut_sheet(ap, cols, rows, base / "sprites", prefix, tol)
            report.append(f"组 {g['name']} {a}：{how}；切出 {len([s for s in sprites if s])}/{cols * rows}")
            report += [f"  ⚠ {w}" for w in warns]
            report.append(f"  对照图：{ap.with_suffix('.index.png')}")
            cut += sprites
        # keys>1: each row of an atlas = one sticker's keyframes, left→right
        entries = g["entries"]
        need = len(entries) * keys
        if len(cut) < need:
            report.append(f"  ⚠ 组 {g['name']} 需要 {need} 个格子，只有 {len(cut)} 个")
        for i, e in enumerate(entries):
            cells = cut[i * keys:(i + 1) * keys]
            if not cells or any(c is None for c in cells):
                report.append(f"  ⚠ 「{e.get('text')}」缺图，先重画这一格")
                e.pop("sprites", None)
                continue
            e["sprites"] = [str(c.relative_to(base)) for c in cells]
    mpath.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(report))
    print(f"已把 sprites 写回 {mpath}。先看每张 *.index.png，确认编号和文案对得上。")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="manifest.json 或者一张图集 PNG")
    ap.add_argument("--grid", default="4x4", help="单张图集模式：列x行")
    ap.add_argument("--out", type=Path, default=Path("sprites"))
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--tol", type=int, default=28, help="纯色背景的容差，背景没去干净就调大")
    a = ap.parse_args()
    if a.input.suffix.lower() == ".json":
        run_manifest(a.input, a.tol)
        return
    cols, rows = (int(v) for v in a.grid.lower().split("x"))
    sprites, how, warns = cut_sheet(a.input, cols, rows, a.out, a.prefix or a.input.stem, a.tol)
    print(how)
    for w in warns:
        print("⚠", w)
    print(f"切出 {len([s for s in sprites if s])}/{cols * rows} → {a.out}；对照图 {a.input.with_suffix('.index.png')}")


if __name__ == "__main__":
    main()
