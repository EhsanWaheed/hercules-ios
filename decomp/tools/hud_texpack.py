#!/usr/bin/env python3
"""HD replacements for the in-game HUD (clouds, health bar, medallions, font).

The HUD is not a sprite file: it sits in the top rows of the 4-bit texture
page at VRAM (320,0) (64 words x 256 rows), with its palettes at (352,32),
(352,33) and (352,34). The level texture upload covers the same page and the
game overwrites the HUD rows afterwards, so no upload identity matches it.
DuckStation-format `texpage` names do: they hash a chosen sub-rectangle of
the page as it is in VRAM when drawn, plus the palette. Parts compose, so
the page is split into

- static rectangles (frames, bar, digits, font) per palette 32 and 33, and
- the two 24x24 medallion slots at (0,56) and (24,56), palette 34, one image
  per animation frame: the game writes the spinning medallion (13 frames)
  and the current weapon icon into VRAM while playing.

Names: texpage-P4-<xxh3(rect words)>-<xxh3(16 CLUT words)>-64x256-x-y-wxh-P0-15

    # 1. read page, palettes and medallion frames from the debug build
    #    (in a level; repeat after picking up other weapons, frames are merged)
    ~/psx-decomp/.venv/bin/python tools/hud_texpack.py capture --seconds 15
    # 2. upscale (IllustrationJaNai DAT2, chaiNNer's Python) + palettize, write
    ~/psx-decomp/.venv/bin/python tools/hud_texpack.py build PACK_DIR

Work files: assets/hud/ (capture.npz, orig/, raw/, final/).
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
STATIC = [(0, 0, 256, 56), (48, 56, 208, 24), (0, 80, 256, 16)]   # texels x, y, w, h
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
    slots = [dict() for _ in SLOTS]
    end = time.time() + args.seconds
    while time.time() < end:
        for i, (x, y, w, h) in enumerate(SLOTS):
            s = peek(c, PAGE_X + x // 4, PAGE_Y + y, w // 4, h)
            slots[i][s.tobytes()] = s
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


def name(words, clut, x, y, w, h):
    return (f"texpage-P4-{xxh3(words.astype('<u2').tobytes()):016X}-"
            f"{xxh3(clut.astype('<u2').tobytes()):016X}-64x256-{x}-{y}-{w}x{h}-P0-15")


def pieces(cap):
    page = cap["page"]
    for key in STATIC_CLUTS:
        clut = cap[f"clut_{key}"]
        for x, y, w, h in STATIC:
            words = page[y:y + h, x // 4:(x + w) // 4]
            yield name(words, clut, x, y, w, h), rgba(indices(words), clut)
    for key in SLOT_CLUTS:
        clut = cap[f"clut_{key}"]
        for i, (x, y, w, h) in enumerate(SLOTS):
            for words in cap[f"slot{i}"]:
                yield name(words, clut, x, y, w, h), rgba(indices(words), clut)


def build(args):
    cap = dict(np.load(WORK / "capture.npz"))
    orig, raw, final = WORK / "orig", WORK / "raw", WORK / "final"
    for d in (orig, raw, final):
        d.mkdir(parents=True, exist_ok=True)
    names = []
    for n, img in pieces(cap):
        p = orig / f"{n}.png"
        if not p.exists():
            Image.fromarray(img, "RGBA").save(p)
        names.append(n)
    print(f"{len(names)} HUD pieces")
    subprocess.run([str(MODEL_PY), str(HERE / "upscale_model.py"), str(MODEL), str(orig), str(raw)],
                   check=True)
    dst = Path(args.pack) / "replacements" / "hud"
    dst.mkdir(parents=True, exist_ok=True)
    for n in names:
        o = np.asarray(Image.open(orig / f"{n}.png").convert("RGBA"))
        u = np.asarray(Image.open(raw / f"{n}.png").convert("RGBA"))
        res = palettize(u, o, radius=1, restore="center", alpha_cut=128, protect=2)
        Image.fromarray(res, "RGBA").save(final / f"{n}.png", optimize=True)
        target = dst / f"{n}.png"
        target.unlink(missing_ok=True)
        target.hardlink_to(final / f"{n}.png")
    print(f"{dst}: {len(names)} images")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="read the HUD page from the debug build")
    c.add_argument("--port", type=int, default=4370)
    c.add_argument("--seconds", type=float, default=15)
    b = sub.add_parser("build", help="upscale and write texpage replacements")
    b.add_argument("pack", help="texture pack folder (with replacements/)")
    args = ap.parse_args()
    {"capture": capture, "build": build}[args.cmd](args)


if __name__ == "__main__":
    main()
