#!/usr/bin/env python3
"""Compile a candidate C body for one function and diff it against the original.

Usage: try_func.py SRC NAME CANDIDATE.c [--keep]

CANDIDATE.c holds the function definition (plus any extra declarations it
needs, which are inserted before it). The INCLUDE_ASM line for NAME in SRC is
replaced, the object is compiled, and the function's instruction words are
compared with the original asm. Fields that the linker fills in (jal targets,
%hi/%lo immediates) are masked. With --keep the change stays in SRC if the
full build is still byte-identical; otherwise SRC is always restored.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_m2c import substitute  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ORIG_RE = re.compile(r"/\* [0-9A-F]+ [0-9A-F]+ ([0-9A-F]{8}) \*/\s+(.*)")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def original(folder, name):
    words = []
    for line in (ROOT / folder / f"{name}.s").read_text().splitlines():
        m = ORIG_RE.search(line)
        if m:
            raw = bytes.fromhex(m.group(1))
            words.append((int.from_bytes(raw, "little"), " ".join(m.group(2).split())))
    return words


def compiled(obj, name):
    out = run(["mips64-linux-gnu-objdump", "-d", "-r", str(obj)]).stdout
    words, inside = [], False
    for line in out.splitlines():
        if re.match(rf"^[0-9a-f]+ <{re.escape(name)}>:", line):
            inside = True
            continue
        if inside:
            m = re.match(r"^\s+[0-9a-f]+:\s+([0-9a-f]{8})\s+(.*)", line)
            if m:
                words.append((int(m.group(1), 16), " ".join(m.group(2).split())))
            elif re.match(r"^\s+[0-9a-f]+: R_MIPS", line):
                continue
            elif line.strip() == "" or re.match(r"^[0-9a-f]+ <", line):
                if words:
                    break
    return words


def mask(word, text):
    op = word >> 26
    if op in (2, 3):                  # j/jal: target filled by linker
        return word & ~0x03FFFFFF
    if "%hi" in text or "%lo" in text or op == 0x0F:   # lui / %lo users
        return word & ~0xFFFF
    return word


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("name")
    ap.add_argument("candidate")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    src = ROOT / args.src
    text = src.read_text()
    m = re.search(rf'^INCLUDE_ASM\("([^"]+)", {re.escape(args.name)}\);$', text, re.M)
    if not m:
        sys.exit(f"{args.name} is not an INCLUDE_ASM function in {args.src}")
    folder = m.group(1)
    candidate = Path(args.candidate).read_text().strip()

    obj = ROOT / "build" / args.src.replace(".c", ".o")
    src.write_text(substitute(text, m.group(0), candidate))
    try:
        res = run(["make", str(obj.relative_to(ROOT))])
        if res.returncode != 0:
            print(res.stderr[-3000:])
            sys.exit("compile failed")
        ours, orig = compiled(obj, args.name), original(folder, args.name)
        diffs = 0
        for i in range(max(len(ours), len(orig))):
            o = ours[i] if i < len(ours) else (None, "")
            g = orig[i] if i < len(orig) else (None, "")
            same = o[0] is not None and g[0] is not None and mask(o[0], g[1]) == mask(g[0], g[1])
            diffs += not same
            print(f"{'  ' if same else '>>'} {o[1][:38]:38} | {g[1]}")
        print(f"\n{len(ours)} vs {len(orig)} instructions, {diffs} differ")
        keep = args.keep and diffs == 0 and "matches the original" in run(["make"]).stdout
    finally:
        if not (args.keep and keep):
            src.write_text(text)
    if args.keep:
        print("kept" if keep else "restored")


if __name__ == "__main__":
    main()
