#!/usr/bin/env python3
"""The launcher's HD graphics: the ready pack for this disc, else built from it.

    hd_auto.py --disc GAME.cue --pack mods/texture-packs/SCES-00893 --data hd-build
               [--parent-pid PID]

First it looks for the finished pack of this PAL version (the --pack folder's
name, e.g. SCES-00891) in the project's GitHub release "hd-packs", made by
hercules/tools/hd_pack_release.py and listed with their SHA-256 in
SHA256SUMS.txt there:
  hd-<serial>-core.tar.xz   sprites + HUD + config.yaml
  hd-<serial>-levels.tar    level textures (PNGs, no further compression)
  hd-<serial>-from-<other>.tar.xz
                            only what differs from the pack of <other>, used
                            when that pack, from this same release, is already
                            installed next to --pack (tens of MB instead of GB)
They are downloaded and checked one by one, unpacked next to --pack and swapped
in as a whole; hd-release.json in the pack says which release files it equals.
Only the graphics come from there; movies, sound and everything else stay on
the player's disc. HERC_HD_API overrides the release URL (tests).

Without such an archive it builds the pack locally. That runs in the Python
that ships with the game (overlay_toolchain/python, standard
library only) and sets up, below --data, what the build needs, each piece from
its official source and checked against a fixed SHA-256:

  python     a portable CPython 3.12 (astral-sh/python-build-standalone);
             chainner_ext, the exact chaiNNer alpha fill, has no 3.13 wheels
  packages   torch (CPU) + spandrel + chainner_ext + numpy/Pillow/xxhash, pip
  models     IllustrationJaNai V1 (the-database/MangaJaNai) and HDcube 4
             Compact + Alpha (Venomalia/HDcube), from the authors' GitHub
             releases; their licences do not allow us to ship them
  build      tools/hd_pack_build.py, the same pipeline as the project's own
             pack, installed atomically to --pack

Every step resumes: downloads are checked and kept, finished images are
skipped. --data/progress.json is what the launcher shows:
{"phase", "fraction", "eta", "state": running|done|failed, "error"}.
When the launcher goes away (--parent-pid) or stops it, the whole build stops
with it; the next start continues. Afterwards only the pack and the log stay.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIN = os.name == "nt"

PBS = "https://github.com/astral-sh/python-build-standalone/releases/download/20260825/"
PYTHON = {
    "nt": ("cpython-3.12.14%2B20260825-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
           "8e6aad12ef6fc9685e67ce66253f8f72d6e8fa02cb7187e5850bd4db5ecd9e2a"),
    "posix": ("cpython-3.12.14%2B20260825-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
              "7ce4a71285d913955a76053cc7605ea96da8ecada54dba9cf395245961816421"),
}
# the versions of the chaiNNer setup our own pack was made with (numpy and
# Pillow: the oldest with Python 3.12 wheels)
PACKAGES = ["torch==2.7.0+cpu", "torchvision==0.22.0+cpu", "spandrel==0.4.1", "chainner_ext==0.3.10",
            "numpy==1.26.4", "pillow==10.4.0", "xxhash==3.5.0"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
MODELS = [
    ("https://github.com/the-database/MangaJaNai/releases/download/1.0.0/IllustrationJaNai_V1_ModelsOnly.zip",
     "6f5496f5ded597474290403de73d7a46c3f8ed328261db2e6ff830a415a6f60b",
     {"4x_IllustrationJaNai_V1_DAT2_190k.pth":
      ("IllustrationJaNai/4x_IllustrationJaNai_V1_DAT2_190k.pth",
       "a82f3a2d8d1c676171b86a00048b7a624e3c62c87ec701012f106a171c309fbe")}),
    ("https://github.com/Venomalia/HDcube/releases/download/4.0/4xHDcube4Compact.zip",
     "7893007bd7b92ec3185223369ca0d340c4bfde56c958047abfd25d21d04681ed",
     {"Models/HDcube/4xHDCube4Compact.pth":
      ("Models/HDcube/4xHDCube4Compact.pth",
       "f841188a346581b0e851f6306b69d50da0f5ac668498bb46a32c7c1c03589e58"),
      "Models/HDcube/4xHDcube-Alpha.pth":
      ("Models/HDcube/4xHDcube-Alpha.pth",
       "1781430c1613a037aed1f4eb7493118bff030e0fd5a2bbff641d9bf23f990d88"),
      "Models/HDcube/LICENSE.txt": ("Models/HDcube/LICENSE.txt", None)}),
]
# share of the whole run (the build itself: hours on a CPU)
PHASES = [("python", 0.3), ("packages", 1.5), ("models", 0.4), ("build", 97.8)]
DOWNLOAD_PHASES = [("download", 85.0), ("install", 15.0)]
HD_API = os.environ.get("HERC_HD_API",
                        "https://api.github.com/repos/obaidr1/hercules-recompiled/releases/tags/hd-packs")
DOWNLOAD_FREE_GB = 4  # levels.tar ~1.3 + unpacked pack ~1.8, with room
DIFF_FREE_GB = 1      # the difference to another pack; the rest is hard links
MARKER = "hd-release.json"
FREE_GB = 6          # python + packages ~1.2, downloads ~0.4, work tree ~2.5, pack ~0.7
NO_WINDOW = 0x08000000 if WIN else 0     # CREATE_NO_WINDOW


class Failed(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code


class Progress:
    def __init__(self, path, phases=None):
        self.path = path
        self.phases = phases or PHASES
        self.phase, self.part, self.eta = "", 0.0, None

    def set(self, phase, part=0.0, eta=None, state="running", error=None):
        self.phase, self.part, self.eta = phase, part, eta
        before = 0.0
        for name, w in self.phases:
            if name == phase:
                break
            before += w
        w = dict(self.phases).get(phase, 0.0)
        total = sum(w for _, w in self.phases)
        frac = 1.0 if state == "done" else min(1.0, (before + w * part) / total)
        data = {"phase": phase, "fraction": round(frac, 4), "eta": eta, "state": state, "error": error,
                "updated": int(time.time())}
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data))
            tmp.replace(self.path)
        except OSError:          # Windows: the launcher has it open; the next write wins
            pass


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ssl_context():
    import ssl
    ctx = ssl.create_default_context()
    if not WIN and not ctx.get_ca_certs():
        for f in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
                  "/etc/ssl/ca-bundle.pem", "/etc/ssl/cert.pem"):
            if os.path.exists(f):
                ctx.load_verify_locations(f)
                break
    return ctx


def download(url, dst, digest, report):
    """url -> dst, checked; a verified file from an earlier run is kept."""
    if dst.exists() and sha256(dst) == digest:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    log(f"download {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hercules-recompiled-hd"})
        with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    report(got / total)
    except OSError as e:
        raise Failed("network", f"{url}: {e}")
    if sha256(part) != digest:
        part.unlink()
        raise Failed("download", f"{url}: checksum mismatch")
    part.replace(dst)
    return dst


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "hercules-recompiled-hd",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def release_assets():
    """{name: (url, sha256, size)} of the checked assets of the hd-packs release, or None."""
    try:
        rel = fetch_json(HD_API)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None                          # no release (yet): build locally
        raise Failed("network", f"{HD_API}: {e}")
    except OSError as e:
        raise Failed("network", f"{HD_API}: {e}")
    assets = {x["name"]: x for x in rel.get("assets", [])}
    if "SHA256SUMS.txt" not in assets:
        return None
    req = urllib.request.Request(assets["SHA256SUMS.txt"]["browser_download_url"],
                                 headers={"User-Agent": "hercules-recompiled-hd"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
            sums = r.read().decode("utf-8")
    except OSError as e:
        raise Failed("network", f"SHA256SUMS.txt: {e}")
    digests = {line.split()[-1].lstrip("*"): line.split()[0].lower()
               for line in sums.splitlines() if len(line.split()) >= 2}
    return {n: (x["browser_download_url"], digests[n], x["size"]) for n, x in assets.items() if n in digests}


def release_marker(serial, assets):
    """What hd-release.json says for the full pack of serial in this release."""
    return {"serial": serial, "core": assets[f"hd-{serial}-core.tar.xz"][1],
            "levels": assets[f"hd-{serial}-levels.tar"][1]}


def plan_download(pack, assets):
    """(base pack or None, [asset names]) for pack, or None if the release lacks it.

    A base is another pack next to this one whose hd-release.json matches this
    release: then only the difference to it is needed, the smallest one wins.
    """
    serial = pack.name
    full = [f"hd-{serial}-core.tar.xz", f"hd-{serial}-levels.tar"]
    if not all(n in assets for n in full):
        return None
    best = None
    for other in sorted(pack.parent.iterdir()) if pack.parent.is_dir() else []:
        name = f"hd-{serial}-from-{other.name}.tar.xz"
        if other.name == serial or name not in assets:
            continue
        try:
            mark = json.loads((other / MARKER).read_text())
            if mark != release_marker(other.name, assets):
                continue
        except (OSError, ValueError, KeyError):
            continue
        if best is None or assets[name][2] < assets[best[1]][2]:
            best = (other, name)
    return (best[0], [best[1]]) if best else (None, full)


def link_tree(src, dst):
    """dst = src as hard links (a copy where that fails). Installed packs are
    only ever swapped as a whole, never written into, so sharing files is safe."""
    for d, dirs, files in os.walk(src):
        rel = Path(d).relative_to(src)
        if rel == Path("."):
            dirs[:] = [x for x in dirs if x != "dumps"]
            files = [f for f in files if f != MARKER]
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            try:
                os.link(Path(d) / f, dst / rel / f)
            except OSError:
                shutil.copy2(Path(d) / f, dst / rel / f)


def unpack(path, dst, report):
    """A .tar / .tar.xz from the release into dst. In a difference, copy.txt
    (DEST<TAB>SOURCE, files already in dst) comes first, then remove.txt."""
    root = os.path.normcase(str(dst.resolve())) + os.sep

    def target(name):
        t = (dst / name).resolve()
        if not os.path.normcase(str(t)).startswith(root):
            raise Failed("download", f"bad path in archive: {name}")
        return t
    size = path.stat().st_size
    with open(path, "rb") as raw, \
            tarfile.open(fileobj=raw, mode="r|xz" if path.name.endswith(".xz") else "r|") as t:
        for n, m in enumerate(t):
            if not m.isfile():
                raise Failed("download", f"not a file in archive: {m.name}")
            src = t.extractfile(m)
            if m.name == "copy.txt":             # all sources linked before any is replaced
                staged = []
                for line in src.read().decode("utf-8").splitlines():
                    if not line:
                        continue
                    d, s = line.split("\t")
                    out = target(d)
                    tmp = out.with_name(out.name + ".copy")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    tmp.unlink(missing_ok=True)
                    try:
                        os.link(target(s), tmp)
                    except OSError:
                        shutil.copy2(target(s), tmp)
                    staged.append((tmp, out))
                for tmp, out in staged:
                    os.replace(tmp, out)
                continue
            if m.name == "remove.txt":
                for name in src.read().decode("utf-8").splitlines():
                    if name:
                        target(name).unlink(missing_ok=True)
                continue
            out = target(m.name)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.unlink(missing_ok=True)          # may be a hard link into the base pack
            with open(out, "wb") as f:
                shutil.copyfileobj(src, f)
            if n % 500 == 0:
                report(raw.tell() / size)


def install_dir(src, pack):
    """Swap the unpacked folder in as the pack, never leaving it half written."""
    old = pack.with_name(pack.name + ".replaced")
    if old.exists():
        shutil.rmtree(old)
    if pack.exists():
        pack.rename(old)
    src.rename(pack)
    shutil.rmtree(old, ignore_errors=True)


def phase_download(a, data, prog):
    """The finished pack of this PAL version from the release; False if there is none."""
    serial = a.pack.name
    assets = release_assets()
    found = plan_download(a.pack, assets) if assets else None
    if found is None:
        log(f"no ready pack for {serial}: building it from the disc")
        return False
    base, names = found
    total = sum(assets[n][2] for n in names)
    need = DIFF_FREE_GB if base else DOWNLOAD_FREE_GB
    free = shutil.disk_usage(data).free / 2**30
    if free < need:
        raise Failed("disk", f"{free:.1f} GB free, {need} needed")
    tmp = a.pack.with_name(a.pack.name + ".installing")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    if base:
        log(f"{serial}: only the difference to the installed {base.name}")
        link_tree(base, tmp)
    # each archive counts once for the download and a quarter for unpacking it
    weight, done = 1.25 * total, 0
    for name in names:
        url, digest, size = assets[name]
        path = download(url, data / "downloads" / name, digest,
                        lambda f: prog.set("download", (done + f * size) / weight))
        unpack(path, tmp, lambda f: prog.set("download", (done + size + 0.25 * f * size) / weight))
        path.unlink()                            # keeps the disk need at one archive
        done += 1.25 * size
        log(f"{name}: {size / 2**20:.0f} MB unpacked")
    prog.set("install", 0.5)
    if not (tmp / "replacements").is_dir() or not (tmp / "config.yaml").exists():
        raise Failed("download", "archives without config.yaml / replacements/")
    (tmp / MARKER).write_text(json.dumps(release_marker(serial, assets)))
    a.pack.parent.mkdir(parents=True, exist_ok=True)
    install_dir(tmp, a.pack)
    log(f"HD pack {serial} downloaded and installed ({total / 2**20:.0f} MB, {', '.join(names)})")
    return True


def run(cmd, logf, **kw):
    log("run " + " ".join(map(str, cmd)))
    p = subprocess.Popen([str(c) for c in cmd], stdout=logf, stderr=subprocess.STDOUT,
                         creationflags=NO_WINDOW, **kw)
    return p


def wait(p, what):
    if p.wait():
        raise Failed("failed", f"{what} ended with {p.returncode}")


# ------------------------------------------------------------------ phases
def phase_python(data, prog):
    root = data / "python"
    exe = root / ("python/python.exe" if WIN else "python/bin/python3")
    if (root / ".ok").exists() and exe.exists():
        return exe
    prog.set("python")
    name, digest = PYTHON["nt" if WIN else "posix"]
    tar = download(PBS + name, data / "downloads" / name.replace("%2B", "+"), digest,
                   lambda f: prog.set("python", 0.9 * f))
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    with tarfile.open(tar) as t:
        t.extractall(root, filter="data")
    (root / ".ok").touch()
    return exe


def phase_packages(py, data, prog, logf):
    stamp = data / "python" / ".packages"
    want = "\n".join(PACKAGES)
    if stamp.exists() and stamp.read_text() == want:
        return
    prog.set("packages")
    p = run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-cache-dir", "--progress-bar", "off",
             "--only-binary=:all:", "--index-url", TORCH_INDEX, "--extra-index-url", "https://pypi.org/simple",
             *PACKAGES], logf)
    t0 = time.time()
    while p.poll() is None:              # no byte count from pip: a slow ramp
        prog.set("packages", min(0.95, (time.time() - t0) / 600))
        time.sleep(2)
    if p.returncode:
        raise Failed("network", f"pip install ended with {p.returncode}")
    stamp.write_text(want)


def phase_models(data, prog):
    models = data / "models"
    todo = [m for m in MODELS if not all(
        (models / dst).exists() and (h is None or sha256(models / dst) == h) for dst, h in m[2].values())]
    if not todo:
        return models
    prog.set("models")
    for i, (url, digest, members) in enumerate(todo):
        z = download(url, data / "downloads" / url.rsplit("/", 1)[1], digest,
                     lambda f, i=i: prog.set("models", (i + f) / len(todo)))
        with zipfile.ZipFile(z) as zf:
            for member, (dst, h) in members.items():
                out = models / dst
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(out, "wb") as f:
                    shutil.copyfileobj(src, f)
                if h and sha256(out) != h:
                    raise Failed("download", f"{member}: checksum mismatch")
    return models


def phase_build(py, data, models, a, prog, logf):
    prog.set("build")
    tool = HERE / "tools" / "hd_pack_build.py"
    if WIN:                 # no console windows for the steps it starts
        pyw = py.with_name("pythonw.exe")
        py = pyw if pyw.exists() else py
    watch = data / "build.progress.json"
    threads = str(max(1, (os.cpu_count() or 2) - 1))      # one core stays for the game
    # KMP_AFFINITY: no pinning of threads to cores (the game shares them;
    # Wine also lacks the NUMA call Intel's OpenMP uses to pin)
    env = dict(os.environ, OMP_NUM_THREADS=threads, MKL_NUM_THREADS=threads, KMP_AFFINITY="disabled",
               PYTHONUTF8="1")
    p = run([py, tool, a.disc, data / "work", "--install", a.pack, "--models", models,
             "--ml-python", py, "--progress", watch], logf, env=env)
    # Remaining time from the pace of the last minutes of this run: a resumed
    # run first skips everything already made, which says nothing about speed.
    t0, samples = time.time(), []
    while p.poll() is None:
        try:
            f = float(json.loads(watch.read_text()).get("fraction") or 0)
        except (OSError, ValueError):
            f = None
        if f is not None:
            now = time.time()
            if now - t0 > 180:
                samples.append((now, f))
                samples = [x for x in samples if now - x[0] <= 900]
            eta = None
            if len(samples) > 1 and samples[-1][0] - samples[0][0] >= 120 and samples[-1][1] > samples[0][1]:
                rate = (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])
                eta = int((1 - f) / rate)
            prog.set("build", f, eta)
        time.sleep(3)
    if p.returncode:
        raise Failed("failed", f"hd_pack_build ended with {p.returncode}")


# -------------------------------------------------------- process handling
def lower_priority():
    try:
        if WIN:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
        else:
            os.nice(19)
    except (OSError, AttributeError):
        pass


def tie_children():
    """Children die with this process: own process group / a kill-on-close job."""
    if not WIN:
        try:
            os.setpgrp()
        except OSError:
            pass
        return
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        job = k.CreateJobObjectW(None, None)

        class Basic(ctypes.Structure):
            _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                        ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD),
                        ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]

        class Ext(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", ctypes.c_uint64 * 6), ("p", ctypes.c_size_t),
                        ("j", ctypes.c_size_t), ("pp", ctypes.c_size_t), ("pj", ctypes.c_size_t)]
        info = Ext()
        info.Basic.LimitFlags = 0x2000           # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        k.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(k.GetCurrentProcess()))
        tie_children.job = job                   # keep the handle open for our lifetime
    except (OSError, AttributeError):
        pass


def stop_all(*_):
    if not WIN:
        if threading.current_thread() is threading.main_thread():   # only there may it set handlers
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            os.killpg(0, signal.SIGTERM)
        except OSError:
            pass
    os._exit(3)                                  # Windows: closing the job ends the children


def watch_parent(pid):
    def alive():
        if WIN:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x00100000, False, pid)         # SYNCHRONIZE
            if not h:
                return False
            r = k.WaitForSingleObject(h, 0)
            k.CloseHandle(h)
            return r == 0x102                                 # WAIT_TIMEOUT: still running
        # not getppid(): SDL starts background processes through a double
        # fork, so the launcher is never our parent
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return True

    def loop():
        while alive():
            time.sleep(2)
        log("launcher gone, stopping")
        stop_all()
    threading.Thread(target=loop, daemon=True).start()


def single_instance(data):
    f = open(data / "hd.lock", "a+")
    try:
        if WIN:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--disc", type=Path, required=True)
    ap.add_argument("--pack", type=Path, required=True, help="texture pack folder to install to")
    ap.add_argument("--data", type=Path, required=True, help="work folder (several GB while it runs)")
    ap.add_argument("--parent-pid", type=int)
    ap.add_argument("--no-download", action="store_true", help="always build from the disc")
    a = ap.parse_args()
    data = a.data.resolve()
    data.mkdir(parents=True, exist_ok=True)
    lock = single_instance(data)
    if lock is None:
        return 0                                 # already running
    logf = open(data / "hd-build.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = logf
    prog = Progress(data / "progress.json")
    tie_children()
    lower_priority()
    if not WIN:
        signal.signal(signal.SIGTERM, stop_all)
    if a.parent_pid:
        watch_parent(a.parent_pid)
    log(f"HD build: disc {a.disc}, pack {a.pack}")
    try:
        if not a.disc.exists():
            raise Failed("disc", str(a.disc))
        if not a.no_download:
            prog.phases = DOWNLOAD_PHASES
            if phase_download(a, data, prog):
                prog.set("install", 1.0, state="done")
                shutil.rmtree(data / "downloads", ignore_errors=True)
                return 0
            prog.phases = PHASES
        if not (data / "python" / ".packages").exists() or not (data / "work").exists():
            free = shutil.disk_usage(data).free / 2**30
            if free < FREE_GB:
                raise Failed("disk", f"{free:.1f} GB free, {FREE_GB} needed")
        py = phase_python(data, prog)
        phase_packages(py, data, prog, logf)
        models = phase_models(data, prog)
        phase_build(py, data, models, a, prog, logf)
    except Failed as e:
        log(f"failed: {e}")
        prog.set(prog.phase or "python", prog.part, state="failed", error=e.code)
        return 1
    except Exception as e:                       # noqa: BLE001 - reported to the launcher
        log(f"failed: {e!r}")
        prog.set(prog.phase or "python", prog.part, state="failed", error="failed")
        return 1
    prog.set("build", 1.0, state="done")
    log("HD pack installed; removing the build files")
    for d in ("work", "downloads", "python", "models"):
        shutil.rmtree(data / d, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
