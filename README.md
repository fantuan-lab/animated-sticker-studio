# Animated Sticker Studio

**English** | [中文](README.zh-CN.md)

<p>
  <a href="https://github.com/fantuan-lab/animated-sticker-studio/stargazers"><img src="https://img.shields.io/github/stars/fantuan-lab/animated-sticker-studio?style=flat&color=f5a623" alt="stars"></a>
  <a href="https://github.com/fantuan-lab/animated-sticker-studio/releases"><img src="https://img.shields.io/github/v/release/fantuan-lab/animated-sticker-studio?color=e85d75" alt="release"></a>
  <img src="https://img.shields.io/badge/Claude_Code-skill-d97757" alt="Claude Code skill">
  <img src="https://img.shields.io/badge/Codex-skill-10a37f" alt="Codex skill">
  <img src="https://img.shields.io/badge/WeChat%20%C2%B7%20Telegram%20%C2%B7%20LINE%20%C2%B7%20Discord%20%C2%B7%20Slack%20%C2%B7%20WhatsApp-6%20platforms-4c9be8" alt="WeChat, Telegram, LINE, Discord, Slack, WhatsApp">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license"></a>
</p>

<img src="examples/onigiri-cat/hero.webp" width="100%" alt="Onigiri Cat animated stickers">

Give your AI coding agent one character image (or just a description) and get back a full pack of chat stickers that **actually animate**: it writes the captions and poses, draws every keyframe, adds text and effects, exports to each platform's exact upload spec, compresses every file under the size limit, checks its own work, and zips it up.

Works in Claude Code, Codex, and any agent that can run Python.

## Example: Onigiri Cat · 24 stickers

An original character, made in one run: 1 character sheet + 3 pose sheets = 4 image-generation calls, no manual retouching. Shown below is the WeChat Sticker Platform export (240×240, ≤500 KB each), submitted for WeChat review on 2026-11-05.

**#1–16**: one pose each, plus procedural motion. **#17–24**: real frame-by-frame animation — the paw waves, the tears stream, the yawn opens.

| | | | | | |
|---|---|---|---|---|---|
| <img src="examples/onigiri-cat/gif/001-%E6%94%B6%E5%88%B0.gif" width="120" alt="001-收到"><br>001-收到 | <img src="examples/onigiri-cat/gif/002-%E5%A5%BD%E8%80%B6.gif" width="120" alt="002-好耶"><br>002-好耶 | <img src="examples/onigiri-cat/gif/003-%E6%8A%B1%E6%8A%B1.gif" width="120" alt="003-抱抱"><br>003-抱抱 | <img src="examples/onigiri-cat/gif/004-%E6%97%A9%E5%AE%89.gif" width="120" alt="004-早安"><br>004-早安 | <img src="examples/onigiri-cat/gif/005-%E5%9C%A8%E5%90%97.gif" width="120" alt="005-在吗"><br>005-在吗 | <img src="examples/onigiri-cat/gif/006-%E5%93%88%E5%93%88%E5%93%88%E5%93%88.gif" width="120" alt="006-哈哈哈哈"><br>006-哈哈哈哈 |
| <img src="examples/onigiri-cat/gif/007-%E5%A7%94%E5%B1%88.gif" width="120" alt="007-委屈"><br>007-委屈 | <img src="examples/onigiri-cat/gif/008-%E7%94%9F%E6%B0%94%E4%BA%86.gif" width="120" alt="008-生气了"><br>008-生气了 | <img src="examples/onigiri-cat/gif/009-%E6%88%91%E6%83%B3%E6%83%B3.gif" width="120" alt="009-我想想"><br>009-我想想 | <img src="examples/onigiri-cat/gif/010-%E5%8A%A0%E6%B2%B9.gif" width="120" alt="010-加油"><br>010-加油 | <img src="examples/onigiri-cat/gif/011-%E8%B0%A2%E8%B0%A2%E8%80%81%E6%9D%BF.gif" width="120" alt="011-谢谢老板"><br>011-谢谢老板 | <img src="examples/onigiri-cat/gif/012-%E6%BA%9C%E4%BA%86.gif" width="120" alt="012-溜了"><br>012-溜了 |
| <img src="examples/onigiri-cat/gif/013-%E9%9C%87%E6%83%8A.gif" width="120" alt="013-震惊"><br>013-震惊 | <img src="examples/onigiri-cat/gif/014-%E6%91%B8%E9%B1%BC%E4%B8%AD.gif" width="120" alt="014-摸鱼中"><br>014-摸鱼中 | <img src="examples/onigiri-cat/gif/015-%E5%A5%BD%E7%9A%84.gif" width="120" alt="015-好的"><br>015-好的 | <img src="examples/onigiri-cat/gif/016-%E5%86%B2%E9%B8%AD.gif" width="120" alt="016-冲鸭"><br>016-冲鸭 | <img src="examples/onigiri-cat/gif/017-%E6%8B%9C%E6%8B%9C.gif" width="120" alt="017-拜拜"><br>017-拜拜 | <img src="examples/onigiri-cat/gif/018-%E9%BC%93%E6%8E%8C.gif" width="120" alt="018-鼓掌"><br>018-鼓掌 |
| <img src="examples/onigiri-cat/gif/019-%E6%89%93%E5%AD%97%E4%B8%AD.gif" width="120" alt="019-打字中"><br>019-打字中 | <img src="examples/onigiri-cat/gif/020-%E5%B9%B2%E9%A5%AD.gif" width="120" alt="020-干饭"><br>020-干饭 | <img src="examples/onigiri-cat/gif/021-%E7%82%B9%E8%B5%9E.gif" width="120" alt="021-点赞"><br>021-点赞 | <img src="examples/onigiri-cat/gif/022-%E5%93%AD%E5%93%AD.gif" width="120" alt="022-哭哭"><br>022-哭哭 | <img src="examples/onigiri-cat/gif/023-%E5%9B%B0%E4%BA%86.gif" width="120" alt="023-困了"><br>023-困了 | <img src="examples/onigiri-cat/gif/024-%E6%AF%94%E5%BF%83.gif" width="120" alt="024-比心"><br>024-比心 |

<details>
<summary>The same pack exported to four platforms, all passing their spec checks</summary>

| Platform | Spec | Largest / average file | Limit |
|---|---|---|---|
| Generic GIF | 320×320 GIF | 702 KB / 578 KB | 1 MB (soft) |
| WeChat Sticker Platform | 240×240 GIF + 120 thumbnails + transparent cover and icon | 442 KB / 368 KB | 500 KB |
| Telegram video sticker | 512×512 transparent WebM VP9 | 128 KB / 94 KB | 256 KB |
| LINE animated sticker | 320×270 APNG, 12 frames, 2 loops | 298 KB / 270 KB | 300 KB |

</details>

## What it does

- **Characters really move.** Gesture stickers get 2–4 drawn keyframes (wave, clap, type, eat, cry, yawn…), layered with procedural motion. Most AI sticker tools only slide and squash one still image.
- **22 seamless motion presets**, 5 caption animations (pop, typewriter, wave, shake, static), 17 vector effect icons that stay sharp at any size.
- **Smooth illustration or pixel-art** rendering.
- **Platform presets**: generic GIF, WeChat Sticker Platform, Telegram, LINE, Discord, Slack, WhatsApp — size, format, frame count, duration and byte limits. Files are re-encoded until they fit, and the setting used is recorded.
- **Companion images** each platform asks for: WeChat thumbnails / cover / chat icon, LINE main + tab, Telegram and WhatsApp pack icons.
- **Robust cutting**: removes solid backgrounds and the fake "transparent" checkerboard image models often paint; finds each sprite by its pixels, so uneven grids still cut cleanly; writes a numbered index sheet per atlas.
- **Self-review the agent can actually see**: agents can't watch a GIF, so every sticker is laid out as 4 frames on alternating light/dark rows. Clipping, halos on dark mode, wrong motion and near-duplicate poses (perceptual hash) are flagged; stickers that jump off the canvas are auto-shrunk.
- **Offline preview page** with light / dark / checker / pixel backgrounds and a chat mock-up.
- **CJK fonts found automatically**, with a glyph-coverage check.

## Quick start

**Install**

- Claude Code: put this folder at `~/.claude/skills/animated-sticker-studio/`, or tell Claude: *"Install this skill: https://github.com/fantuan-lab/animated-sticker-studio"*
- Codex: put it at `~/.codex/skills/animated-sticker-studio/` (`agents/openai.yaml` is included).

Requires Python 3 + Pillow (`pip install Pillow`). Telegram export and the MP4 preview also need ffmpeg.

**Make a pack**

Send your agent a character image and say:

> Use animated-sticker-studio to make 16 animated stickers of this character for the WeChat Sticker Platform.

Or: "24 office-worker stickers", "use my own captions", "pixel style", "also export a Telegram version". No image? Describe the character and it will draw a reference sheet for you to approve first.

**Image generation: you only need ONE of these**

| You use | What to set up | Notes |
|---|---|---|
| Codex | Nothing | Codex has a built-in image tool; the skill hands it the prompts |
| Claude Code (recommended: hiapi) | One hiapi key as `HIAPI_API_KEY` | Used for the Onigiri Cat pack, tested. gpt-image-2, 1K transparent, about $0.04 per sheet. Sign up with my invite link: [hiapi.ai/invite/fantuan](https://hiapi.ai/invite/fantuan) |
| Claude Code (fallback: OpenAI) | Only if you already have an OpenAI or compatible-gateway key: `OPENAI_API_KEY` | Code is written but not yet tested; not needed if you use hiapi |

<details>
<summary>Run the scripts yourself</summary>

```sh
# 1. write manifest.json (format: references/manifest.md, captions: references/phrases.md)
# 2. generate pose sheets
python3 scripts/gen_atlas.py manifest.json --provider hiapi
# 3. cut sprites, then check atlases/*.index.png
python3 scripts/cut_atlas.py manifest.json
# 4. render, export, verify, zip
python3 scripts/build_pack.py manifest.json out --platform wechat,telegram --mp4
```

Rebuild the example without spending anything (the cut sprites are in the repo):

```sh
cd examples/onigiri-cat
python3 ../../scripts/build_pack.py manifest.json out --platform generic,wechat
```

</details>

## Repository layout

```
SKILL.md                workflow the agent follows
scripts/gen_atlas.py    prompts + image-generation providers
scripts/cut_atlas.py    background removal, sprite cutting, index sheets
scripts/build_pack.py   render, per-platform export, compression, checks, preview, zip
scripts/sticker_core.py motion, icons, captions, die-cut outline
references/             manifest format, platform specs, caption library (Chinese)
examples/onigiri-cat/   Onigiri Cat: reference, atlases, sprites, finished GIFs
```

## Notes

- Platform specs reflect public requirements as of November 2026; the platform's own console is the final word. Store listings (banners, copyright paperwork, account setup) are still up to you.
- Your reference image is sent to the image provider you choose. Use only characters you own or are licensed to adapt.
- Built after studying [WoYun520/pixel-gif-sticker-pack](https://github.com/WoYun520/pixel-gif-sticker-pack); the Chinese README has a point-by-point comparison.

## License

[MIT](LICENSE)
