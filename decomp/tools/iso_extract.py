#!/usr/bin/env python3
"""Extract the files of a PlayStation disc image (MODE2/2352 BIN, or its CUE).

    python3 tools/iso_extract.py DISC.cue OUT_DIR [--list filelist.txt]

Walks the ISO 9660 directory tree and writes every file below OUT_DIR with
its disc name minus the ";1" version (EX/TITLE. stays "TITLE."). Form 1
files (data) are written as their 2048-byte user data; Form 2 files
(XA audio, interleaved streams) as 2336 bytes per sector (subheader + data
+ EDC), the layout XA/STR tools expect. The optional list has one line per
file: LBA, ISO size, form1/form2, path (same format as filelist.txt).
"""
import argparse
import re
import struct
import sys
from pathlib import Path

RAW = 2352


def bin_of(path):
    path = Path(path)
    if path.suffix.lower() != ".cue":
        return path
    m = re.search(r'FILE\s+"([^"]+)"', path.read_text(errors="replace"))
    if not m:
        sys.exit(f"{path}: no FILE line")
    return path.parent / m.group(1)


class Disc:
    def __init__(self, path):
        self.f = open(path, "rb")

    def raw(self, lba):
        self.f.seek(lba * RAW)
        return self.f.read(RAW)

    def form2(self, lba):
        return bool(self.raw(lba)[18] & 0x20)      # subheader submode bit 5

    def data(self, lba, n=1):
        return b"".join(self.raw(lba + i)[24:24 + 2048] for i in range(n))


def records(disc, lba, size):
    """Directory records of one directory extent."""
    buf = disc.data(lba, (size + 2047) // 2048)
    out, pos = [], 0
    while pos < len(buf):
        n = buf[pos]
        if n == 0:                                  # rest of this sector is padding
            pos = (pos // 2048 + 1) * 2048
            continue
        rec = buf[pos:pos + n]
        ext, length = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
        flags, nlen = rec[25], rec[32]
        name = rec[33:33 + nlen]
        if name not in (b"\0", b"\1"):
            out.append((name.decode("ascii").split(";")[0], ext, length, bool(flags & 2)))
        pos += n
    return out


def walk(disc, lba, size, prefix=""):
    for name, ext, length, is_dir in records(disc, lba, size):
        path = f"{prefix}{name}"
        if is_dir:
            yield from walk(disc, ext, length, path + "/")
        else:
            yield path, ext, length


def extract(image, out, listing=None, progress=None):
    disc = Disc(bin_of(image))
    pvd = disc.data(16)
    if pvd[1:6] != b"CD001":
        sys.exit("no ISO 9660 volume descriptor at sector 16")
    root = pvd[156:156 + 34]
    entries = sorted(walk(disc, struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]),
                     key=lambda e: e[1])
    out = Path(out)
    lines = []
    for k, (path, lba, size) in enumerate(entries):
        dst = out / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        sectors = (size + 2047) // 2048
        form2 = sectors > 0 and disc.form2(lba)
        if form2:
            data = b"".join(disc.raw(lba + i)[16:RAW] for i in range(sectors))
        else:
            data = disc.data(lba, sectors)[:size]
        dst.write_bytes(data)
        lines.append(f"{lba:7d} {size:10d} {'form2' if form2 else 'form1'} {path}")
        if progress:
            progress(k + 1, len(entries))
    if listing:
        Path(listing).write_text("\n".join(lines) + "\n")
    return len(entries)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("--list")
    a = ap.parse_args()
    print(f"{extract(a.image, a.out, a.list)} files -> {a.out}")


if __name__ == "__main__":
    main()
