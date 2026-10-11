#!/usr/bin/env python3
"""First-pass decompilation: try m2c's output for each INCLUDE_ASM function.

For every function still included as asm in SRC, run m2c, substitute the
result, and rebuild. A function is kept only when `make` reports a
byte-identical executable; otherwise the INCLUDE_ASM line is restored.

Usage: auto_m2c.py SRC [--max-size BYTES] [--only NAME ...]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT.parent / ".venv/bin/python"
M2C = ROOT.parent / "tools/m2c/m2c.py"
INCLUDE_RE = re.compile(r'^INCLUDE_ASM\("([^"]+)", (\w+)\);$', re.M)
SIZE_RE = re.compile(r"^nonmatching \w+, 0x([0-9A-Fa-f]+)", re.M)


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def build_ok():
    res = run(["make"])
    return "matches the original" in res.stdout


def context_for(src_text):
    """Preprocessed current source, minus asm includes, for m2c --context."""
    body = INCLUDE_RE.sub("", src_text)
    res = run(["cpp", "-undef", "-P", "-DM2CTX", "-Iinclude", "-"], input=body)
    return res.stdout


def m2c(asm_path, ctx_path):
    res = run([str(PYTHON), str(M2C), "--target", "mipsel-gcc-c", "--valid-syntax",
               "--globals", "used", "--context", str(ctx_path), str(asm_path)])
    if res.returncode != 0 or "M2C_ERROR" in res.stdout:
        return None
    return res.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--max-size", type=lambda s: int(s, 0), default=0x400)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    src = ROOT / args.src
    ctx_path = ROOT / "build/m2c_ctx.c"
    ctx_path.parent.mkdir(exist_ok=True)

    if not build_ok():
        sys.exit("baseline build does not match; fix that first")

    candidates = []
    for folder, name in INCLUDE_RE.findall(src.read_text()):
        asm = ROOT / folder / f"{name}.s"
        size = int(SIZE_RE.search(asm.read_text()).group(1), 16)
        if size <= args.max_size and (not args.only or name in args.only):
            candidates.append((size, folder, name, asm))

    matched, failed = [], []
    for size, folder, name, asm in sorted(candidates):
        text = src.read_text()
        ctx_path.write_text(context_for(text))
        code = m2c(asm, ctx_path)
        line = f'INCLUDE_ASM("{folder}", {name});'
        if code is None:
            failed.append((name, size, "m2c"))
            continue
        src.write_text(text.replace(line, code, 1))
        if build_ok():
            matched.append((name, size))
            print(f"MATCH  {name} ({size:#x})", flush=True)
        else:
            src.write_text(text)
            failed.append((name, size, "build"))
            print(f"fail   {name} ({size:#x})", flush=True)

    if not build_ok():
        sys.exit("final build does not match -- inspect the source")
    print(f"\n{len(matched)} matched, {len(failed)} left")


if __name__ == "__main__":
    main()
