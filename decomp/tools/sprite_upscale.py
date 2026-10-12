#!/usr/bin/env python3
"""Upscale sprite frames without chaiNNer (e.g. on a rented GPU).

Reproduces the chaiNNer chain "Hercules Sprites ... - IllustrationJaNai-DAT2":
  colour: Fill Alpha (extend texture) -> colour model (DAT2)
  alpha:  alpha channel -> alpha model (HDcube-Alpha) -> threshold to-zero 5 %
Output keeps the folder layout of SRC; frames already in DST are skipped.

    pip install spandrel chainner_ext opencv-python-headless
    python sprite_upscale.py SRC DST --color DAT2.pth --alpha HDcube-Alpha.pth

Afterwards run sprite_palettize.py on DST (variant "DAT2-schutz").
"""
import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from chainner_ext import fill_alpha_extend_color, fill_alpha_fragment_blur
from spandrel import ModelLoader


class Upscaler:
    def __init__(self, path: Path, device: torch.device, fp16: bool):
        self.desc = ModelLoader(device).load_from_file(str(path)).eval()
        self.fp16 = fp16 and self.desc.supports_half and device.type == "cuda"
        if self.fp16:
            self.desc.model.half()
        self.device = device

    @torch.inference_mode()
    def __call__(self, img: np.ndarray) -> np.ndarray:
        """img: HxWxC float32 RGB/gray in 0..1 -> upscaled, same channel count."""
        in_c = self.desc.input_channels
        gray = img.ndim == 2
        if gray and in_c == 3:
            x = np.repeat(img[..., None], 3, axis=2)
        elif not gray and in_c == 1:
            x = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)[..., None]
        else:
            x = img if not gray else img[..., None]
        t = torch.from_numpy(np.ascontiguousarray(x.transpose(2, 0, 1)))[None].to(self.device)
        t = t.half() if self.fp16 else t.float()
        y = self.desc(t).float().clamp_(0, 1)[0].cpu().numpy().transpose(1, 2, 0)
        if gray:
            # chaiNNer narrows BGR -> gray with cv2 (luma weights); our order is RGB.
            return cv2.cvtColor(y, cv2.COLOR_RGB2GRAY) if y.shape[2] == 3 else y[..., 0]
        return y if y.shape[2] == 3 else np.repeat(y, 3, axis=2)


def upscale_frame(rgba: np.ndarray, color: Upscaler, alpha_up: Upscaler) -> np.ndarray:
    img = rgba.astype(np.float32) / 255
    filled = fill_alpha_fragment_blur(img, threshold=0.05, iterations=6, fragment_count=5)
    filled = fill_alpha_extend_color(filled, threshold=0.05, iterations=100_000)
    rgb = color(np.ascontiguousarray(filled[..., :3]))
    a = alpha_up(np.ascontiguousarray(img[..., 3]))
    a = np.where(a > 0.05, a, 0)
    out = np.dstack((rgb, a))
    return (out * 255).round().clip(0, 255).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--color", type=Path, required=True, help="colour model (DAT2 .pth)")
    ap.add_argument("--alpha", type=Path, required=True, help="alpha model (HDcube-Alpha .pth)")
    ap.add_argument("--fp16", action="store_true", help="half precision on CUDA (faster)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N frames (for testing)")
    args = ap.parse_args()

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {dev}" + (f" ({torch.cuda.get_device_name()})" if dev.type == "cuda" else ""))
    color = Upscaler(args.color, dev, args.fp16)
    alpha_up = Upscaler(args.alpha, dev, args.fp16)

    todo = [p for p in sorted(args.src.rglob("f*.png"))
            if not (args.dst / p.relative_to(args.src)).exists()]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} frames to do")
    t0 = time.time()
    for i, src in enumerate(todo, 1):
        bgra = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
        if bgra.ndim == 2:
            bgra = cv2.cvtColor(bgra, cv2.COLOR_GRAY2BGRA)
        elif bgra.shape[2] == 3:
            bgra = cv2.cvtColor(bgra, cv2.COLOR_BGR2BGRA)
        out = upscale_frame(cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA), color, alpha_up)
        dst = args.dst / src.relative_to(args.src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp.png")
        cv2.imwrite(str(tmp), cv2.cvtColor(out, cv2.COLOR_RGBA2BGRA))
        tmp.rename(dst)
        if i % 200 == 0 or i == len(todo):
            el = time.time() - t0
            print(f"{i}/{len(todo)}  {el / 60:.1f} min, about {el / i * (len(todo) - i) / 60:.0f} min left",
                  flush=True)


if __name__ == "__main__":
    main()
