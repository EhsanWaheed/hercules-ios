#!/usr/bin/env python3
"""Snap upscaled sprite frames back onto the pixel art of the original frame.

AI upscalers blend colours and invent details (e.g. Hercules' 2-pixel eye
becomes an anime eye with lashes). This forces the upscaled frame to stay
faithful to the original pixel art while keeping the smoother shapes:

1. Local colours: every upscaled pixel may only take a colour that occurs in
   the original within --radius pixels of its source pixel (no dithering).
   Transparency follows the same rule, so edges stay hard.
2. Protect: pixels whose colour occurs at most --protect times in the frame
   (the eye is a single grey pixel) are copied 1:1 together with their
   8 neighbours, so tiny details keep their exact pixel-art look.
3. Restore: an original pixel whose colour vanished from its upscaled block
   (eye highlight, small dots) is painted back into the block's centre
   (--restore center) or the whole block (--restore block).

    ~/psx-decomp/.venv/bin/python tools/sprite_palettize.py SRC_DIR ORIG_DIR DST_DIR

SRC_DIR:  upscaled frames (fNNNN.png, RGB or RGBA, integer scale of original)
ORIG_DIR: original frames with the same names and folder layout (a single
          sprite folder or a whole tree such as assets/sprites)

All sprites with the chosen model:
    ~/psx-decomp/.venv/bin/python tools/sprite_palettize.py \
        assets/sprites_hd/DAT2-raw assets/sprites assets/sprites_hd/DAT2-schutz
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def palettize(up: np.ndarray, orig: np.ndarray, radius: int, restore: str,
              alpha_cut: int, protect: int = 0) -> np.ndarray:
    h, w = orig.shape[:2]
    s = up.shape[0] // h
    if s * h != up.shape[0] or s * w != up.shape[1]:
        raise ValueError(f"upscaled size {up.shape[1]}x{up.shape[0]} is not a multiple of {w}x{h}")

    opaque = orig[..., 3] >= 128
    colors, inv = np.unique(orig[..., :3][opaque], axis=0, return_inverse=True)
    k = len(colors)
    out = np.zeros(up.shape[:2] + (4,), np.uint8)
    if k == 0:
        return out
    idx = np.full((h, w), k)                     # k = transparent
    idx[opaque] = inv.ravel()

    # Colours allowed per original pixel: those within `radius` (outside = transparent).
    onehot = np.eye(k + 1, dtype=bool)[idx]
    if radius < 0:
        allowed = np.ones_like(onehot)
    else:
        pad = np.pad(onehot, ((radius, radius), (radius, radius), (0, 0)))
        if radius:
            pad[:radius, :, k] = pad[-radius:, :, k] = True
            pad[:, :radius, k] = pad[:, -radius:, k] = True
        allowed = np.zeros_like(onehot)
        for dy in range(2 * radius + 1):
            for dx in range(2 * radius + 1):
                allowed |= pad[dy:dy + h, dx:dx + w]
    if protect > 0:
        rare = opaque & (np.bincount(inv.ravel(), minlength=k)[np.minimum(idx, k - 1)] <= protect)
        near = np.pad(rare, 1)
        near = np.logical_or.reduce([near[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)])
        allowed[near] = onehot[near]
    allowed = allowed.repeat(s, 0).repeat(s, 1)

    rgb = up[..., :3].astype(np.int32)
    dist = ((rgb[..., None, :] - colors.astype(np.int32)) ** 2).sum(-1)
    dist[~allowed[..., :k]] = 1 << 30
    choice = dist.argmin(-1)

    want = up[..., 3] >= alpha_cut if up.shape[2] == 4 else np.ones(up.shape[:2], bool)
    can_opaque = allowed[..., :k].any(-1)
    vis = np.where(want, can_opaque, ~allowed[..., k])
    choice[~vis] = k

    if restore != "off":
        blocks = choice.reshape(h, s, w, s)
        missing = opaque & ~(blocks == idx[:, None, :, None]).any(axis=(1, 3))
        m = s // 4 if restore == "center" else 0
        ys, xs = np.nonzero(missing)
        for y, x in zip(ys, xs):
            blocks[y, m:s - m, x, m:s - m] = idx[y, x]

    vis = choice < k
    out[vis, :3] = colors[choice[vis]]
    out[vis, 3] = 255
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("orig", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--radius", type=int, default=1,
                    help="neighbourhood for allowed colours; -1 = whole frame palette (default 1)")
    ap.add_argument("--restore", choices=["center", "block", "off"], default="center")
    ap.add_argument("--protect", type=int, default=2,
                    help="copy pixels 1:1 whose colour occurs at most N times (0 = off, default 2)")
    ap.add_argument("--alpha", type=int, default=128, help="alpha threshold (default 128)")
    args = ap.parse_args()

    # Every folder below ORIG_DIR holding frames is processed (ORIG_DIR itself
    # may be one sprite folder); frames already in DST_DIR are skipped, so the
    # run can be repeated while the upscaler is still writing.
    done = skipped = missing = bad = 0
    for odir in sorted({p.parent for p in args.orig.rglob("f*.png")}):
        rel = odir.relative_to(args.orig)
        sdir, ddir = args.src / rel, args.dst / rel
        for src in sorted(sdir.glob("f*.png")):
            dst, orig = ddir / src.name, odir / src.name
            if not orig.exists():
                missing += 1
                continue
            if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                skipped += 1
                continue
            try:
                with Image.open(src) as u, Image.open(orig) as o:
                    up = np.asarray(u.convert("RGBA" if "A" in u.getbands() else "RGB"))
                    res = palettize(up, np.asarray(o.convert("RGBA")), args.radius,
                                    args.restore, args.alpha, args.protect)
            except (ValueError, OSError) as e:
                print(f"{src}: {e}")
                bad += 1
                continue
            ddir.mkdir(parents=True, exist_ok=True)
            Image.fromarray(res, "RGBA").save(dst, optimize=True)
            done += 1
    print(f"{args.dst}: {done} new, {skipped} already done"
          + (f", {missing} without original" if missing else "")
          + (f", {bad} failed" if bad else ""))

if __name__ == "__main__":
    main()
