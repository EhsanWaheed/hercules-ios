#!/usr/bin/env python3
"""Batch: m2c draft -> decomp-permuter -> keep if the full build matches.

Usage: permute_all.py SRC [--max-size BYTES] [--seconds N] [--jobs N]

For each INCLUDE_ASM function in SRC (smallest first), an m2c draft is
permuted for up to N seconds. A zero-score result is substituted into SRC
and kept only when `make` still produces a byte-identical executable.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_m2c as am  # noqa: E402

ROOT = am.ROOT
PERMUTER = ROOT.parent / "tools/decomp-permuter/permuter.py"


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def extract_function(source, name):
    """Return the definition of NAME from a permuter output source."""
    m = re.search(rf"^[^\n;]*\b{re.escape(name)}\s*\([^;]*?\)\s*\{{", source, re.M)
    if not m:
        return None
    depth, i = 0, m.start()
    for j in range(m.end() - 1, len(source)):
        depth += {"{": 1, "}": -1}.get(source[j], 0)
        if depth == 0:
            return source[i:j + 1]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--max-size", type=lambda s: int(s, 0), default=0x100)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()

    src = ROOT / args.src
    ctx = ROOT / "build/m2c_ctx.c"
    work = ROOT / "build/permute"
    work.mkdir(parents=True, exist_ok=True)

    todo = []
    for folder, name in am.INCLUDE_RE.findall(src.read_text()):
        size = int(am.SIZE_RE.search((ROOT / folder / f"{name}.s").read_text()).group(1), 16)
        if size <= args.max_size:
            todo.append((size, folder, name))

    matched = []
    for size, folder, name in sorted(todo):
        text = src.read_text()
        ctx.write_text(am.context_for(text))
        code = am.m2c(ROOT / folder / f"{name}.s", ctx)
        if code is None:
            print(f"skip   {name} (m2c failed)", flush=True)
            continue
        decls, body = am.split_decls(code, text)
        cand = work / f"{name}.c"
        cand.write_text("\n".join(decls) + "\n" + body + "\n")

        setup = run(["tools/permute_setup.sh", name, str(cand), folder])
        if setup.returncode != 0:
            print(f"skip   {name} (draft does not compile)", flush=True)
            continue
        pdir = ROOT / "permuter" / name
        try:
            run([str(am.PYTHON), str(PERMUTER), str(pdir), f"-j{args.jobs}", "--stop-on-zero"],
                timeout=args.seconds)
        except subprocess.TimeoutExpired:
            pass
        zero = [d for d in pdir.glob("output-0-*") if (d / "source.c").exists()]
        if not zero:
            print(f"open   {name} ({size:#x})", flush=True)
            continue
        func = extract_function((zero[0] / "source.c").read_text(), name)
        if func is None:
            print(f"open   {name} ({size:#x}, could not extract result)", flush=True)
            continue
        new_text = am.substitute(text, f'INCLUDE_ASM("{folder}", {name});',
                                 "\n".join(decls) + "\n" + func)
        src.write_text(new_text)
        if am.build_ok():
            matched.append(name)
            print(f"MATCH  {name} ({size:#x})", flush=True)
        else:
            src.write_text(text)
            print(f"open   {name} ({size:#x}, permuter match failed full build)", flush=True)

    if not am.build_ok():
        sys.exit("final build does not match -- inspect the source")
    print(f"\n{len(matched)} matched")


if __name__ == "__main__":
    main()
