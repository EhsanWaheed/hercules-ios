#!/usr/bin/env python3
"""In-place updates for the release builds (run by the launcher).

    updater.py check    --game DIR                 -> DIR/update/check.json
    updater.py download --game DIR                 -> DIR/update/staging/ (+ progress.json)
    updater.py apply    --game DIR --wait-pid PID [--relaunch EXE]

Standard library only. `check` asks GitHub for the latest release of
obaidr1/hercules-recompiled and compares its tag with psx_game_version.txt;
the release notes are the changelog the launcher shows. `download` fetches
this platform's zip, checks it against the release's SHA256SUMS.txt and
unpacks it to update/staging. `apply` waits for the launcher to exit, copies
staging over the game folder and starts the game again. It runs in the
staged (new) Python, so nothing it replaces is in use.

Only files that are in the release zip are written; the player's files
(settings, disc path, saves, memory cards, the HD pack, the HD build) are
never in it, and PROTECTED keeps them safe even if a zip ever carried one.
Nothing is deleted. HERC_UPDATE_API overrides the release URL (tests).
"""
import argparse
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

API = os.environ.get("HERC_UPDATE_API",
                     "https://api.github.com/repos/obaidr1/hercules-recompiled/releases/latest")
WIN = os.name == "nt"
ASSET = "hercules-recompiled-windows-x64.zip" if WIN else "hercules-recompiled-linux-x64.zip"
PROTECTED_FILES = {"launcher.ini", "settings.toml", "disc.cfg", "input.ini", "keybinds.ini", "config.ini"}
PROTECTED_DIRS = {"saves", "memcards", "hd-build", "disc"}
PROTECTED_PREFIXES = ("mods/texture-packs/", "mods/state.toml")


def ctx():
    c = ssl.create_default_context()
    if not WIN and not c.get_ca_certs():
        for f in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
                  "/etc/ssl/ca-bundle.pem", "/etc/ssl/cert.pem"):
            if os.path.exists(f):
                c.load_verify_locations(f)
                break
    return c


def fetch(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": "hercules-recompiled-updater", "Accept": accept})
    return urllib.request.urlopen(req, timeout=30, context=None if url.startswith("http:") else ctx())


def version_tuple(v):
    out = []
    for part in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out + [0] * (3 - len(out)))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
    except OSError:              # Windows: the launcher is reading it; the next write wins
        pass


def cmd_check(game):
    u = game / "update"
    if not (u / "staging.json").exists():       # no update waiting to be applied
        cleanup(game)
    current = (game / "psx_game_version.txt").read_text().strip() if (game / "psx_game_version.txt").exists() else "0"
    try:
        with fetch(API) as r:
            rel = json.load(r)
    except Exception as e:                     # offline: say nothing in the launcher
        write_json(u / "check.json", {"state": "error", "error": str(e)[:200], "current": current})
        return 1
    tag = rel.get("tag_name", "")
    assets = {a["name"]: a for a in rel.get("assets", [])}
    asset = assets.get(ASSET)
    newer = bool(asset) and version_tuple(tag) > version_tuple(current)
    write_json(u / "check.json", {
        "state": "ok", "current": current, "latest": tag.lstrip("vV"), "newer": newer,
        "notes": rel.get("body", ""), "name": rel.get("name", tag),
        "url": asset["browser_download_url"] if asset else "", "size": asset["size"] if asset else 0,
        "sums": assets["SHA256SUMS.txt"]["browser_download_url"] if "SHA256SUMS.txt" in assets else "",
    })
    return 0


def cmd_download(game):
    u = game / "update"
    prog = u / "progress.json"
    try:
        info = json.loads((u / "check.json").read_text())
        if not info.get("newer"):
            raise RuntimeError("no update")
        with fetch(info["sums"], "application/octet-stream") as r:
            sums = {line.split()[1].lstrip("*"): line.split()[0]
                    for line in r.read().decode().splitlines() if len(line.split()) == 2}
        want = sums.get(ASSET)
        if not want:
            raise RuntimeError("no checksum for " + ASSET)
        zpath = u / ASSET
        h = hashlib.sha256()
        with fetch(info["url"], "application/octet-stream") as r, open(zpath, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.get("size") or 0)
            got = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                write_json(prog, {"state": "download", "fraction": got / total if total else 0})
        if h.hexdigest() != want:
            zpath.unlink()
            raise RuntimeError("checksum mismatch")
        write_json(prog, {"state": "unpack", "fraction": 1})
        staging = u / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            for m in z.infolist():
                name = m.filename
                if name.startswith("/") or ".." in Path(name).parts:
                    raise RuntimeError("bad path in zip: " + name)
                z.extract(m, staging)
                mode = (m.external_attr >> 16) & 0o777
                if mode and not WIN:
                    os.chmod(staging / name, mode)
        zpath.unlink()
        write_json(u / "staging.json", {"version": info["latest"]})
        write_json(prog, {"state": "ready", "fraction": 1, "version": info["latest"]})
        return 0
    except Exception as e:
        write_json(prog, {"state": "failed", "error": str(e)[:200]})
        return 1


def protected(rel):
    parts = rel.split("/")
    if parts[0] == "update":                    # the updater's own state; only the script itself updates
        return rel != "update/updater.py"
    # one disc and HD build per PAL release (launcher: disc-<id>.cfg, hd-build-<id>/)
    if len(parts) == 1 and parts[0].startswith("disc-") and parts[0].endswith(".cfg"):
        return True
    if parts[0].startswith("hd-build-"):
        return True
    if parts[0] == "lang" and len(parts) > 2:   # lang/<id>/: the other releases' builds, same rules
        rel = "/".join(parts[2:])
        parts = parts[2:]
    return (rel in PROTECTED_FILES or parts[0] in PROTECTED_DIRS or rel.startswith(PROTECTED_PREFIXES))


def cleanup(game):
    """Leftovers of the last update: the unpacked release, replaced files (Windows)."""
    shutil.rmtree(game / "update" / "staging", ignore_errors=True)
    for old in game.rglob("*.old"):
        rel = old.relative_to(game).as_posix()
        if rel.split("/")[0] in PROTECTED_DIRS or rel.startswith(PROTECTED_PREFIXES):
            continue
        if old.with_name(old.name[:-4]).exists():
            try:
                old.unlink()
            except OSError:
                pass


def wait_pid(pid, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        if WIN:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x00100000, False, pid)        # SYNCHRONIZE
            if not h:
                return
            r = k.WaitForSingleObject(h, 500)
            k.CloseHandle(h)
            if r == 0:
                return
        else:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.2)


def cmd_apply(game, pid, relaunch):
    u = game / "update"
    staging = u / "staging"
    log = open(u / "apply.log", "a", encoding="utf-8")
    try:
        if pid:
            wait_pid(pid)
        time.sleep(0.5)
        copied = 0
        for src in staging.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(staging).as_posix()
            if protected(rel):
                log.write(f"kept {rel}\n")
                continue
            dst = game / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(20):               # Windows: a file can stay locked briefly
                try:
                    if dst.exists() and WIN:
                        old = dst.with_name(dst.name + ".old")
                        if old.exists():
                            old.unlink()
                        dst.replace(old)
                    shutil.copy2(src, dst)
                    break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("cannot write " + rel)
            copied += 1
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} applied {copied} files\n")
        write_json(u / "applied.json", json.loads((u / "staging.json").read_text()))
        for f in (u / "progress.json", u / "check.json", u / "staging.json"):
            f.unlink(missing_ok=True)
    except Exception as e:
        log.write(f"failed: {e}\n")
        write_json(u / "progress.json", {"state": "failed", "error": str(e)[:200]})
    finally:
        log.close()
    if relaunch:
        flags = 0x00000008 if WIN else 0            # DETACHED_PROCESS
        subprocess.Popen([relaunch], cwd=str(game), creationflags=flags, close_fds=True,
                         start_new_session=not WIN)
    # staging (with the Python running this) is cleared by the next download
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("op", choices=["check", "download", "apply"])
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--wait-pid", type=int, default=0)
    ap.add_argument("--relaunch", default="")
    a = ap.parse_args()
    game = a.game.resolve()
    if a.op == "check":
        return cmd_check(game)
    if a.op == "download":
        return cmd_download(game)
    return cmd_apply(game, a.wait_pid, a.relaunch)


if __name__ == "__main__":
    sys.exit(main())
