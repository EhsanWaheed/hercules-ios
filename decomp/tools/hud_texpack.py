#!/usr/bin/env python3
"""HD replacements for the in-game HUD (clouds, health bar, medallions, font).

The HUD is not a sprite file: it sits in the top rows of the 4-bit texture
page at VRAM (320,0) (64 words x 256 rows), with its palettes at (352,32),
(352,33) and (352,34). The level texture upload covers the same page and the
game overwrites the HUD rows afterwards, so no upload identity matches it.
DuckStation-format `texpage` names do: they hash a chosen sub-rectangle of
the page as it is in VRAM when drawn, plus the palette. Parts compose, so

- each captured page is upscaled whole per palette (no seams) and cut into
  16x8-texel tiles, each named by its own hash: a level that changes part
  of the page (other glyphs, bar colours) still matches every tile it keeps;
- the two 24x24 medallion slots at (0,56) and (24,56), palette 34, get one
  image per animation frame: the game writes the spinning medallion (13
  frames) and the current weapon icon into VRAM while playing.

Names: texpage-P4-<xxh3(rect words)>-<xxh3(16 CLUT words)>-64x256-x-y-wxh-P0-15

    # 1. read page, palettes and medallion frames from the debug build, once
    #    per level (--name L0 .. L11; captures are combined in step 2)
    ~/psx-decomp/.venv/bin/python tools/hud_texpack.py capture --seconds 15 --name L1
    # 2. upscale (IllustrationJaNai DAT2, chaiNNer's Python) + palettize, write
    ~/psx-decomp/.venv/bin/python tools/hud_texpack.py build PACK_DIR

Without a running game: the whole HUD strip ships on the disc. STP/STP1
(ENGINE1 levels) and STP/STP2 (ENGINE3 levels 2, 8, 10) are the 64x512-word
VRAM column at x 320: rows 0..95 are the HUD page (rows 56..79 are the two
slots the game fills at run time), the palettes sit at (352, 32..39), and
every medallion / weapon frame is a 24x24 cell of the grid from row 80,
x every 6 words (checked against all captures). `from-disc` writes one
capture per STP file with every non-empty grid cell as a slot frame:

    python3 tools/hud_texpack.py from-disc FILES_DIR [--work DIR]

Work files: assets/hud/ (captures/, orig/, raw/, pack/).
"""
import argparse
import ctypes
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sprite_palettize import palettize  # noqa: E402

ROOT = HERE.parent
WORK = ROOT / "assets/hud"
PAGE_X, PAGE_Y, ROWS = 320, 0, 96
CLUTS = {"frame": (352, 32), "bar": (352, 33), "medal": (352, 34)}
SLOTS = [(0, 56, 24, 24), (24, 56, 24, 24)]
STATIC_CLUTS = ("frame", "bar")
SLOT_CLUTS = ("medal",)
MODEL = Path.home() / "psx-decomp/models/IllustrationJaNai/4x_IllustrationJaNai_V1_DAT2_190k.pth"
MODEL_PY = Path.home() / ".config/chaiNNer/python/python/bin/python3.11"

_lib = ctypes.CDLL(str(HERE / "native/libxxh3.so"))
_lib.xxh3_64.restype = ctypes.c_ulonglong
_lib.xxh3_64.argtypes = (ctypes.c_char_p, ctypes.c_ulong)


def xxh3(data):
    return _lib.xxh3_64(data, len(data))


# ------------------------------------------------------------------ capture
def peek(c, x, y, w, h):
    """vram_peek prints each 16-bit word as big-endian hex."""
    r = c("vram_peek", x=x, y=y, w=w, h=h)
    return np.frombuffer(bytes.fromhex(r["hex"]), ">u2").reshape(h, w).astype("<u2")


def capture(args):
    sys.path.insert(0, str(HERE / "port_debug"))
    from dbg import C
    c = C(args.port)
    page = peek(c, PAGE_X, PAGE_Y, 64, ROWS)
    cluts = {k: peek(c, x, y, 16, 1)[0] for k, (x, y) in CLUTS.items()}
    cluts["rows"] = peek(c, 352, 32, 16, 8)        # every palette next to the HUD's
    slots = [dict() for _ in SLOTS]
    end = time.time() + args.seconds
    while time.time() < end:
        for i, (x, y, w, h) in enumerate(SLOTS):
            s = peek(c, PAGE_X + x // 4, PAGE_Y + y, w // 4, h)
            slots[i][s.tobytes()] = s
    if args.name:                         # one capture per level, kept apart
        out = WORK / "captures" / f"{args.name}.npz"
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez(out, page=page, **{f"clut_{k}": v for k, v in cluts.items()},
                 **{f"slot{i}": np.stack(list(s.values())) for i, s in enumerate(slots)})
        print(f"{out}: slot frames " + ", ".join(str(len(s)) for s in slots))
        return
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "capture.npz"
    if path.exists():                     # merge frames from earlier captures
        old = np.load(path)
        for i in range(len(SLOTS)):
            for s in (old[f"slot{i}"] if f"slot{i}" in old else []):
                slots[i].setdefault(s.tobytes(), s)
        if not np.array_equal(old["page"], page):
            print("note: static HUD rows differ from the earlier capture; using the new ones")
    np.savez(path, page=page, **{f"clut_{k}": v for k, v in cluts.items()},
             **{f"slot{i}": np.stack(list(s.values())) for i, s in enumerate(slots)})
    print(f"{path}: slot frames " + ", ".join(str(len(s)) for s in slots))
    print("palette hashes: " + ", ".join(f"{k} {xxh3(v.tobytes()):016X}" for k, v in cluts.items()))


# -------------------------------------------------------------------- build
TILE_W, TILE_H = 16, 8          # texels; x and width stay word aligned (4 texels)


def indices(words):
    """4-bit texels of a word array (rows x words) -> rows x (4*words)."""
    w = words.astype(np.uint16)
    out = np.zeros((w.shape[0], w.shape[1] * 4), np.uint8)
    for i in range(4):
        out[:, i::4] = (w >> (4 * i)) & 15
    return out


def rgba(idx, clut):
    c = clut.astype(np.uint32)
    rgb = np.stack([(c & 31) << 3, ((c >> 5) & 31) << 3, ((c >> 10) & 31) << 3], -1)
    rgb = (rgb | (rgb >> 5)).astype(np.uint8)
    alpha = np.where(clut == 0, 0, 255).astype(np.uint8)   # colour word 0 = transparent
    return np.dstack([rgb[idx], alpha[idx]])


def h16(a):
    return f"{xxh3(np.ascontiguousarray(a).astype('<u2').tobytes()):016X}"


def name(words, clut, x, y, w, h):
    return f"texpage-P4-{h16(words)}-{h16(clut)}-64x256-{x}-{y}-{w}x{h}-P0-15"


def in_slot(x, y, w, h):
    return any(x < sx + sw and sx < x + w and y < sy + sh and sy < y + h for sx, sy, sw, sh in SLOTS)


STP_GRID = (80, 24, 6)          # first row, cell height, cell width (words)


def from_disc(args):
    out = Path(args.work) / "captures"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("STP1", "STP2"):
        stp = np.frombuffer((Path(args.files) / "STP" / f"{name}.").read_bytes(), "<u2").reshape(512, 64)
        y0, ch, cw = STP_GRID
        cells = [stp[y:y + ch, x:x + cw] for y in range(y0, 512 - ch + 1, ch)
                 for x in range(0, 64 - cw + 1, cw)]
        cells = [c for c in cells if c.any()]
        caps = {"page": stp[:ROWS].copy(), "clut_rows": stp[32:40, 32:48].copy()}
        for k, (x, y) in CLUTS.items():
            caps[f"clut_{k}"] = stp[y - PAGE_Y, x - PAGE_X:x - PAGE_X + 16].copy()
        frames = np.stack(cells)
        np.savez(out / f"{name}.npz", **caps, slot0=frames, slot1=frames)
        print(f"{out / name}.npz: {len(cells)} slot frames")


def captures():
    paths = sorted((WORK / "captures").glob("*.npz"))
    if (WORK / "capture.npz").exists():
        paths.append(WORK / "capture.npz")
    return [dict(np.load(p)) for p in paths]


def jobs(caps):
    """(kind, key, words, clut): whole HUD pages per palette, medallion frames."""
    seen = set()
    for cap in caps:
        page = cap["page"]
        cluts = [cap[f"clut_{k}"] for k in STATIC_CLUTS]
        if "clut_rows" in cap:     # every palette beside the HUD's (bar segments, blink)
            cluts += [r for r in cap["clut_rows"] if len(set(r.tolist())) > 2]
        for clut in cluts:
            key = f"page-{h16(page)}-{h16(clut)}"
            if key not in seen:
                seen.add(key)
                yield "page", key, page, clut
        for i, (x, y, w, h) in enumerate(SLOTS):
            for words in cap.get(f"slot{i}", []):
                for clut in [cap[f"clut_{k}"] for k in SLOT_CLUTS]:
                    key = f"slot{i}-{h16(words)}-{h16(clut)}"
                    if key not in seen:
                        seen.add(key)
                        yield f"slot{i}", key, words, clut


def build(args):
    orig, raw, final = WORK / "orig", WORK / "raw", WORK / "final"
    for d in (orig, raw, final):
        d.mkdir(parents=True, exist_ok=True)
    todo = list(jobs(captures()))
    for kind, key, words, clut in todo:
        p = orig / f"{key}.png"
        if not p.exists():
            Image.fromarray(rgba(indices(words), clut), "RGBA").save(p)
    print(f"{len(todo)} HUD images to upscale")
    cmd = [str(args.python), str(HERE / "upscale_model.py"), str(args.model), str(orig), str(raw)]
    if args.progress:
        cmd += ["--progress", str(args.progress)]
    subprocess.run(cmd, check=True)
    dst = Path(args.pack) / "replacements" / "hud"
    out = WORK / "pack"
    if out.exists():
        for f in out.glob("*.png"):
            f.unlink()
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for kind, key, words, clut in todo:
        o = np.asarray(Image.open(orig / f"{key}.png").convert("RGBA"))
        u = np.asarray(Image.open(raw / f"{key}.png").convert("RGBA"))
        res = palettize(u, o, radius=1, restore="center", alpha_cut=128, protect=2)
        s = res.shape[0] // o.shape[0]
        if kind == "page":
            for ty in range(0, ROWS, TILE_H):
                for tx in range(0, 256, TILE_W):
                    if in_slot(tx, ty, TILE_W, TILE_H) or not o[ty:ty + TILE_H, tx:tx + TILE_W, 3].any():
                        continue
                    n = name(words[ty:ty + TILE_H, tx // 4:(tx + TILE_W) // 4], clut, tx, ty, TILE_W, TILE_H)
                    target = out / f"{n}.png"
                    if not target.exists():
                        Image.fromarray(res[ty * s:(ty + TILE_H) * s, tx * s:(tx + TILE_W) * s],
                                        "RGBA").save(target, optimize=True)
                        written += 1
        else:
            x, y, w, h = SLOTS[int(kind[-1])]
            target = out / f"{name(words, clut, x, y, w, h)}.png"
            if not target.exists():
                Image.fromarray(res, "RGBA").save(target, optimize=True)
                written += 1
    # Publish: the pack folder gets exactly this set (hard links).
    dst.mkdir(parents=True, exist_ok=True)
    for f in dst.glob("*.png"):
        f.unlink()
    for f in out.glob("*.png"):
        (dst / f.name).hardlink_to(f)
    print(f"{dst}: {written} images")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="read the HUD page from the debug build")
    c.add_argument("--port", type=int, default=4370)
    c.add_argument("--seconds", type=float, default=15)
    c.add_argument("--name", help="store as assets/hud/captures/NAME.npz (per level)")
    b = sub.add_parser("build", help="upscale and write texpage replacements")
    b.add_argument("pack", help="texture pack folder (with replacements/)")
    b.add_argument("--model", type=Path, default=MODEL, help="spandrel model (default DAT2)")
    b.add_argument("--python", type=Path, default=MODEL_PY, help="Python with torch + spandrel")
    b.add_argument("--work", type=Path, help=f"work folder (default {WORK})")
    b.add_argument("--progress", type=Path, help="JSON progress file for the upscale step")
    d = sub.add_parser("from-disc", help="captures from STP/STP1 and STP2 of the extracted disc")
    d.add_argument("files", help="extracted disc files (with STP/)")
    d.add_argument("--work", type=Path, default=WORK)
    args = ap.parse_args()
    if getattr(args, "work", None):
        globals()["WORK"] = Path(args.work)
    {"capture": capture, "build": build, "from-disc": from_disc}[args.cmd](args)


if __name__ == "__main__":
    main()
