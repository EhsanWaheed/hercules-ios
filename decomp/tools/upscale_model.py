#!/usr/bin/env python3
"""Upscale RGBA PNGs with a spandrel model, without the chaiNNer GUI.

Runs in chaiNNer's bundled Python (it has torch + spandrel):

    ~/.config/chaiNNer/python/python/bin/python3.11 tools/upscale_model.py \
        ~/psx-decomp/models/IllustrationJaNai/4x_IllustrationJaNai_V1_DAT2_190k.pth IN_DIR OUT_DIR

IN_DIR may be a tree; its folders are mirrored below OUT_DIR. Colour and
alpha are upscaled separately: transparent pixels first take the
colour of their nearest opaque neighbour (so edges do not pick up a dark
halo), the alpha channel goes through the model as a grey image (skipped
for opaque pictures). Images larger than about 180x180 run in overlapping
128-pixel tiles to keep memory low. Existing
outputs newer than their input are skipped.
"""
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
import spandrel


def bleed(rgb, alpha, steps=8):
    """Spread opaque colours into transparent pixels (a few pixels deep)."""
    rgb = rgb.astype(np.float32)
    known = alpha > 0
    for _ in range(steps):
        if known.all():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(rgb, (dy, dx), (0, 1)) * k[..., None]
            cnt += k
        new = ~known & (cnt > 0)
        rgb[new] = acc[new] / cnt[new][:, None]
        known = known | new
    return rgb


TILE, PAD = 128, 16          # large images go through the model in overlapping tiles


def run_whole(model, img):
    x = torch.from_numpy(img.transpose(2, 0, 1)[None].copy()).float() / 255.0
    with torch.no_grad():
        y = model(x)
    return y[0].clamp(0, 1).numpy().transpose(1, 2, 0)


def run(model, img):
    h, w = img.shape[:2]
    if h * w <= TILE * TILE * 2:
        y = run_whole(model, img)
    else:
        y = None
        for ty in range(0, h, TILE):
            for tx in range(0, w, TILE):
                y0, x0 = max(0, ty - PAD), max(0, tx - PAD)
                y1, x1 = min(h, ty + TILE + PAD), min(w, tx + TILE + PAD)
                part = run_whole(model, img[y0:y1, x0:x1])
                s = part.shape[0] // (y1 - y0)
                if y is None:
                    y = np.zeros((h * s, w * s, 3), np.float32)
                th, tw = min(TILE, h - ty), min(TILE, w - tx)
                oy, ox = (ty - y0) * s, (tx - x0) * s
                y[ty * s:(ty + th) * s, tx * s:(tx + tw) * s] = part[oy:oy + th * s, ox:ox + tw * s]
    return (y * 255.0 + 0.5).astype(np.uint8)


def main():
    model_path, src, dst = map(Path, sys.argv[1:4])
    model = spandrel.ModelLoader().load_from_file(str(model_path))
    model.eval()
    dst.mkdir(parents=True, exist_ok=True)
    done = 0
    # A tree (assets/sprites/SD1/S1_3/f0001.png ...) is mirrored below DST.
    for f in sorted(src.rglob("*.png")):
        out = dst / f.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_mtime >= f.stat().st_mtime:
            continue
        im = np.asarray(Image.open(f).convert("RGBA"))
        alpha = im[..., 3]
        rgb = run(model, bleed(im[..., :3], alpha).astype(np.uint8))
        if alpha.min() == 255:               # opaque picture: no alpha pass
            a = np.full(rgb.shape[:2], 255, np.uint8)
        else:
            a = run(model, np.repeat(alpha[..., None], 3, 2))[..., 0]
        Image.fromarray(np.dstack([rgb, a]), "RGBA").save(out)
        done += 1
    print(f"{dst}: {done} upscaled")


if __name__ == "__main__":
    main()
