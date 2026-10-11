#!/usr/bin/env python3
"""Approximate texture colours by guessing a palette per tile.

Usage: guess_palettes.py OUT_DIR LEVEL_FILE... [--tile W H]

Reads the texture blocks of an i2.x level as 4-bit indexed (see
docs/level_format.md). The CLUT block holds 31 usable rows x 16 palettes of 16
colours (colour 0 = transparent). For every tile all 496 palettes are tried
and the one where neighbouring pixels are most similar *relative to* the
colour spread inside the tile wins; the ratio keeps dark or flat palettes
from winning just for being uniform. This is a heuristic: the real palette assignment
lives in the level's RAM part and is not decoded yet.

Writes <name>_tex{1,2}_guess.png and <name>_palettes.txt (tile -> palette row).
"""
import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fullscreen2png import png  # noqa: E402
from level_vram import BLOCKS, CLUT_X, CLUT_Y, VRAM_H, VRAM_W, build_vram  # noqa: E402

# Row 31 is not a palette: the 0x200-byte table of header field 0x20 overlaps it.
ROWS, PER_ROW = 31, 16
PALETTES = ROWS * PER_ROW


def palettes_rgb(vram):
    """(512, 16, 3) float array: every 16-colour CLUT as RGB 0..255."""
    rows = vram[CLUT_Y:CLUT_Y + ROWS, CLUT_X:CLUT_X + 256].astype(np.int32)
    rgb = np.stack([(rows >> s) & 31 for s in (0, 5, 10)], axis=-1)
    rgb = (rgb << 3 | rgb >> 2).astype(np.float32)
    return rgb.reshape(PALETTES, 16, 3)


def indices_4bpp(vram, x, y, w, h):
    words = vram[y:y + h, x:x + w].astype(np.uint16)
    out = np.empty((h, w * 4), dtype=np.uint8)
    for i in range(4):
        out[:, i::4] = (words >> (4 * i)) & 0xF
    return out


def score(img, opaque):
    """Neighbour colour step divided by overall colour spread (lower = better)."""
    dx = np.abs(np.diff(img, axis=1)).sum(axis=-1)[opaque[:, 1:] & opaque[:, :-1]]
    dy = np.abs(np.diff(img, axis=0)).sum(axis=-1)[opaque[1:] & opaque[:-1]]
    steps = np.concatenate([dx, dy])
    colours = img[opaque]
    spread = np.abs(colours - colours.mean(axis=0)).sum(axis=-1).mean()
    if steps.size == 0 or spread < 8:            # flat or empty palette: reject
        return np.inf
    return steps.mean() / spread


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("levels", nargs="+")
    ap.add_argument("--tile", nargs=2, type=int, default=(32, 32), metavar=("W", "H"))
    args = ap.parse_args()
    tw, th = args.tile
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name in args.levels:
        path = Path(name)
        data = path.read_bytes()
        if not data.startswith(b"i2."):
            print(f"skip {name}: not the i2.x layout")
            continue
        stem = path.name.replace(".", "_")
        vram = np.array(build_vram(data), dtype=np.uint16).reshape(VRAM_H, VRAM_W)
        pals = palettes_rgb(vram)
        report = []
        for idx, (_, x, y, w, h) in enumerate(BLOCKS[:2], 1):
            ind = indices_4bpp(vram, x, y, w, h)
            out = np.zeros(ind.shape + (3,), dtype=np.float32)
            for ty in range(0, ind.shape[0], th):
                for tx in range(0, ind.shape[1], tw):
                    tile = ind[ty:ty + th, tx:tx + tw]
                    opaque = tile != 0
                    if opaque.sum() < 16:
                        continue                 # (almost) empty tile: leave black
                    scores = [score(pals[p][tile], opaque) for p in range(PALETTES)]
                    best = int(np.argmin(scores))
                    if not np.isfinite(scores[best]):
                        continue
                    out[ty:ty + th, tx:tx + tw] = pals[best][tile]
                    report.append(f"tex{idx} {tx:4d},{ty:3d} palette {best:3d} "
                                  f"(row {best // PER_ROW}, clut {best % PER_ROW})")
            img = out.astype(np.uint8)
            png(out_dir / f"{stem}_tex{idx}_guess.png", img.shape[1], img.shape[0],
                [row.tobytes() for row in img])
        (out_dir / f"{stem}_palettes.txt").write_text("\n".join(report) + "\n")
        rows_used = sorted({int(r.split("row ")[1].split(",")[0]) for r in report})
        cluts_used = len({r.split("palette")[1].split()[0] for r in report})
        print(f"wrote {stem}: {len(report)} tiles, {cluts_used} distinct palettes, rows {rows_used}")


if __name__ == "__main__":
    main()
