#!/usr/bin/env python3
"""Cut a file's raw 2352-byte sectors out of the disc image.

Usage: cut_raw.py BIN FILELIST PATH OUT

Uses the LBA and size from filelist.txt (written by the disc extractor).
Raw sectors keep the sync/header/subheader that STR/XA tools such as
ffmpeg need, which the 2048-byte filesystem view drops.
"""
import sys

SECTOR = 2352


def main():
    bin_path, filelist, wanted, out = sys.argv[1:5]
    for line in open(filelist):
        lba, size, _form, path = line.split(maxsplit=3)
        if path.strip() == wanted:
            count = (int(size) + 2047) // 2048
            with open(bin_path, "rb") as f, open(out, "wb") as o:
                f.seek(int(lba) * SECTOR)
                o.write(f.read(count * SECTOR))
            return
    sys.exit(f"{wanted} not in {filelist}")


if __name__ == "__main__":
    main()
