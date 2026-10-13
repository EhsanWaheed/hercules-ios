#!/usr/bin/env python3
"""Cut the launcher's artwork out of the game's own assets.

The launcher is styled after the game's title menus (docs: design.md). It
uses the extracted game art from the hercules decomp project
(~/psx-decomp/hercules/assets, made from the user's own disc) and is never
committed: output goes to launcher/web/assets/ (git-ignored).

- backgrounds: TI_TME (main menu with logo), TI_TPS_0_0/_1 (Meg's room and
  its light shafts), TI_T03 (dark red plaster), TI_TSE* (level frescoes)
- sprites (SD4 = TITLE): menu with each item highlighted, muses, Megara,
  German captions, level names
- font: the game's pause-menu font from the HUD texture page (captured by
  hercules/tools/hud_texpack.py) in yellow / orange / blue, with digits and
  the few missing letters assembled from existing glyphs

    ~/psx-decomp/.venv/bin/python launcher/build_assets.py
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERC = Path.home() / "psx-decomp/hercules"
IMAGES = HERC / "assets/images"
SPRITES = HERC / "assets/sprites"
OUT = Path(__file__).resolve().parent / "web/assets"


def save(img, rel):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p, optimize=True)
    return rel


def sprite(path):
    return Image.open(SPRITES / path).convert("RGBA")


def crop_alpha(img):
    box = img.getbbox()
    return img.crop(box) if box else img


# ------------------------------------------------------------- backgrounds
def backgrounds(manifest):
    bg = {}
    for key, name in [("menu", "TI_TME_0"), ("room", "TI_TPS_0_0"), ("beams", "TI_TPS_0_1"),
                      ("plaster", "TI_T03_0"), ("plaster2", "TI_T02_0"), ("teal", "TI_T09_0"),
                      ("keys", "TI_T17_0")]:
        bg[key] = save(Image.open(IMAGES / f"{name}.png").convert("RGB"), f"bg/{key}.png")
    frescoes = {}
    for i in range(1, 12):
        p = IMAGES / f"TI_TSE{i}_0.png"
        if p.exists():
            frescoes[str(i)] = save(Image.open(p).convert("RGB"), f"bg/fresco{i}.png")
    manifest["bg"] = bg
    manifest["fresco"] = frescoes


# ----------------------------------------------------------------- sprites
def sprites(manifest):
    sp = {}
    # main menu, one image per highlighted item (f0002..f0005); help line at the bottom
    sp["menu"] = [save(sprite(f"SD4/S4_1/f{n:04d}.png"), f"sprite/menu{i}.png")
                  for i, n in enumerate(range(2, 6))]
    # muses (15-frame idle loops) and Megara
    for key, folder in [("muse_a", "S4_5"), ("muse_b", "S4_8"), ("muse_c", "S4_15")]:
        frames = sorted((SPRITES / "SD4" / folder).glob("f*.png"))
        frames = [f for f in frames if Image.open(f).size[1] >= 120]
        sp[key] = [save(sprite(f"SD4/{folder}/{f.name}"), f"sprite/{key}_{i:02d}.png")
                   for i, f in enumerate(frames)]
    meg = sorted((SPRITES / "SD4/S4_3").glob("f*.png"))[1:25]
    sp["meg"] = [save(sprite(f"SD4/S4_3/{f.name}"), f"sprite/meg_{i:02d}.png") for i, f in enumerate(meg)]
    # captions (SD4/S4_16 = memory card texts, S4_3 f0001 = Meg title + help)
    cap = {}
    s416 = {"load": 1, "save": 2, "wait": 3, "select_help": 8, "yes": 12, "no": 14,
            "quit_help": 30, "empty": 31, "load_help": 35}
    for key, n in s416.items():
        cap[key] = save(crop_alpha(sprite(f"SD4/S4_16/f{n:04d}.png")), f"sprite/cap_{key}.png")
    megsheet = sprite("SD4/S4_3/f0001.png")          # 296 x 216: title on top, help at the bottom
    half = megsheet.height // 2
    cap["meg_title"] = save(crop_alpha(megsheet.crop((0, 0, megsheet.width, half))), "sprite/cap_meg_title.png")
    cap["meg_help"] = save(crop_alpha(megsheet.crop((0, half, megsheet.width, megsheet.height))),
                           "sprite/cap_meg_help.png")
    cap["back_help"] = save(crop_alpha(sprite("SD4/S4_2/f0001.png")), "sprite/cap_back_help.png")
    sp["caption"] = cap
    # level names (SD4/S4_16 f0016..f0025), keyed by the game's level number
    names = {"0": 16, "1": 17, "2": 17, "3": 18, "5": 19, "6": 20, "7": 21, "8": 22, "9": 23,
             "10": 24, "11": 25}
    sp["level_name"] = {lv: save(crop_alpha(sprite(f"SD4/S4_16/f{n:04d}.png")), f"sprite/level{lv}.png")
                        for lv, n in names.items()}
    manifest["sprite"] = sp


# -------------------------------------------------------------------- font
def font(manifest):
    """Pause-menu font from the HUD page (4-bit, palettes at (352,32..39))."""
    sys.path.insert(0, str(HERC / "tools"))
    import hud_texpack as hud
    caps = sorted((HERC / "assets/hud/captures").glob("L*.npz"))
    cap = next(np.load(c) for c in caps if "clut_rows" in np.load(c))
    idx = hud.indices(cap["page"])
    pal = cap["clut_rows"]
    mask = (pal[3][idx] != 0)                      # palette 3: bright yellow font

    def segment(y0, y1, x0, x1):
        cols = mask[y0:y1, x0:x1].any(0)
        boxes, start = [], None
        for x, on in enumerate(list(cols) + [False]):
            if on and start is None:
                start = x
            elif not on and start is not None:
                boxes.append((x0 + start, x0 + x))
                start = None
        return boxes

    def band(x0, x1, y_from, y_to):
        rows = np.nonzero(mask[y_from:y_to, x0:x1].any(1))[0]
        return y_from + rows[0], y_from + rows[-1] + 1

    glyphs = {}
    # two letter rows between x 96 and 232
    # (left of x 96 a cloud ornament reaches into the second row)
    for text, (yf, yt), xr in [("ABCDEFGHIJKL?", (42, 59), 232), ("MNOPRSTUWZ1", (59, 76), 238)]:
        y0, y1 = band(96, xr, yf, yt)
        boxes = [b for b in segment(y0, y1, 96, xr) if b[1] - b[0] >= 3]
        while len(boxes) < len(text):             # touching letters (F+G, M+N): split the
            i = max(range(len(boxes)), key=lambda k: boxes[k][1] - boxes[k][0])  # widest
            a, b = boxes[i]                       # at its least-inked column
            ink = mask[y0:y1, a + 4:b - 4].sum(0)
            cut_x = a + 4 + int(np.argmin(ink))
            boxes[i:i + 1] = [(a, cut_x), (cut_x + 1, b)]
        if len(boxes) != len(text):
            raise SystemExit(f"font row {text}: {len(boxes)} glyphs found")
        for ch, (x0, x1) in zip(text, boxes):
            glyphs[ch] = (x0, y0, x1, y1)
    height = max(g[3] - g[1] for g in glyphs.values())
    # small digits 0..9: pairs at x 232..238 / 240..246, rows 1..39 (8 rows each)
    digits = {}
    for i in range(5):
        y0 = 1 + 8 * i
        for j, x0 in enumerate((232, 240)):
            digits[str(2 * i + j)] = (x0, y0, x0 + 6, y0 + 7)

    corners = [idx[y0, x0] for (x0, y0, _, _) in digits.values()] + \
              [idx[y1 - 1, x1 - 1] for (_, _, x1, y1) in digits.values()]
    digit_bg = np.bincount(corners).argmax()       # the tile colour behind every digit
    TOP = 3                                        # room above capitals for umlaut dots
    H = height + TOP

    def cut(box, palette, cell=False):
        x0, y0, x1, y1 = box
        sub = idx[y0:y1, x0:x1]
        img = hud.rgba(sub, pal[palette])
        if cell:                                   # digits sit on a filled tile colour
            img[sub == digit_bg] = 0
        return img

    def pad_to(img, h):                            # bottom-align to the line height
        out = np.zeros((h, img.shape[1], 4), np.uint8)
        img = img[-h:]
        out[h - img.shape[0]:] = img
        return out

    def build(palette):
        g = {ch: pad_to(cut(b, palette), H) for ch, b in glyphs.items()}
        A, O, K, I = g["A"], g["O"], g["K"], g["I"]
        ink = A[..., 3] > 0
        rows = np.nonzero(ink.any(1))[0]
        top, bottom = rows[0], rows[-1]
        mid = (top + bottom) // 2
        fill = A[bottom, np.nonzero(ink[bottom])[0][0]]          # outline colour
        opaque = A[ink]
        keys, counts = np.unique(opaque.view(np.uint32), return_counts=True)
        lum = lambda c: int(c[0]) * 3 + int(c[1]) * 6 + int(c[2])
        cands = [np.frombuffer(np.uint32(k).tobytes(), np.uint8) for k in keys[np.argsort(-counts)][:4]]
        face = max(cands, key=lum)                 # brightest of the main colours

        def runs(row):
            on = list(row[..., 3] > 0) + [False]
            out, st = [], None
            for x, v in enumerate(on):
                if v and st is None: st = x
                elif not v and st is not None: out.append((st, x)); st = None
            return out

        # digits: index 1 is the face, index 10 the shadow -> the font's own colours,
        # doubled to the letter height
        for d, (x0, y0, x1, y1) in digits.items():
            sub = idx[y0:y1, x0:x1]
            im = np.zeros(sub.shape + (4,), np.uint8)
            im[sub == 10] = fill
            im[sub == 1] = face
            im = im.repeat(2, 0).repeat(2, 1)
            g[d] = pad_to(im[-height:], H)

        def stroke(w, segments):
            """Pixel-art letter from line segments: 4-px face, 1-px outline."""
            G = np.zeros((H, w, 4), np.uint8)
            face_m = np.zeros((H, w), bool)
            for (xa, ya, xb, yb) in segments:
                n = int(max(abs(xb - xa), abs(yb - ya)) * 2) + 1
                for t in np.linspace(0, 1, n):
                    cx, cy = xa + (xb - xa) * t, ya + (yb - ya) * t
                    for oy in range(-1, 2):
                        for ox in range(-1, 2):
                            yy, xx = int(round(cy + oy)), int(round(cx + ox))
                            if 0 <= yy < H and 0 <= xx < w:
                                face_m[yy, xx] = True
            edge = np.zeros_like(face_m)
            for oy in (-1, 0, 1):
                for ox in (-1, 0, 1):
                    edge |= np.roll(np.roll(face_m, oy, 0), ox, 1)
            G[edge] = fill
            G[face_m] = face
            return G

        w = A.shape[1]
        g["V"] = stroke(w, [(1.5, top + 1, w / 2 - 0.5, bottom - 1), (w - 2.5, top + 1, w / 2 - 0.5, bottom - 1)])
        g["X"] = stroke(w, [(1.5, top + 1, w - 2.5, bottom - 1), (w - 2.5, top + 1, 1.5, bottom - 1)])
        aw = w - 2
        g["<"] = stroke(aw, [(aw - 2.5, top + 2, 1.5, mid), (1.5, mid, aw - 2.5, bottom - 2)])
        g[">"] = stroke(aw, [(1.5, top + 2, aw - 2.5, mid), (aw - 2.5, mid, 1.5, bottom - 2)])
        g[":"] = np.zeros((H, 4, 4), np.uint8)
        for yy in (mid - 3, bottom - 2):
            g[":"][yy:yy + 3, 0:4] = fill
            g[":"][yy + 1:yy + 2, 1:3] = face
        g["Y"] = stroke(w, [(1.5, top + 1, w / 2 - 0.5, mid), (w - 2.5, top + 1, w / 2 - 0.5, mid),
                            (w / 2 - 0.5, mid, w / 2 - 0.5, bottom - 1)])
        Q = O.copy()
        Q[bottom - 3:bottom + 1, -5:] = np.maximum(Q[bottom - 3:bottom + 1, -5:],
                                                   O[bottom - 3:bottom + 1, :5][:, ::-1])
        g["Q"] = Q
        g[" "] = np.zeros((H, 6, 4), np.uint8)
        g["-"] = np.zeros((H, 7, 4), np.uint8)
        g["-"][mid - 1:mid + 2, 0:7] = fill
        g["-"][mid:mid + 1, 1:6] = face
        g["."] = np.zeros((H, 4, 4), np.uint8)
        g["."][bottom - 2:bottom + 1, 0:4] = fill
        g["."][bottom - 1:bottom, 1:3] = face
        for base, new in (("A", "Ä"), ("O", "Ö"), ("U", "Ü")):
            G = g[base].copy()
            w = G.shape[1]
            for dx in (w // 3 - 1, 2 * w // 3 - 1):
                G[top - 3:top - 1, dx:dx + 3] = fill
                G[top - 3:top - 2, dx + 1:dx + 2] = face
            g[new] = G
        return g

    variants = {"yellow": 3, "orange": 4}
    atlases, meta = {}, {}
    for name, palette in variants.items():
        g = build(palette)
        order = sorted(g)
        width = sum(g[c].shape[1] + 1 for c in order)
        sheet = np.zeros((H, width, 4), np.uint8)
        x = 0
        for c in order:
            w = g[c].shape[1]
            sheet[:, x:x + w] = g[c]
            meta[c] = [x, w]
            x += w + 1
        atlases[name] = sheet
    # blue = the yellow glyphs recoloured toward the menu blue (#8CB9F3) by luminance
    y = atlases["yellow"].astype(np.float32)
    lum = (0.3 * y[..., 0] + 0.59 * y[..., 1] + 0.11 * y[..., 2]) / 255.0
    blue = np.zeros_like(atlases["yellow"])
    for c, (lo, hi) in enumerate(((20, 0x8C), (40, 0xB9), (90, 0xF3))):
        blue[..., c] = np.clip(lo + (hi - lo) * np.clip(lum * 1.25, 0, 1), 0, 255)
    blue[..., 3] = atlases["yellow"][..., 3]
    atlases["blue"] = blue
    files = {k: save(Image.fromarray(v, "RGBA"), f"font/{k}.png") for k, v in atlases.items()}
    manifest["font"] = {"height": int(H), "glyphs": meta, "files": files}


def main():
    if not IMAGES.exists() or not SPRITES.exists():
        sys.exit(f"missing game assets in {HERC / 'assets'} (run the decomp extract tools first)")
    if OUT.exists():
        shutil.rmtree(OUT)
    manifest = {}
    backgrounds(manifest)
    sprites(manifest)
    font(manifest)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    (OUT / "manifest.js").write_text("window.HERC_ASSETS = " + json.dumps(manifest, ensure_ascii=False) + ";\n")
    print(f"{OUT}: {sum(1 for _ in OUT.rglob('*.png'))} images")


if __name__ == "__main__":
    main()
