#!/usr/bin/env python3
"""Local sprite animation viewer: original vs. upscaled variants side by side.

Usage: sprite_viewer.py [--port N] [--no-browser]

Scans assets/sprites/*/*/meta.json and the upscaled variants in
assets/sprites_test/<variant>/ and assets/sprites_hd/<variant>/, writes
build/sprite_index.json and serves the project directory on 127.0.0.1 so
tools/sprite_viewer.html can load the PNGs. Nothing leaves this machine.

A variant directory may mirror the sprite tree (<variant>/SD1/S1_3/...) or
be flat (chaiNNer run on a single folder); flat ones are matched to the
sprite folder with exactly the same file names.
"""
import argparse
import functools
import http.server
import json
import socketserver
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
VARIANT_ROOTS = [ASSETS / "sprites_test", ASSETS / "sprites_hd"]


def build_index():
    folders = {}
    for meta in sorted((ASSETS / "sprites").glob("*/*/meta.json")):
        rel = meta.parent.relative_to(ASSETS / "sprites").as_posix()
        names = {p.name for p in meta.parent.glob("f*.png")}
        folders[rel] = {"meta": f"assets/sprites/{rel}/meta.json", "variants": {}, "_names": names}

    for vroot in VARIANT_ROOTS:
        if not vroot.is_dir():
            continue
        for vdir in sorted(p for p in vroot.iterdir() if p.is_dir()):
            label = f"{vdir.name} ({vroot.name})"
            flat = {p.name for p in vdir.glob("f*.png")}
            if flat:
                for rel, info in folders.items():
                    if flat == info["_names"]:
                        info["variants"][label] = vdir.relative_to(ROOT).as_posix()
            for rel, info in folders.items():
                nested = vdir / rel
                if nested.is_dir() and any(nested.glob("f*.png")):
                    info["variants"][label] = nested.relative_to(ROOT).as_posix()

    for info in folders.values():
        del info["_names"]
    index = {"folders": folders}
    out = ROOT / "build" / "sprite_index.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(index, indent=1))
    return index


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    index = build_index()
    with_variants = [k for k, v in index["folders"].items() if v["variants"]]
    print(f"{len(index['folders'])} sprite folders, {len(with_variants)} with upscaled variants: "
          + ", ".join(with_variants[:10]))

    handler = functools.partial(Handler, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/tools/sprite_viewer.html"
        print(f"viewer: {url}  (Ctrl+C to stop)")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
