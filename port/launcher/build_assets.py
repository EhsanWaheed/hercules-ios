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
  hercules/tools/hud_texpack.py) in yellow / orange / blue; digits, accents,
  pad symbols and the few missing letters are drawn in the same style

Everything is written at SCALE (4) times the PAL size: sprites come from
the palettized DAT2 upscale (assets/sprites_hd/DAT2-schutz), backgrounds
and the font atlas go through the same model here (cached in
assets/images_hd/DAT2). Without the model the SD art is enlarged instead.

    ~/psx-decomp/.venv/bin/python launcher/build_assets.py [--sd]
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

PORT = Path(__file__).resolve().parent.parent


def find_decomp():
    """The decomp checkout: $HERC_DECOMP, ../decomp (combined repo) or ~/psx-decomp/hercules."""
    import os
    for d in (os.environ.get("HERC_DECOMP"), PORT.parent / "decomp", Path.home() / "psx-decomp/hercules"):
        if d and (Path(d) / "tools/sprites.py").exists():
            return Path(d)
    sys.exit("decomp tools not found (set HERC_DECOMP)")


HERC = find_decomp()
IMAGES = HERC / "assets/images"
SPRITES = HERC / "assets/sprites"
# HD title sprites: our hand-made set, else the one the HD pack build made from the disc
HD_WORK = Path.home() / ".local/share/hercules-recompiled/hd-work/assets/sprites_hd/final"
SPRITES_HD = next((d for d in (HERC / "assets/sprites_hd/DAT2-schutz", HD_WORK) if (d / "SD4").is_dir()),
                  HERC / "assets/sprites_hd/DAT2-schutz")
IMAGES_HD = HERC / "assets/images_hd/DAT2"
OUT = Path(__file__).resolve().parent / "web/assets"


def disc_cue():
    """The disc named in the port's game.toml (relative paths: from the port folder)."""
    import tomllib
    disc = tomllib.loads((PORT / "game.toml").read_text())["game"]["disc"]
    p = Path(disc)
    return p if p.is_absolute() else PORT / p


def prepare():
    """Make the inputs this script reads from the player's disc when they are missing:
    extracted files, full-screen pictures, title sprites, HUD strip (font)."""
    py, tools = sys.executable, HERC / "tools"
    if not (HERC / "files/EX/TITLE.").exists():
        print("extracting the disc ...", flush=True)
        subprocess.run([py, tools / "iso_extract.py", disc_cue(), HERC / "files"], check=True)
    if not (IMAGES / "TI_TME_0.png").exists():
        subprocess.run([py, tools / "fullscreen2png.py", IMAGES,
                        *sorted(str(p) for p in (HERC / "files/TI").iterdir())], check=True)
    if not (SPRITES / "SD4").is_dir():
        src = sorted(p.relative_to(HERC).as_posix() for p in (HERC / "files/SD4").glob("S*"))
        subprocess.run([py, tools / "sprites.py", "dump", "assets/sprites", *src], cwd=HERC, check=True)
    if not list((HERC / "assets/hud/captures").glob("*.npz")):
        if not (tools / "native/libxxh3.so").exists():
            subprocess.run(["make", "tools/native/libxxh3.so"], cwd=HERC, check=True)
        subprocess.run([py, tools / "hud_texpack.py", "from-disc", HERC / "files",
                        "--work", HERC / "assets/hud"], check=True)
MODEL = Path.home() / "psx-decomp/models/IllustrationJaNai/4x_IllustrationJaNai_V1_DAT2_190k.pth"
MODEL_PY = Path.home() / ".config/chaiNNer/python/python/bin/python3.11"
SCALE = 4
HD = "--sd" not in sys.argv


def model_ok():
    return HD and MODEL.exists() and MODEL_PY.exists()


def upscale(images):
    """{name: RGBA array} -> {name: 4x RGBA array} through the DAT2 model."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in", Path(tmp) / "out"
        src.mkdir()
        for name, im in images.items():
            Image.fromarray(im, "RGBA").save(src / f"{name}.png")
        subprocess.run([str(MODEL_PY), str(HERC / "tools/upscale_model.py"), str(MODEL), str(src), str(dst)],
                       check=True, stdout=subprocess.DEVNULL)
        return {name: np.asarray(Image.open(dst / f"{name}.png").convert("RGBA")) for name in images}


def enlarge(img):
    return img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST)


def save(img, rel):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p, optimize=True)
    return rel


def sprite(path):
    """A title sprite at SCALE x (HD upscale if there is one)."""
    hd = SPRITES_HD / path
    if HD and hd.exists():
        img = Image.open(hd).convert("RGBA")
        if img.width == Image.open(SPRITES / path).width * SCALE:
            return img
    return enlarge(Image.open(SPRITES / path).convert("RGBA"))


def crop_alpha(img):
    box = img.getchannel("A").point(lambda a: 255 if a >= 24 else 0).getbbox()
    if not box:
        return img
    x0, y0, x1, y1 = box                      # whole PAL pixels, so the layout stays on the grid
    x0, y0 = x0 // SCALE * SCALE, y0 // SCALE * SCALE
    x1, y1 = -(-x1 // SCALE) * SCALE, -(-y1 // SCALE) * SCALE
    return img.crop((x0, y0, x1, y1))


def picture(name):
    """A full-screen picture from assets/images at SCALE x (DAT2, cached)."""
    sd = IMAGES / f"{name}.png"
    hd = IMAGES_HD / f"{name}.png"
    if model_ok() and not (hd.exists() and hd.stat().st_mtime >= sd.stat().st_mtime):
        IMAGES_HD.mkdir(parents=True, exist_ok=True)
        up = upscale({name: np.asarray(Image.open(sd).convert("RGBA"))})[name]
        Image.fromarray(up, "RGBA").convert("RGB").save(hd)
    if HD and hd.exists():
        return Image.open(hd).convert("RGB")
    return enlarge(Image.open(sd).convert("RGB"))


# ------------------------------------------------------------- backgrounds
def backgrounds(manifest):
    bg = {}
    for key, name in [("menu", "TI_TME_0"), ("room", "TI_TPS_0_0"), ("beams", "TI_TPS_0_1"),
                      ("plaster", "TI_T03_0"), ("plaster2", "TI_T02_0"), ("teal", "TI_T09_0"),
                      ("keys", "TI_T17_0")]:
        bg[key] = save(picture(name), f"bg/{key}.png")
    frescoes = {}
    for i in range(1, 12):
        if (IMAGES / f"TI_TSE{i}_0.png").exists():
            frescoes[str(i)] = save(picture(f"TI_TSE{i}_0"), f"bg/fresco{i}.png")
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
        frames = [f for f in frames if Image.open(f).size[1] >= 120]          # SD sizes
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
    caps = sorted((HERC / "assets/hud/captures").glob("*.npz"))
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
    TOP = 6                                        # room above capitals for accents
    BOT = 3                                        # and below the baseline for the cedilla
    H = TOP + height + BOT

    def cut(box, palette):
        x0, y0, x1, y1 = box
        return hud.rgba(idx[y0:y1, x0:x1], pal[palette])

    def pad_to(img):                               # bottom-align on the baseline
        out = np.zeros((H, img.shape[1], 4), np.uint8)
        img = img[-height:]
        out[H - BOT - img.shape[0]:H - BOT] = img
        return out

    def build(palette):
        g = {ch: pad_to(cut(b, palette)) for ch, b in glyphs.items()}
        A = g["A"]
        ink = A[..., 3] > 0
        rows = np.nonzero(ink.any(1))[0]
        top, bottom = rows[0], rows[-1]
        mid = (top + bottom) // 2
        fill = A[bottom, np.nonzero(ink[bottom])[0][0]]          # outline colour
        keys, counts = np.unique(A[ink].view(np.uint32), return_counts=True)
        lum = lambda c: int(c[0]) * 3 + int(c[1]) * 6 + int(c[2])
        cands = [np.frombuffer(np.uint32(k).tobytes(), np.uint8) for k in keys[np.argsort(-counts)][:4]]
        face = max(cands, key=lum)                 # brightest of the main colours

        def paint(face_m):
            """Face pixels -> glyph with the font's 1-px dark outline."""
            G = np.zeros(face_m.shape + (4,), np.uint8)
            edge = np.zeros_like(face_m)
            for oy in (-1, 0, 1):
                for ox in (-1, 0, 1):
                    edge |= np.roll(np.roll(face_m, oy, 0), ox, 1)
            G[edge] = fill
            G[face_m] = face
            return G

        def stroke(w, lines, t=3, y0=None, y1=None):
            """Pixel-art glyph from polylines in a unit box (0..1, top..baseline),
            drawn with a t x t pixel brush (3 = the letters' face, 1 = thin)."""
            r0, r1 = -(t // 2), t - t // 2
            y0 = top - r0 if y0 is None else y0
            y1 = bottom - r1 + 1 if y1 is None else y1
            xa_, xb_ = 1 - r0, w - 1 - r1
            m = np.zeros((H, w), bool)
            for line in lines:
                pts = [(xa_ + (xb_ - xa_) * u, y0 + (y1 - y0) * v) for u, v in line]
                for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
                    n = int(max(abs(xb - xa), abs(yb - ya)) * 3) + 1
                    for t in np.linspace(0, 1, n):
                        cx, cy = xa + (xb - xa) * t, ya + (yb - ya) * t
                        for oy in range(r0, r1):
                            for ox in range(r0, r1):
                                yy, xx = int(round(cy + oy)), int(round(cx + ox))
                                if 0 <= yy < H and 0 <= xx < w:
                                    m[yy, xx] = True
            return paint(m)

        w = A.shape[1]
        g["V"] = stroke(w, [[(0, 0), (0.5, 1), (1, 0)]])
        g["X"] = stroke(w, [[(0, 0), (1, 1)], [(1, 0), (0, 1)]])
        g["Y"] = stroke(w, [[(0, 0), (0.5, 0.5), (1, 0)], [(0.5, 0.5), (0.5, 1)]])
        aw = w - 2
        g["<"] = stroke(aw, [[(1, 0.1), (0, 0.5), (1, 0.9)]])
        g[">"] = stroke(aw, [[(0, 0.1), (1, 0.5), (0, 0.9)]])
        g["/"] = stroke(aw, [[(1, 0), (0, 1)]])
        O = g["O"]
        Q = O.copy()
        Q[bottom - 3:bottom + 1, -5:] = np.maximum(Q[bottom - 3:bottom + 1, -5:],
                                                   O[bottom - 3:bottom + 1, :5][:, ::-1])
        g["Q"] = Q

        # digits in the letters' angular style, a little narrower than A
        dw = w
        c = 0.25
        box = [(c, 0), (1 - c, 0), (1, c), (1, 1 - c), (1 - c, 1), (c, 1), (0, 1 - c), (0, c), (c, 0)]
        digits = {
            "0": [box],
            "1": [[(0.15, 0.25), (0.55, 0)], [(0.55, 0), (0.55, 1)], [(0.15, 1), (0.95, 1)]],
            "2": [[(0, c), (c, 0), (1 - c, 0), (1, c), (1, 0.35), (0, 1), (1, 1)]],
            "3": [[(0, 0), (1, 0), (0.4, 0.42), (1 - c, 0.42), (1, 0.42 + c), (1, 1 - c), (1 - c, 1), (0, 1)]],
            "4": [[(0.75, 1), (0.75, 0), (0, 0.68), (1, 0.68)]],
            "5": [[(1, 0), (0, 0), (0, 0.42), (1 - c, 0.42), (1, 0.42 + c), (1, 1 - c), (1 - c, 1), (0, 1)]],
            "6": [[(1, 0), (c, 0), (0, c), (0, 1 - c), (c, 1), (1 - c, 1), (1, 1 - c), (1, 0.45 + c),
                   (1 - c, 0.45), (0, 0.45)]],
            "7": [[(0, 0), (1, 0), (0.3, 1)]],
            "8": [[(c, 0.45), (0, 0.45 - c), (0, c), (c, 0), (1 - c, 0), (1, c), (1, 0.45 - c), (1 - c, 0.45),
                   (c, 0.45), (0, 0.45 + c), (0, 1 - c), (c, 1), (1 - c, 1), (1, 1 - c), (1, 0.45 + c),
                   (1 - c, 0.45)]],
            "9": [[(0, 1), (1 - c, 1), (1, 1 - c), (1, c), (1 - c, 0), (c, 0), (0, c), (0, 0.55 - c),
                   (c, 0.55), (1, 0.55)]],
        }
        for d, lines in digits.items():
            g[d] = stroke(dw, lines, t=2)

        def blank(wd):
            return np.zeros((H, wd, 4), np.uint8)

        def marks(wd, face_pts):
            m = np.zeros((H, wd), bool)
            for (yy, xx) in face_pts:
                m[yy, xx] = True
            return paint(m)

        g[" "] = blank(9)
        dot = [(bottom - 1, 1), (bottom - 1, 2), (bottom, 1), (bottom, 2)]
        g["."] = marks(4, dot)
        g[","] = marks(5, dot + [(bottom + 1, 2), (bottom + 2, 1)])
        g[":"] = marks(4, dot + [(mid - 2, 1), (mid - 2, 2), (mid - 1, 1), (mid - 1, 2)])
        g["'"] = marks(4, [(top, 1), (top, 2), (top + 1, 1), (top + 1, 2), (top + 2, 1)])
        g["!"] = marks(4, dot + [(y, x) for y in range(top, bottom - 3) for x in (1, 2)])
        g["¡"] = g["!"][::-1].copy()
        g["¡"] = np.roll(g["¡"], (top + bottom) - (H - 1), 0)          # flip about the letter band
        g["¿"] = np.roll(g["?"][::-1, ::-1].copy(), (top + bottom) - (H - 1), 0)
        g["-"] = marks(7, [(mid, x) for x in range(1, 6)])
        # percent: two small rings and a slash
        ring = lambda y0, x0: [(y0, x0), (y0, x0 + 1), (y0 + 1, x0), (y0 + 1, x0 + 1)]
        g["%"] = np.maximum(stroke(w, [[(1, 0.05), (0, 0.95)]], t=1),
                            marks(w, ring(top + 1, 2) + ring(bottom - 2, w - 4)))
        g["+"] = marks(9, [(mid, x) for x in range(1, 8)] + [(y, 4) for y in range(mid - 3, mid + 4)])

        # pad buttons, thin like the game's own captions
        sw = w
        g["△"] = stroke(sw, [[(0.5, 0), (1, 1), (0, 1), (0.5, 0)]], t=1)
        g["□"] = stroke(sw, [[(0.08, 0.08), (0.92, 0.08), (0.92, 1), (0.08, 1), (0.08, 0.08)]], t=1)
        g["○"] = stroke(sw, [[(0.3, 0), (0.7, 0), (1, 0.3), (1, 0.7), (0.7, 1), (0.3, 1), (0, 0.7),
                              (0, 0.3), (0.3, 0)]], t=1)

        # accents: face pixels relative to (top - 5, left of the mark)
        ACC = {
            "acute": [(0, 3), (0, 4), (1, 2), (1, 3), (2, 1), (2, 2)],
            "grave": [(0, 1), (0, 2), (1, 2), (1, 3), (2, 3), (2, 4)],
            "circ": [(0, 2), (0, 3), (1, 1), (1, 4), (2, 0), (2, 5)],
            "tilde": [(1, 1), (1, 2), (1, 5), (2, 0), (2, 3), (2, 4)],
        }

        def accent(base, kind):
            G = g[base]
            bw = G.shape[1]
            if kind == "uml":
                G = G.copy()
                for dx in (bw // 3 - 1, 2 * bw // 3 - 1):
                    G[top - 4:top - 2, dx:dx + 3] = fill
                    G[top - 4:top - 3, dx + 1:dx + 2] = face
                return G
            pts = ACC[kind]
            mw = max(x for _, x in pts) + 3
            wd = max(bw, mw)
            out = blank(wd)
            ox = (wd - bw) // 2
            out[:, ox:ox + bw] = G
            m0 = (wd - mw) // 2 + 1
            mk = marks(wd, [(top - 5 + y, m0 + x) for y, x in pts])
            on = mk[..., 3] > 0
            out[on] = mk[on]
            return out

        for ch, base, kind in [("Ä", "A", "uml"), ("Ö", "O", "uml"), ("Ü", "U", "uml"), ("Ë", "E", "uml"),
                               ("Ï", "I", "uml"),
                               ("Á", "A", "acute"), ("É", "E", "acute"), ("Í", "I", "acute"),
                               ("Ó", "O", "acute"), ("Ú", "U", "acute"),
                               ("À", "A", "grave"), ("È", "E", "grave"), ("Ì", "I", "grave"),
                               ("Ò", "O", "grave"), ("Ù", "U", "grave"),
                               ("Â", "A", "circ"), ("Ê", "E", "circ"), ("Î", "I", "circ"),
                               ("Ô", "O", "circ"), ("Û", "U", "circ"), ("Ñ", "N", "tilde")]:
            g[ch] = accent(base, kind)
        C = g["C"].copy()                          # cedilla below the baseline
        cx = C.shape[1] // 2
        ced = marks(C.shape[1], [(bottom + 1, cx), (bottom + 2, cx), (bottom + 2, cx - 1)])
        on = ced[..., 3] > 0
        C[on] = ced[on]
        g["Ç"] = C
        return g

    GAP = 6                                        # transparent columns between glyphs (model bleed)
    variants = {"yellow": 3, "orange": 4}
    atlases, meta = {}, {}
    for name, palette in variants.items():
        g = build(palette)
        order = sorted(g)
        width = sum(g[c].shape[1] + GAP for c in order) + GAP
        sheet = np.zeros((H, width, 4), np.uint8)
        x = GAP
        for c in order:
            w = g[c].shape[1]
            sheet[:, x:x + w] = g[c]
            meta[c] = [x, w]
            x += w + GAP
        atlases[name] = np.pad(sheet, ((GAP, GAP), (0, 0), (0, 0)))
    if model_ok():
        sys.path.insert(0, str(HERC / "tools"))
        from sprite_palettize import palettize
        up = upscale(atlases)
        hd = {k: palettize(up[k], atlases[k], radius=1, restore="center", alpha_cut=128, protect=2)
              for k in atlases}
    else:
        hd = {k: v.repeat(SCALE, 0).repeat(SCALE, 1) for k, v in atlases.items()}
    # blue = the yellow glyphs recoloured toward the menu blue (#8CB9F3) by luminance
    y = hd["yellow"].astype(np.float32)
    lum = (0.3 * y[..., 0] + 0.59 * y[..., 1] + 0.11 * y[..., 2]) / 255.0
    blue = np.zeros_like(hd["yellow"])
    for c, (lo, hi) in enumerate(((20, 0x8C), (40, 0xB9), (90, 0xF3))):
        blue[..., c] = np.clip(lo + (hi - lo) * np.clip(lum * 1.25, 0, 1), 0, 255)
    blue[..., 3] = hd["yellow"][..., 3]
    hd["blue"] = blue
    files = {k: save(Image.fromarray(np.ascontiguousarray(v), "RGBA"), f"font/{k}.png") for k, v in hd.items()}
    # glyph boxes in PAL pixels: [x, width]; rows GAP .. GAP + height of the atlas
    manifest["font"] = {"height": int(H), "top": GAP, "baseline": int(H - BOT), "glyphs": meta, "files": files}


def main():
    prepare()
    if OUT.exists():
        shutil.rmtree(OUT)
    manifest = {"scale": SCALE}
    backgrounds(manifest)
    sprites(manifest)
    font(manifest)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    (OUT / "manifest.js").write_text("window.HERC_ASSETS = " + json.dumps(manifest, ensure_ascii=False) + ";\n")
    print(f"{OUT}: {sum(1 for _ in OUT.rglob('*.png'))} images")


if __name__ == "__main__":
    main()
