# Platform presets

Public requirements as of 2026-11. The platform's own console is the final word; re-check before a submission.
`build_pack.py` encodes each sticker per platform and steps down colours / quality / frame count until the file fits the budget. `report.json` → `by_platform.<name>.setting` says what it used.

| key | what you get | canvas | format | per-file limit | other rules checked |
|---|---|---|---|---|---|
| `generic` | GIF to send in WeChat/QQ/飞书/钉钉 chats directly | 320×320 | GIF, 24 f × 80 ms, infinite loop | 1 MB (soft) | transparency, clipping, motion |
| `wechat` | 微信表情开放平台 主图 | 240×240 | GIF | 500 KB | album = any 8–24; extras: 120×120 缩略图 per sticker, 240×240 封面 PNG and 50×50 聊天页图标 PNG (both: transparent, no white outline, no text — taken from the reference art) |
| `telegram` | Telegram video sticker | 512×512 | WebM VP9 + alpha, no audio | 256 KB | ≤3 s, ≤30 fps; extra: 100×100 pack thumbnail PNG |
| `line` | LINE animation sticker | 320×270 | APNG, 12 f × 160 ms, 2 loops | 300 KB | 5–20 frames, total play ≤4 s, pack = 8/16/24; extras: main 240×240, tab 96×74 |
| `discord` | Discord server sticker | 320×320 | APNG | 512 KB | |
| `slack` | Slack custom emoji | 128×128 | GIF, 12 f × 160 ms | 128 KB | |
| `whatsapp` | WhatsApp animated sticker | 512×512 | animated WebP | 500 KB | extra: 96×96 tray icon |

Still manual after the build:

- **WeChat 表情开放平台** (form checked 2026-11-05): 表情名称 ≤8 汉字 no punctuation; 表情介绍 ≤80; 版权信息 ≤10 (designer/studio name if unregistered); 详情页横幅 750×400 JPG/PNG ≤500KB, no text, not white, not transparent; 赞赏引导语 5–15 字 + 引导图 750×560 + 致谢图 750×750 (≤500KB each); one 含义词 per sticker; 原创类型 / 角色 / 风格 (1–2) / 主题. 赞赏 needs complete 艺术家信息 first. The price field only appears for accounts with paid stickers enabled.
- **LINE Creators Market**: account + listing text; LINE re-checks every APNG.
- **Telegram**: upload via @Stickers bot (`/newvideo`), one file at a time, then the pack icon.
- **Discord**: server must have free sticker slots (boost level dependent).

Notes

- GIF has 1-bit transparency. The white die-cut border hides the stair-step edge, so stickers look clean on both light and dark chat backgrounds; check the dark rows in `review/motion-*.png`.
- APNG, WebP and WebM keep full soft alpha.
- Telegram needs ffmpeg built with `libvpx-vp9`. Check with `ffmpeg -hide_banner -encoders | grep vp9`.
