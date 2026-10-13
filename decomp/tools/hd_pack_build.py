#!/usr/bin/env python3
"""Build the HD texture pack from the user's own disc, start to finish.

    python3 tools/hd_pack_build.py DISC.cue WORK_DIR [--install PACK_DIR]
        [--models DIR] [--ml-python PY] [--progress FILE]

Every step reads only the disc image and writes below WORK_DIR, so nothing
of the game ships with the project. Steps (each skips work already done, so
an interrupted run continues where it stopped):

  extract    disc files (tools/iso_extract.py)              seconds
  sprites    decode SD1/SD3/SD4 frames (sprites.py dump)     ~1 min
  levels     cut level textures (cut_textures.py)            seconds
  hud        HUD page, palettes, slot frames from STP1/STP2  seconds
  upscale    sprites: IllustrationJaNai DAT2, SD3/S3_1 (Hercules seen from
             behind): HDcube; levels: HDcube; all with the HDcube-Alpha
             model for transparency (the project's chaiNNer chains)     hours
  palettize  snap sprites back onto their pixel art           minutes
  pack       sprite blocks, sprite/level/HUD replacements, config.yaml

--install copies the finished pack to PACK_DIR (replacing it as a whole,
never half-written). --progress keeps a JSON file up to date:
{"step", "steps", "index", "done", "total", "fraction", "eta", "state"}.

Models (not redistributable, see their licences) are looked up in --models:
  IllustrationJaNai/4x_IllustrationJaNai_V1_DAT2_190k.pth
  Models/HDcube/4xHDCube4Compact.pth
  Models/HDcube/4xHDcube-Alpha.pth
--ml-python is a Python with torch + spandrel (+ chainner_ext for the exact
chaiNNer alpha fill), e.g. chaiNNer's bundled one. Plain steps run in the
Python that runs this script (numpy, Pillow).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECOMP = HERE.parent
DAT2 = "IllustrationJaNai/4x_IllustrationJaNai_V1_DAT2_190k.pth"
HDCUBE = "Models/HDcube/4xHDCube4Compact.pth"
ALPHA = "Models/HDcube/4xHDcube-Alpha.pth"
BACK_VIEW = "SD3/S3_1"           # Hercules from behind (run levels): HDcube looks better here
CHAIN = ["--fill", "all", "--alpha-threshold", "0.05"]

# relative weight of each step (≈ share of the run time on a CPU)
STEPS = [("extract", 0.2), ("sprites", 0.5), ("levels", 0.2), ("hud", 0.1),
         ("upscale-sprites", 90.0), ("upscale-backview", 0.5), ("upscale-levels", 2.0),
         ("upscale-hud", 1.5), ("palettize", 3.0), ("cells", 1.0), ("pack-sprites", 1.5),
         ("pack-levels", 0.5), ("pack-hud", 0.3), ("install", 0.2)]


class Progress:
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.t0 = time.time()
        self.index, self.step = 0, ""
        self.done = self.total = 0
        self.weight_done = 0.0
        self.state = "running"

    def fraction(self):
        total_w = sum(w for _, w in STEPS)
        cur = dict(STEPS).get(self.step, 0) * (self.done / self.total if self.total else 0)
        return min(1.0, (self.weight_done + cur) / total_w)

    def write(self):
        if not self.path:
            return
        f = self.fraction()
        el = time.time() - self.t0
        eta = el / f - el if f > 0.01 else None
        data = {"step": self.step, "steps": len(STEPS), "index": self.index, "done": self.done,
                "total": self.total, "fraction": round(f, 4), "elapsed": int(el),
                "eta": int(eta) if eta is not None else None, "state": self.state}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path)

    def begin(self, step):
        self.index = [s for s, _ in STEPS].index(step) + 1
        self.step, self.done, self.total = step, 0, 0
        print(f"[{self.index}/{len(STEPS)}] {step}", flush=True)
        self.write()

    def end(self):
        self.weight_done += dict(STEPS)[self.step]
        self.done = self.total
        self.write()


def run(cmd, cwd=None, env=None, watch=None, prog=None):
    """Run a tool; while it runs, copy its --progress file into ours."""
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env)
    while p.poll() is None:
        if watch and prog and watch.exists():
            try:
                d = json.loads(watch.read_text())
                prog.done, prog.total = d["done"], d["total"]
                prog.write()
            except (ValueError, KeyError, OSError):
                pass
        time.sleep(2)
    if p.returncode:
        raise SystemExit(f"step failed ({p.returncode}): {' '.join(map(str, cmd))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("disc", type=Path, help=".cue (or .bin) of the game")
    ap.add_argument("work", type=Path)
    ap.add_argument("--install", type=Path, help="texture pack folder to (re)place")
    ap.add_argument("--models", type=Path, default=Path.home() / "psx-decomp/models")
    ap.add_argument("--ml-python", type=Path,
                    default=Path.home() / ".config/chaiNNer/python/python/bin/python3.11")
    ap.add_argument("--progress", type=Path)
    a = ap.parse_args()

    for m in (DAT2, HDCUBE, ALPHA):
        if not (a.models / m).exists():
            sys.exit(f"model missing: {a.models / m}")
    W = a.work.resolve()
    W.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HERC_ROOT=str(W))
    py = sys.executable
    prog = Progress(a.progress)
    ml = [a.ml_python, HERE / "upscale_model.py"]
    A = W / "assets"

    try:
        prog.begin("extract")
        if not (W / "files/EX/ENGINE1.").exists():
            run([py, HERE / "iso_extract.py", a.disc, W / "files", "--list", W / "filelist.txt"])
        prog.end()

        prog.begin("sprites")
        if not (A / "sprites/.done").exists():
            srcs = sorted(p.relative_to(W).as_posix() for d in ("SD1", "SD3", "SD4")
                          for p in (W / "files" / d).glob("S*"))
            run([py, HERE / "sprites.py", "dump", "assets/sprites", *srcs], cwd=W, env=env)
            (A / "sprites/.done").touch()
        prog.end()

        prog.begin("levels")
        if not (A / "textures_cut/.done").exists():
            lv = sorted(p.relative_to(W).as_posix() for p in (W / "files/LV").glob("L*.1"))
            run([py, HERE / "cut_textures.py", "assets/textures_cut", *lv], cwd=W, env=env)
            (A / "textures_cut/.done").touch()
        prog.end()

        prog.begin("hud")
        run([py, HERE / "hud_texpack.py", "from-disc", W / "files", "--work", A / "hud"])
        prog.end()

        watch = W / "upscale.progress.json"
        prog.begin("upscale-sprites")
        run([*ml, a.models / DAT2, A / "sprites", A / "sprites_hd/raw", "--alpha-model", a.models / ALPHA,
             *CHAIN, "--exclude", BACK_VIEW, "--progress", watch], watch=watch, prog=prog)
        prog.end()
        prog.begin("upscale-backview")
        run([*ml, a.models / HDCUBE, A / "sprites", A / "sprites_hd/raw", "--alpha-model", a.models / ALPHA,
             *CHAIN, "--only", BACK_VIEW, "--progress", watch], watch=watch, prog=prog)
        prog.end()
        prog.begin("upscale-levels")
        run([*ml, a.models / HDCUBE, A / "textures_cut", A / "textures_hd", "--alpha-model", a.models / ALPHA,
             *CHAIN, "--progress", watch], watch=watch, prog=prog)
        prog.end()

        pack = W / "pack"
        prog.begin("upscale-hud")
        if not (xxh := HERE / "native/libxxh3.so").exists():
            run(["make", xxh.relative_to(DECOMP)], cwd=DECOMP)
        hud_pack = W / "pack-hud"
        run([py, HERE / "hud_texpack.py", "build", hud_pack, "--work", A / "hud", "--python", a.ml_python,
             "--model", a.models / DAT2, "--progress", watch], watch=watch, prog=prog)
        prog.end()

        prog.begin("palettize")
        run([py, HERE / "sprite_palettize.py", A / "sprites_hd/raw", A / "sprites", A / "sprites_hd/final"])
        prog.end()

        prog.begin("cells")
        # As done by hand for our pack: everything but the back view in one
        # set, the back view (HDcube) on its own; its names that the main set
        # already has (blocks shared with other files) stay DAT2.
        cells, back_cells = A / "sprite_cells", A / "sprite_cells_backview"
        for d in (cells, back_cells):
            if d.exists():
                shutil.rmtree(d)
        run([py, HERE / "sprite_cells.py", A / "sprites_hd/final", cells, "--scale", "4",
             "--skip", BACK_VIEW], env=env)
        run([py, HERE / "sprite_cells.py", A / "sprites_hd/final", back_cells, "--scale", "4",
             "--only", BACK_VIEW], env=env)
        prog.end()

        new, back = W / "pack.new", W / "pack.backview"
        for d in (new, back):
            if d.exists():
                shutil.rmtree(d)
        prog.begin("pack-sprites")
        run([py, HERE / "sprite_texpack.py", cells, new], env=env)
        run([py, HERE / "sprite_texpack.py", back_cells, back], env=env)
        have = {f.name for f in (new / "replacements/sprites").rglob("*.png")}
        for f in (back / "replacements/sprites").rglob("*.png"):
            if f.name not in have:
                dst = new / "replacements/sprites" / f.relative_to(back / "replacements/sprites")
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(f, dst)
        shutil.rmtree(back)
        prog.end()
        prog.begin("pack-levels")
        run([py, HERE / "level_texpack.py", A / "textures_cut", A / "textures_hd", new], env=env)
        prog.end()
        prog.begin("pack-hud")
        shutil.copytree(hud_pack / "replacements/hud", new / "replacements/hud")
        (new / "config.yaml").write_text(
            "# Level textures key off one 384x512 upload; later partial writes must\n"
            "# only cut out what they overwrite instead of dropping the whole upload.\n"
            "MaxVRAMWriteSplits: 64\n")
        if pack.exists():
            shutil.rmtree(pack)
        new.rename(pack)
        prog.end()

        prog.begin("install")
        if a.install:
            dst = a.install
            tmp = dst.with_name(dst.name + ".installing")
            if tmp.exists():
                shutil.rmtree(tmp)
            dst.parent.mkdir(parents=True, exist_ok=True)

            def link_or_copy(src, target):
                try:
                    os.link(src, target)          # same disk: no second copy of the pack
                except OSError:
                    shutil.copy2(src, target)
            shutil.copytree(pack, tmp, copy_function=link_or_copy)
            old = dst.with_name(dst.name + ".replaced")
            if dst.exists():
                if old.exists():
                    shutil.rmtree(old)
                dst.rename(old)
            tmp.rename(dst)
            if old.exists():
                shutil.rmtree(old)
        prog.end()
        prog.state = "done"
        prog.write()
        print(f"HD pack ready: {a.install or pack}")
    except (SystemExit, KeyboardInterrupt, Exception) as e:
        prog.state = "failed"
        prog.write()
        if not isinstance(e, SystemExit) or e.code not in (0, None):
            raise


if __name__ == "__main__":
    main()
