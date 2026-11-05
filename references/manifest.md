# manifest.json

One file drives the whole pipeline. `gen_atlas.py` fills `atlas`/`grid`, `cut_atlas.py` fills `sprites`, `build_pack.py` reads everything. Paths are relative to the manifest.

```json
{
  "title": "饭团猫日常",
  "style": "smooth",
  "count": 24,
  "character": {
    "name": "饭团猫",
    "reference": "ref/character.png",
    "anchors": "chubby white onigiri-shaped cat, green nori band on belly, red umeboshi on head, big round black eyes"
  },
  "palette": {"ink": "#2F3A4A", "accent": "#FF6F91", "outline": "#FFFFFF"},
  "caption": {"fx": "pop", "pos": "bottom"},
  "platforms": ["generic", "wechat"],
  "groups": [
    {
      "name": "日常回复",
      "atlas": "atlases/g01.png", "grid": [4, 4],
      "entries": [
        {"text": "收到", "pose": "saluting with the right paw, confident smile", "motion": "nod", "icon": "check",
         "sprites": ["sprites/g01_01.png"]}
      ]
    },
    {
      "name": "逐帧动作",
      "keys": 4,
      "atlas": "atlases/g02.png", "grid": [4, 4],
      "entries": [
        {"text": "拜拜", "pose": "waving goodbye",
         "key_poses": ["paw down", "paw raised, palm open", "paw tilted left", "paw tilted right"],
         "timing": [2, 1, 1, 1], "motion": "breathe", "icon": "none",
         "sprites": ["sprites/g02_01.png", "sprites/g02_02.png", "sprites/g02_03.png", "sprites/g02_04.png"]}
      ]
    }
  ]
}
```

## Top level

| field | default | meaning |
|---|---|---|
| `title` | 表情包 | pack name; used for the ZIP and gallery |
| `style` | `smooth` | `smooth` = anti-aliased illustration (soft alpha kept in APNG/WebP/WebM). `pixel` = nearest-neighbour, hard edges, pixel-art outline |
| `count` | – | optional; build fails if the real count differs |
| `palette.ink` | `#3B2A5A` | caption fill and icon outline (a group may override `ink`/`accent`) |
| `palette.accent` | `#FF7AA8` | icon fill |
| `palette.outline` | `#FFFFFF` | die-cut border around the art and caption stroke |
| `caption.fx` | `pop` | default caption animation |
| `caption.pos` | `bottom` | `bottom` or `top` |
| `platforms` | `["generic"]` | see platforms.md; `--platform` overrides |

## Group

| field | meaning |
|---|---|
| `name` | category shown in gallery |
| `keys` | 1 (default) = one pose per cell. N>1 = each atlas ROW is one sticker's N keyframes, left→right |
| `atlas` | sheet path (string, or a list when one group spans several sheets) |
| `grid` | `[cols, rows]`; for `keys` groups this is `[keys, entries]` |

## Entry

| field | meaning |
|---|---|
| `text` | caption; empty string = no caption (art gets bigger) |
| `pose` | English drawing instruction for the cell (or the loop's theme for keyframes) |
| `key_poses` | keys groups only: exactly `keys` short descriptions, one per frame |
| `sprites` | filled by `cut_atlas.py`; 1 path = static pose, 2+ = keyframes |
| `timing` | relative hold length per keyframe, e.g. `[2,1,1,1]` |
| `motion` | procedural motion layered on top (keyframe stickers often use `none` or `breathe`) |
| `amp` | motion strength multiplier, default 1.0 |
| `icon` | moving accent, or `none` |
| `caption_fx` | overrides the pack default |

## Motions

`none` `breathe` `float` `nod` `shake_head` `sway` `jump` `hop2` `startle` `pop` `heartbeat` `tremble` `droop` `lean` `bow` `rush` `dance` `stomp` `wiggle` `dizzy` `peek` `slide`

All are seamless loops. `slide` leaves the frame on purpose (exempt from the clipping check).

## Icons

`spark` `heart` `tear` `sweat` `anger` `question` `exclaim` `zzz` `note` `check` `cross` `steam` `swirl` `bolt` `dots` `lines` `flower` `none`

Vector-drawn, so they stay sharp at any output size; in `pixel` style they are drawn on the low-res grid and come out pixelated to match. Use `none` when the generated art already has its own effect marks.

## Caption effects

`static` · `pop` (springs in) · `type` (characters appear one by one) · `wave` (characters bob in sequence) · `shake` (jolts on the beat)
