#!/usr/bin/env python3
"""Lossless recompression of the PNGs of finished HD packs (oxipng).

    python3 tools/png_optimize.py PACK_DIR [PACK_DIR ...] [--workers N]

Our upscaling writes PNGs with little compression; oxipng (palette where
the colours allow it, better filters, deflate) makes sprites about 40 % and
level textures about 85 % of their size. Every result is decoded and compared
with the original (RGBA pixels, Pillow) and only replaces it when equal; the
runtime decodes with stb_image, which reads all PNG forms oxipng writes.
Files are rewritten in place, once per inode, so packs that share images as
hard links (hd_auto.py's language differences) share the result too.
Needs `pip install pyoxipng pillow`. Run it before tools/hd_pack_release.py.
"""
import argparse
import io
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import oxipng
from PIL import Image


def rgba(data):
    im = Image.open(io.BytesIO(data))
    return im.size, im.convert("RGBA").tobytes()


def one(path):
    """(bytes before, bytes after, path if the pixels differed)."""
    a = open(path, "rb").read()
    b = oxipng.optimize_from_memory(a, level=4, strip=oxipng.StripChunks.safe())
    if len(b) >= len(a):
        return len(a), len(a), None
    if rgba(a) != rgba(b):
        return len(a), len(a), path
    with open(path, "r+b") as f:            # same inode: every pack linking it gets it
        f.write(b)
        f.truncate()
    return len(a), len(b), None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("packs", nargs="+")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    a = ap.parse_args()
    seen, files = set(), []
    for pack in a.packs:
        for root, _, names in os.walk(pack):
            for n in names:
                if n.endswith(".png"):
                    p = os.path.join(root, n)
                    st = os.stat(p)
                    if (st.st_dev, st.st_ino) not in seen:
                        seen.add((st.st_dev, st.st_ino))
                        files.append(p)
    files.sort(key=lambda p: -os.path.getsize(p))         # big level textures first
    print(f"{len(files)} images", flush=True)
    t, before, after, bad = time.time(), 0, 0, []
    with ProcessPoolExecutor(a.workers) as ex:
        for i, (x, y, mismatch) in enumerate(ex.map(one, files, chunksize=16)):
            before += x
            after += y
            if mismatch:
                bad.append(mismatch)
            if i % 20000 == 0:
                print(f"{i}: {after / before * 100:.1f} %, {time.time() - t:.0f} s", flush=True)
    print(f"{len(files)} images: {before / 1e9:.2f} -> {after / 1e9:.2f} GB; "
          f"kept {len(bad)} originals whose pixels changed", flush=True)
    for p in bad[:20]:
        print("pixels changed, kept:", p)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
