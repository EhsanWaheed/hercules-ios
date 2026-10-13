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

The project's chaiNNer chains (models/*.chn) are reproduced with

    --alpha-model 4xHDcube-Alpha.pth --alpha-threshold 0.05 --fill all

(split transparency, "fill alpha: extend texture", colour through the main
model, alpha through HDcube-Alpha, alpha "threshold to zero" at 5 %). The
fill uses chaiNNer's own Rust code (pip package chainner_ext, bundled with
chaiNNer) when it is installed, else a plain nearest-colour bleed.
--exclude skips sub-trees (e.g. SD3/S3_1), --only limits to them;
--progress FILE keeps {"done", "total"} up to date for a caller.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
import spandrel

try:
    import chainner_ext
except ImportError:
    chainner_ext = None


def bleed(rgb, alpha, steps=8):
    """Spread opaque colours into transparent pixels (steps deep; 0 = all)."""
    rgb = rgb.astype(np.float32)
    known = alpha > 0
    if not known.any():
        return rgb
    for _ in range(steps or 4096):
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


def fill_texture(rgba):
    """chaiNNer "Fill Alpha: Extend texture" on a float RGBA image (0..1)."""
    img = chainner_ext.fill_alpha_fragment_blur(rgba, threshold=0.05, iterations=6, fragment_count=5)
    img = chainner_ext.fill_alpha_extend_color(img, threshold=0.05, iterations=100_000)
    return img[..., :3]


def to_float(img):
    return img.astype(np.float32) / 255.0 if img.dtype == np.uint8 else img.astype(np.float32)


def run_whole(model, img):
    x = torch.from_numpy(to_float(img).transpose(2, 0, 1)[None].copy())
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
    return np.clip(y, 0, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("model", type=Path)
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--alpha-model", type=Path, help="separate model for the alpha channel")
    ap.add_argument("--alpha-threshold", type=float, default=0.0,
                    help="alpha below this fraction becomes 0 (threshold to zero)")
    ap.add_argument("--fill", choices=["edge", "all"], default="edge",
                    help="colour bleed into transparency: 8 px (edge) or everywhere (all)")
    ap.add_argument("--exclude", action="append", default=[], help="relative sub-path to skip")
    ap.add_argument("--only", action="append", default=[], help="relative sub-path to limit to")
    ap.add_argument("--progress", type=Path, help="JSON progress file")
    a = ap.parse_args()

    def load(path):
        m = spandrel.ModelLoader().load_from_file(str(path))
        m.eval()
        return m
    model = load(a.model)
    alpha_model = load(a.alpha_model) if a.alpha_model else model
    a.dst.mkdir(parents=True, exist_ok=True)

    def wanted(f):
        rel = f.relative_to(a.src).as_posix()
        if any(rel == x or rel.startswith(x.rstrip("/") + "/") for x in a.exclude):
            return False
        return not a.only or any(rel == x or rel.startswith(x.rstrip("/") + "/") for x in a.only)
    files = [f for f in sorted(a.src.rglob("*.png")) if wanted(f)]
    done = skipped = 0

    def report():
        if a.progress:
            tmp = a.progress.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps({"done": done + skipped, "total": len(files)}))
                tmp.replace(a.progress)
            except OSError:     # Windows: the reader has it open; next write wins
                pass
    report()
    # A tree (assets/sprites/SD1/S1_3/f0001.png ...) is mirrored below DST.
    for f in files:
        out = a.dst / f.relative_to(a.src)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_mtime >= f.stat().st_mtime:
            skipped += 1
            continue
        im = np.asarray(Image.open(f).convert("RGBA"))
        alpha = im[..., 3]
        if a.fill == "all" and chainner_ext is not None:
            src = fill_texture(np.ascontiguousarray(to_float(im)))
        else:
            src = bleed(im[..., :3], alpha, 0 if a.fill == "all" else 8) / 255.0
        rgb = run(model, src)
        if alpha.min() == 255:               # opaque picture: no alpha pass
            al = np.ones(rgb.shape[:2], np.float32)
        else:
            al = run(alpha_model, np.repeat(to_float(alpha)[..., None], 3, 2)).mean(-1)
            if a.alpha_threshold > 0:
                al = np.where(al < a.alpha_threshold, 0, al)
        px = (np.dstack([rgb, al]) * 255.0 + 0.5).astype(np.uint8)
        tmp = out.with_suffix(".part.png")
        Image.fromarray(px, "RGBA").save(tmp)
        tmp.replace(out)                     # a crash never leaves a half-written file
        done += 1
        if done % 10 == 0:
            report()
    report()
    print(f"{a.dst}: {done} upscaled, {skipped} already done")


if __name__ == "__main__":
    main()
