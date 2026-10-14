#!/usr/bin/env python3
"""Archives of finished HD packs for the launcher's download.

Per PAL version (SERIAL, e.g. SCES-00893):

  hd-SERIAL-core.tar.xz    config.yaml + replacements/ without levels
                           (sprites, HUD); xz -6 only to drop the ~1.5 KB of
                           tar headers each of the 240,000 long-named files
                           costs, the PNGs themselves do not compress further
  hd-SERIAL-levels.tar     replacements/levels, a plain tar of its own

Run tools/png_optimize.py on the packs first (lossless, about a third smaller).
  hd-SERIAL-from-BASE.tar.xz
                           for a player who already has the pack of BASE from
                           this release: only the files of SERIAL that differ
                           from it, copy.txt (DEST<TAB>SOURCE: an image BASE
                           has under another name, applied first) and
                           remove.txt (names BASE has and SERIAL does not).
                           Tens of MB instead of the whole pack

and SHA256SUMS.txt over all archives. Each archive stays below GitHub's 2 GiB
asset limit. Uploaded as the assets of the GitHub release "hd-packs";
HerculesRecomp/hd/hd_auto.py picks what the player needs there, checks it and
installs it.

    python3 tools/hd_pack_release.py OUT_DIR SERIAL=SOURCE [SERIAL=SOURCE ...]

SOURCE is a pack folder (config.yaml + replacements/) or a glob of the older
hd-SERIAL-<n>.zip archives. xz runs as the external program (all cores).
The pack loader refuses more than 262,144 images, so a bigger pack is an error.
"""
import argparse
import glob
import hashlib
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

LIMIT = 262_144
ASSET_LIMIT = 2**31 - 2**20
MTIME = 1767225600                       # 2026-01-01, the same bytes on every run


class Source:
    """name -> bytes of one pack, from its folder or from zip archives."""

    def __init__(self, spec):
        self.where = {}
        p = Path(spec)
        if p.is_dir():
            self.root = p
            files = [p / "config.yaml"] if (p / "config.yaml").exists() else []
            files += [f for f in (p / "replacements").rglob("*") if f.is_file()]
            self.where = {f.relative_to(p).as_posix(): None for f in files}
        else:
            self.root = None
            paths = sorted(glob.glob(spec))
            if not paths:
                raise SystemExit(f"{spec}: neither a pack folder nor archives")
            for path in paths:
                z = zipfile.ZipFile(path)
                for info in z.infolist():
                    if not info.is_dir():
                        self.where[info.filename] = z
        if sum(1 for n in self.where if n.endswith(".png")) > LIMIT:
            raise SystemExit(f"{spec}: more than {LIMIT} images, the pack loader would refuse it")

    def names(self):
        return sorted(self.where)

    def digests(self):
        """name -> content hash, computed once."""
        if not hasattr(self, "_digests"):
            self._digests = {n: hashlib.blake2b(self.read(n), digest_size=20).digest() for n in self.where}
        return self._digests

    def read(self, name):
        if self.root is not None:
            return (self.root / name).read_bytes()
        return self.where[name].read(name)


def is_level(name):
    return name.startswith("replacements/levels/")


def write_tar(out, members, xz_level=None):
    """members: [(name, bytes)] in order -> out (.tar, or .tar.xz via xz at xz_level)."""
    tmp = out.with_name(out.name + ".part")
    with open(tmp, "wb") as f:
        xz = subprocess.Popen(["xz", xz_level, "-T0", "-c"], stdin=subprocess.PIPE, stdout=f) if xz_level else None
        with tarfile.open(fileobj=xz.stdin if xz else f, mode="w|", format=tarfile.PAX_FORMAT) as t:
            for name, data in members:
                info = tarfile.TarInfo(name)
                info.size, info.mtime, info.mode = len(data), MTIME, 0o644
                t.addfile(info, io.BytesIO(data))
        if xz:
            xz.stdin.close()
            if xz.wait():
                raise SystemExit(f"xz ended with {xz.returncode}")
    if tmp.stat().st_size > ASSET_LIMIT:
        raise SystemExit(f"{out.name}: {tmp.stat().st_size / 2**30:.2f} GB, above GitHub's asset limit")
    tmp.replace(out)
    print(f"{out.name}: {out.stat().st_size / 2**20:.1f} MB", flush=True)


def full(src, serial, out):
    names = src.names()
    write_tar(out / f"hd-{serial}-core.tar.xz",
              ((n, src.read(n)) for n in names if not is_level(n)), "-6")
    write_tar(out / f"hd-{serial}-levels.tar",
              ((n, src.read(n)) for n in names if is_level(n)))


def diff(src, serial, base, base_serial, out):
    bd, sd = base.digests(), src.digests()
    by_content = {}
    for n in sorted(bd):
        by_content.setdefault(bd[n], n)
    changed, copies = [], []
    for n in src.names():
        if n != "config.yaml" and sd[n] == bd.get(n):
            continue
        if n != "config.yaml" and sd[n] in by_content:
            copies.append((n, by_content[sd[n]]))   # same image under another name
        else:
            changed.append(n)
    removed = sorted(set(bd) - set(sd))
    members = [("copy.txt", "".join(f"{d}\t{s}\n" for d, s in copies).encode()),
               ("remove.txt", "".join(n + "\n" for n in removed).encode())]
    members += ((n, src.read(n)) for n in changed)
    print(f"{serial} from {base_serial}: {len(changed)} files, {len(copies)} copied, "
          f"{len(removed)} removed", flush=True)
    write_tar(out / f"hd-{serial}-from-{base_serial}.tar.xz", members, "-9e")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("packs", nargs="+", help="SERIAL=SOURCE, e.g. SCES-00891=.../SCES-00891")
    ap.add_argument("--only", help="build just this kind: full or diffs")
    ap.add_argument("--base", action="append", help="diffs only from this SERIAL (repeatable)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    srcs = {}
    for item in a.packs:
        serial, spec = item.split("=", 1)
        srcs[serial] = Source(spec)
    if a.only != "diffs":
        for serial, src in srcs.items():
            full(src, serial, a.out)
    if a.only != "full":
        for serial, src in srcs.items():
            for base_serial, base in srcs.items():
                if base_serial != serial and (not a.base or base_serial in a.base):
                    diff(src, serial, base, base_serial, a.out)
    archives = sorted(p for p in a.out.glob("hd-*") if p.name.endswith((".tar", ".tar.xz")))
    sums = [f"{sha256(p)}  {p.name}" for p in archives]
    (a.out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    print(f"SHA256SUMS.txt: {len(sums)} archives")


if __name__ == "__main__":
    sys.exit(main())
