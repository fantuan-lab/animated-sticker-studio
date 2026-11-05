#!/usr/bin/env python3
"""Generate pose sheets (atlases) for every group in a sticker manifest.

  python3 gen_atlas.py manifest.json --provider hiapi            # all groups without an atlas yet
  python3 gen_atlas.py manifest.json --provider hiapi --group 2  # (re)generate one group
  python3 gen_atlas.py manifest.json --print-prompts             # just print prompts for an agent's own image tool
  python3 gen_atlas.py manifest.json --provider hiapi --make-reference "a round cream hamster mascot..."

Providers (keys come from the environment only, never from arguments):
  hiapi   HIAPI_API_KEY        gpt-image-2 image-to-image via https://api.hiapi.ai/v1/tasks (data-URI reference)
  openai  OPENAI_API_KEY       /v1/images/edits on OPENAI_BASE_URL (default https://api.openai.com), model
                               OPENAI_IMAGE_MODEL (default gpt-image-1); any OpenAI-compatible gateway works
The reference image is sent to the provider you choose. Only use art the user owns or is allowed to adapt.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

STYLE = {
    "pixel": ("Pixel-art sprite style: crisp chunky square pixels as if drawn at about 96 px tall and scaled up, "
              "limited palette, 1-pixel dark outline, no anti-aliasing, no gradients, no blur."),
    "smooth": ("Clean sticker illustration in exactly the same art style, line weight and colouring as the reference: "
               "bold clean outline, flat cel shading, bright saturated colours."),
}

RULES = (
    "Layout rules: an invisible {cols}-column × {rows}-row grid of equal cells; exactly one complete character per cell, "
    "centred, all at the same scale, feet/bottom roughly on the same line in each row. Leave wide empty gutters so "
    "nothing touches or crosses a neighbouring cell or the image edge. Background: fully transparent (or, if transparency "
    "is impossible, one flat plain colour that the character does not use). No grid lines, no borders, no frames, "
    "no speech bubbles, no text, no letters, no numbers, no watermark, no ground shadow. "
    "Faces must read clearly at 120 px: big expressive eyes and mouth, simple shapes."
)


def identity(m):
    c = m.get("character", {})
    parts = ["Use the attached reference image as the ONLY character model: same species/body shape, face, hair, "
             "colours, outfit and signature accessories in every cell."]
    if c.get("anchors"):
        parts.append(f"Identity anchors that must stay identical: {c['anchors']}.")
    if c.get("name"):
        parts.append(f"(The character is called {c['name']}; do not write the name anywhere.)")
    return " ".join(parts)


def group_prompt(m, g):
    style = STYLE.get(m.get("style", "smooth"), STYLE["smooth"])
    keys = int(g.get("keys", 1))
    entries = g["entries"]
    if keys > 1:
        cols, rows = keys, len(entries)
        lines = []
        for r, e in enumerate(entries, 1):
            kp = e.get("key_poses") or []
            if len(kp) != keys:
                raise SystemExit(f"「{e.get('text')}」需要 {keys} 个 key_poses")
            frames = "; ".join(f"frame {k + 1}: {p}" for k, p in enumerate(kp))
            lines.append(f"Row {r} — one short animation loop ({e.get('pose', e.get('text', ''))}), "
                         f"left to right: {frames}.")
        body = ("A sprite sheet of animation keyframes. Each ROW is one looping animation of the same character; "
                "inside a row only the body parts named below change, everything else (size, position of the feet, "
                "camera, lighting) stays fixed so the frames can be flipped through without jitter.\n" + "\n".join(lines))
    else:
        cols, rows = g.get("grid") or grid_for(len(entries))
        lines = [f"Cell {i + 1} (row {i // cols + 1}, column {i % cols + 1}): {e.get('pose') or e.get('text')}"
                 for i, e in enumerate(entries)]
        body = ("A character sticker sheet with a different pose and expression in each cell, in reading order "
                "(left→right, top→bottom). Every pose must be clearly different from the others — different arms, "
                "body angle, props or expression, not just a different mouth.\n" + "\n".join(lines))
        empties = cols * rows - len(entries)
        if empties:
            body += f"\nThe last {empties} cell(s) stay completely empty."
    return f"{identity(m)}\n{style}\n{body}\n" + RULES.format(cols=cols, rows=rows), (cols, rows)


def grid_for(n):
    if n <= 4:
        return [n, 1]
    if n <= 8:
        return [4, 2]
    if n <= 12:
        return [4, 3]
    if n <= 16:
        return [4, 4]
    raise SystemExit("一张图集最多 16 格；把这一组拆成两组")


RATIOS = {"1:1": 1, "4:3": 4 / 3, "3:2": 1.5, "2:1": 2, "3:1": 3, "3:4": 3 / 4, "2:3": 2 / 3, "1:2": 0.5}


def aspect(cols, rows):
    r = cols / rows
    return min(RATIOS, key=lambda k: abs(RATIOS[k] - r))


def ref_bytes(path: Path, max_side=768):
    """Reference shrunk to <=768px PNG: plenty for identity, much faster and steadier to upload."""
    from io import BytesIO
    from PIL import Image
    im = Image.open(path)
    im.thumbnail((max_side, max_side))
    buf = BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def data_uri(path: Path):
    return "data:image/png;base64," + base64.b64encode(ref_bytes(path)).decode()


# ------------------------------------------------------------------ providers

def _json(url, key, body=None, timeout=90, tries=6):
    """One HTTP call with its own retries, so a flaky connection never throws away a paid task."""
    data = json.dumps(body).encode() if body is not None else None
    for i in range(tries):
        req = urllib.request.Request(url, data=data,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if i == tries - 1:
                raise
            time.sleep(3 + 3 * i)


def _download(url, dest: Path, tries=6):
    for i in range(tries):
        try:
            urllib.request.urlretrieve(url, dest)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if i == tries - 1:
                raise
            time.sleep(3 + 3 * i)


def hiapi(prompt, ref: Path | None, ratio, dest: Path, resolution="1K"):
    key = os.environ.get("HIAPI_API_KEY") or sys.exit("没有 HIAPI_API_KEY 环境变量")
    api = "https://api.hiapi.ai/v1/tasks"
    inp = {"prompt": prompt, "aspect_ratio": ratio, "resolution": resolution}
    if resolution == "1K":
        inp["background"] = "transparent"
    if ref:
        inp["input_urls"] = [data_uri(ref)]
    model = "gpt-image-2/image-to-image" if ref else "gpt-image-2/text-to-image"
    tid = _json(api, key, {"model": model, "input": inp})["data"]["taskId"]
    wait = 6
    for _ in range(90):
        time.sleep(wait)
        wait = min(wait * 1.3, 20)
        d = _json(f"{api}/{tid}", key)["data"]
        if d["status"] == "success":
            _download(d["output"][0]["url"], dest)
            return
        if d["status"] in ("fail", "failed", "error"):
            raise RuntimeError(f"hiapi 任务失败：{json.dumps(d, ensure_ascii=False)[:400]}")
    raise TimeoutError("hiapi 超时")


def openai(prompt, ref: Path | None, ratio, dest: Path, resolution="1K"):
    key = os.environ.get("OPENAI_API_KEY") or sys.exit("没有 OPENAI_API_KEY 环境变量")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
    size = {"1:1": "1024x1024"}.get(ratio, "1536x1024" if RATIOS[ratio] > 1 else "1024x1536")
    fields = {"model": model, "prompt": prompt, "size": size, "background": "transparent", "n": "1",
              "output_format": "png"}
    if ref:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="reference.png"\r\n'
                 f'Content-Type: image/png\r\n\r\n').encode()
        body += ref_bytes(ref, 1024) + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{base}/images/edits", data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.load(r)
    else:
        res = _json(f"{base}/images/generations", key, fields, timeout=300)
    item = res["data"][0]
    if item.get("b64_json"):
        dest.write_bytes(base64.b64decode(item["b64_json"]))
    else:
        urllib.request.urlretrieve(item["url"], dest)


PROVIDERS = {"hiapi": hiapi, "openai": openai}


def generate(provider, prompt, ref, ratio, dest, resolution):
    last = None
    for attempt in range(3):
        try:
            PROVIDERS[provider](prompt, ref, ratio, dest, resolution)
            from PIL import Image
            Image.open(dest).load()
            return
        except (urllib.error.URLError, RuntimeError, TimeoutError, OSError, KeyError) as e:
            last = e
            print(f"  第 {attempt + 1} 次失败：{str(e)[:200]}，重试…", flush=True)
            time.sleep(5)
    raise SystemExit(f"生成失败：{last}")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--provider", choices=list(PROVIDERS))
    ap.add_argument("--group", type=int, action="append", help="只生成第几组（可重复）；会覆盖已有图集")
    ap.add_argument("--print-prompts", action="store_true", help="只打印提示词，交给你自己的出图工具")
    ap.add_argument("--resolution", default="1K", choices=["1K", "2K"],
                    help="1K 支持原生透明背景；2K 更清晰但背景要靠 cut_atlas 去掉")
    ap.add_argument("--make-reference", metavar="描述", help="用户只有文字描述时，先画一张角色设定图")
    a = ap.parse_args()

    mpath = a.manifest
    m = json.loads(mpath.read_text(encoding="utf-8"))
    base = mpath.parent
    char = m.setdefault("character", {})

    if a.make_reference:
        if not a.provider:
            sys.exit("--make-reference 需要 --provider")
        dest = base / "ref" / "character.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        p = (f"Character design reference for a chat sticker mascot: {a.make_reference}. One single character, "
             f"full body, front three-quarter view, neutral happy expression, centred, plain transparent background, "
             f"no text. {STYLE.get(m.get('style', 'smooth'))}")
        print("画角色设定图…", flush=True)
        generate(a.provider, p, None, "1:1", dest, "1K")
        char["reference"] = str(dest.relative_to(base))
        mpath.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"设定图：{dest}（先给用户看，满意了再生成图集）")
        return

    ref = base / char["reference"] if char.get("reference") else None
    if ref and not ref.exists() and not a.print_prompts:
        sys.exit(f"找不到参考图 {ref}")
    todo = []
    for gi, g in enumerate(m["groups"], 1):
        if a.group and gi not in a.group:
            continue
        if not a.group and not a.print_prompts and g.get("atlas") and (base / g["atlas"]).exists():
            continue
        todo.append((gi, g))
    if not todo:
        print("所有组都已经有图集了；要重画某组用 --group N")
        return
    for gi, g in todo:
        prompt, (cols, rows) = group_prompt(m, g)
        ratio = aspect(cols, rows)
        if a.print_prompts:
            print(f"===== 组 {gi}「{g['name']}」 {cols}x{rows}  比例 {ratio}  → 保存为 atlases/g{gi:02d}.png\n{prompt}\n")
            continue
        if not a.provider:
            sys.exit("请指定 --provider，或用 --print-prompts 交给自己的出图工具")
        dest = base / "atlases" / f"g{gi:02d}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"组 {gi}「{g['name']}」{cols}x{rows} 生成中…", flush=True)
        generate(a.provider, prompt, ref, ratio, dest, a.resolution)
        g["atlas"] = str(dest.relative_to(base))
        g["grid"] = [cols, rows]
        mpath.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  → {dest}", flush=True)
    if not a.print_prompts:
        print("下一步：python3 cut_atlas.py", mpath)


if __name__ == "__main__":
    main()
