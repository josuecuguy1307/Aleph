#!/usr/bin/env python3
"""build_cuarto_assets.py — the Pixi-native "studio".

No Godot. This script IS the asset pipeline: it draws one PNG atlas and emits
`cuarto.scene.json` conforming to cuarto.scene.schema.ts. Art, per-sprite anchors
and room layout are authored together here so they can never drift.

Run:  python3 build_cuarto_assets.py
Out:  atlas.png  +  cuarto.scene.json   (both next to this file)

Re-run whenever the room shell or sprites change (see README).
"""

import json
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 2  # supersample factor for crisp iso edges (draw 2x, downscale)

TILE_W = 64
TILE_H = 32

# ── palette ────────────────────────────────────────────────────────────────
C_FLOOR_TOP = (58, 65, 80)
C_FLOOR_BOT = (42, 48, 60)
C_FLOOR_EDGE = (74, 84, 104, 120)

C_WALL_TOP = (84, 93, 112)
C_WALL_L = (60, 68, 84)
C_WALL_R = (48, 55, 69)

C_PED_TOP = (88, 80, 130)
C_PED_L = (60, 54, 92)
C_PED_R = (46, 41, 72)

C_ORB_CORE = (197, 182, 255)
C_ORB_GLOW = (124, 92, 255)

C_PLANT_POT = (122, 84, 64)
C_PLANT_POT_D = (92, 62, 47)
C_PLANT_LEAF = (63, 174, 106)
C_PLANT_LEAF_D = (44, 132, 78)

C_DOOR_FRAME = (70, 79, 97)
C_DOOR_VOID = (20, 26, 34)
C_DOOR_GLOW = (70, 214, 200)

C_SLOT = (70, 214, 200)


def _img(w, h):
    return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))


def _diamond(d, cx, cy, w, h, fill, outline=None, ow=1):
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    d.polygon(pts, fill=fill, outline=outline, width=ow * SS)


def _vgrad_diamond(im, cx, cy, w, h, top, bot):
    """Diamond filled with a vertical gradient (cheap: per-scanline)."""
    d = ImageDraw.Draw(im)
    top_y, bot_y = cy - h / 2, cy + h / 2
    for y in range(int(top_y), int(bot_y) + 1):
        t = (y - top_y) / max(1, (bot_y - top_y))
        col = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
        # half-width of the diamond at this scanline
        ht = (1 - abs((y - cy) / (h / 2))) * (w / 2)
        if ht > 0:
            d.line([(cx - ht, y), (cx + ht, y)], fill=col, width=1)


def finish(im):
    """Downscale supersampled image to 1x."""
    return im.resize((im.width // SS, im.height // SS), Image.LANCZOS)


# ── sprite factories: each returns (PIL image @1x, (anchor_x_px, anchor_y_px)) ─

def make_floor():
    w, h = TILE_W, TILE_H
    im = _img(w, h)
    cx, cy = (w / 2) * SS, (h / 2) * SS
    _vgrad_diamond(im, cx, cy, w * SS, h * SS, C_FLOOR_TOP, C_FLOOR_BOT)
    d = ImageDraw.Draw(im)
    _diamond(d, cx, cy, w * SS - 2, h * SS - 2, None, outline=C_FLOOR_EDGE, ow=1)
    return finish(im), (w / 2, h / 2)


def _iso_box(w, h, box_h, top, lcol, rcol, top_inset=0):
    """Generic iso box. Returns (img@1x, anchor=base diamond center px@1x)."""
    im = _img(w, h)
    d = ImageDraw.Draw(im)
    s = SS
    tw = (w - top_inset * 2)
    th = tw / 2
    cx = (w / 2) * s
    top_cy = (th / 2) * s
    base_cy = top_cy + box_h * s
    # left & right faces (parallelograms)
    left = [(cx - tw / 2 * s, top_cy), (cx, top_cy + th / 2 * s),
            (cx, base_cy + th / 2 * s), (cx - tw / 2 * s, base_cy)]
    right = [(cx + tw / 2 * s, top_cy), (cx, top_cy + th / 2 * s),
             (cx, base_cy + th / 2 * s), (cx + tw / 2 * s, base_cy)]
    d.polygon(left, fill=lcol + (255,))
    d.polygon(right, fill=rcol + (255,))
    _diamond(d, cx, top_cy, tw * s, th * s, top + (255,))
    return finish(im), (w / 2, base_cy / s)


def make_wall():
    w, h, box_h = TILE_W, 80, 48
    return _iso_box(w, h, box_h, C_WALL_TOP, C_WALL_L, C_WALL_R)


def make_pedestal():
    w, h, box_h = 56, 64, 34
    return _iso_box(w, h, box_h, C_PED_TOP, C_PED_L, C_PED_R, top_inset=4)


def make_orb():
    w, h = 48, 96
    im = _img(w, h)
    d = ImageDraw.Draw(im)
    s = SS
    cx, cy, r = (w / 2) * s, 28 * s, 16 * s
    # halo (concentric, fading)
    for i in range(10, 0, -1):
        rr = r + i * 3 * s
        a = int(16 * (i / 10))
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=C_ORB_GLOW + (a,))
    # core sphere with a highlight
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=C_ORB_CORE + (255,))
    d.ellipse([cx - r, cy - r, cx + r * 0.2, cy + r * 0.2], fill=(255, 255, 255, 200))
    return finish(im), (w / 2, h)  # contact at bottom-center (floats above tile)


def make_plant():
    w, h = 40, 72
    im = _img(w, h)
    d = ImageDraw.Draw(im)
    s = SS
    cx = (w / 2) * s
    # pot
    d.polygon([(cx - 11 * s, 52 * s), (cx + 11 * s, 52 * s),
               (cx + 8 * s, 70 * s), (cx - 8 * s, 70 * s)], fill=C_PLANT_POT + (255,))
    d.polygon([(cx - 11 * s, 52 * s), (cx + 11 * s, 52 * s),
               (cx + 11 * s, 56 * s), (cx - 11 * s, 56 * s)], fill=C_PLANT_POT_D + (255,))
    # leaves (a few ellipses)
    leaves = [(-9, 30, 10, 26, C_PLANT_LEAF_D), (9, 32, 10, 24, C_PLANT_LEAF_D),
              (0, 16, 12, 30, C_PLANT_LEAF), (-7, 24, 9, 24, C_PLANT_LEAF),
              (7, 26, 9, 22, C_PLANT_LEAF)]
    for dx, ly, lw, lh, col in leaves:
        d.ellipse([cx + (dx - lw / 2) * s, ly * s, cx + (dx + lw / 2) * s, (ly + lh) * s],
                  fill=col + (255,))
    return finish(im), (w / 2, h)


def make_door():
    w, h, box_h = TILE_W, 80, 48
    im, anchor = _iso_box(w, h, box_h, C_DOOR_FRAME, (54, 61, 76), (44, 50, 63))
    # carve a glowing doorway onto the right-facing face
    d = ImageDraw.Draw(im)
    cx = w / 2
    top = h - box_h - TILE_H / 2
    d.polygon([(cx, top + 8), (cx + 20, top + 18), (cx + 20, h - 10), (cx, h - 2)],
              fill=C_DOOR_VOID)
    for i in range(6):
        a = 50 - i * 7
        d.polygon([(cx, top + 10 + i), (cx + 18 - i, top + 19 + i),
                   (cx + 18 - i, h - 12), (cx, h - 4)], outline=C_DOOR_GLOW + (max(0, a),))
    return im, anchor


def make_tile():
    # a small raised iso card; rendered tinted per tool category at runtime
    im, anchor = _iso_box(46, 44, 13, (236, 239, 247), (188, 194, 208),
                          (158, 164, 180), top_inset=3)
    return im, anchor


def make_slot():
    w, h = 56, 36
    im = _img(w, h)
    d = ImageDraw.Draw(im)
    s = SS
    cx, cy = (w / 2) * s, 18 * s
    # glowing ring pad, drawn flat on the floor
    for i in range(5, 0, -1):
        a = int(30 * (i / 5))
        _diamond(d, cx, cy, (40 + i * 4) * s, (20 + i * 2) * s, None,
                 outline=C_SLOT + (a,), ow=1)
    _diamond(d, cx, cy, 36 * s, 18 * s, C_SLOT + (40,), outline=C_SLOT + (160,), ow=1)
    return finish(im), (w / 2, 18)


SPRITES = {
    "floor": make_floor,
    "wall": make_wall,
    "pedestal": make_pedestal,
    "orb": make_orb,
    "plant": make_plant,
    "door": make_door,
    "slot": make_slot,
    "tile": make_tile,
}


def pack_atlas():
    """Render every sprite, pack into a single PNG row-by-row, return frames+anchors."""
    rendered = {name: fn() for name, fn in SPRITES.items()}
    pad = 2
    maxw = 256
    x = y = rowh = 0
    placements = {}
    for name, (im, anchor) in rendered.items():
        if x + im.width + pad > maxw:
            x = 0
            y += rowh + pad
            rowh = 0
        placements[name] = (x, y, im, anchor)
        x += im.width + pad
        rowh = max(rowh, im.height)
    atlas_w = maxw
    atlas_h = y + rowh + pad
    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    frames, anchors = {}, {}
    for name, (px, py, im, anchor) in placements.items():
        atlas.paste(im, (px, py))
        frames[name] = {"x": px, "y": py, "w": im.width, "h": im.height}
        anchors[name] = {"x": anchor[0] / im.width, "y": anchor[1] / im.height}
    atlas.save(os.path.join(HERE, "atlas.png"))
    return frames, anchors, (atlas_w, atlas_h)


# ── room layout (the "authoring") ────────────────────────────────────────────
COLS, ROWS = 7, 7


def build_scene(frames, anchors):
    tiles = []
    for gx in range(COLS):
        for gy in range(ROWS):
            tiles.append({"gridX": gx, "gridY": gy, "sprite": "floor"})

    props = []

    def add(pid, sprite, gx, gy, interactive=False, z=0):
        a = anchors[sprite]
        p = {"id": pid, "sprite": sprite, "gridX": gx, "gridY": gy,
             "anchorX": round(a["x"], 4), "anchorY": round(a["y"], 4)}
        if z:
            p["z"] = z
        if interactive:
            p["interactive"] = True
        props.append(p)

    # back walls (left edge gx=0 ; right edge gy=0), door breaks the right wall
    door_cell = (2, 0)
    for gy in range(ROWS):
        add(f"wall_l_{gy}", "wall", 0, gy)
    for gx in range(1, COLS):
        if (gx, 0) == door_cell:
            continue
        add(f"wall_r_{gx}", "wall", gx, 0)
    add("mcp_door_1", "door", door_cell[0], door_cell[1], interactive=True)

    # núcleo pedestal + floating orb (orb is the interactive core)
    add("nucleo_pedestal", "pedestal", 3, 1)
    add("nucleo_orb", "orb", 3, 1, interactive=True, z=1)

    # one tool-slot per work zone (interactive; light up when a capability is wired)
    add("slot_fuentes", "slot", 2, 4, interactive=True)
    add("slot_mesa", "slot", 3, 4, interactive=True)
    add("slot_entrega", "slot", 6, 4, interactive=True)

    # ambient plants (sway, non-interactive)
    add("plant_1", "plant", 1, 5)
    add("plant_2", "plant", 5, 5)

    zones = [
        {"id": "zone_nucleo", "gridX": 3, "gridY": 1, "w": 1, "h": 1, "role": "nucleo"},
        {"id": "zone_fuentes", "gridX": 1, "gridY": 3, "w": 2, "h": 3, "role": "fuentes"},
        {"id": "zone_mesa", "gridX": 3, "gridY": 3, "w": 2, "h": 2, "role": "mesa"},
        {"id": "zone_entrega", "gridX": 5, "gridY": 3, "w": 2, "h": 3, "role": "entrega"},
    ]

    scene = {
        "schemaVersion": "1.0.0",
        "meta": {
            "name": "Cuarto — sala base",
            "background": "#10131a",
        },
        "grid": {"cols": COLS, "rows": ROWS, "tileWidth": TILE_W, "tileHeight": TILE_H},
        "tiles": tiles,
        "props": props,
        "zones": zones,
        "atlas": {"image": "atlas.png", "frames": frames},
    }
    return scene


def main():
    frames, anchors, size = pack_atlas()
    scene = build_scene(frames, anchors)
    with open(os.path.join(HERE, "cuarto.scene.json"), "w") as f:
        json.dump(scene, f, indent=2)
    print(f"atlas.png  {size[0]}x{size[1]}  ({len(frames)} frames)")
    print(f"cuarto.scene.json  {len(scene['tiles'])} tiles, "
          f"{len(scene['props'])} props, {len(scene['zones'])} zones")


if __name__ == "__main__":
    main()
