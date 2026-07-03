#!/usr/bin/env python3
"""Create a GPT Image edit mask from explicit rectangles.

Mask semantics for the image edit backend:
- Opaque white pixels are preserved.
- Transparent pixels are regenerated/edited.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def parse_rect(value: str) -> tuple[int, int, int, int]:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be x,y,w,h")
    try:
        x, y, w, h = [int(p) for p in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rect values must be integers") from exc
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError("rect width and height must be positive")
    return x, y, w, h


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an edit mask from one or more rectangles.")
    parser.add_argument("--image", required=True, help="Source image path used for dimensions.")
    parser.add_argument("--output", required=True, help="Output PNG mask path.")
    parser.add_argument("--rect", action="append", type=parse_rect, required=True, help="Editable rectangle: x,y,w,h. Repeatable.")
    parser.add_argument("--pad-to", help="Optional padded canvas size WxH, e.g. 1280x800.")
    return parser.parse_args()


def parse_size(value: str | None, fallback: tuple[int, int]) -> tuple[int, int]:
    if not value:
        return fallback
    if "x" not in value.lower():
        raise SystemExit("--pad-to must be WxH")
    w_str, h_str = value.lower().split("x", 1)
    w, h = int(w_str), int(h_str)
    if w < fallback[0] or h < fallback[1]:
        raise SystemExit("--pad-to must be at least the source image size")
    return w, h


def main() -> int:
    args = parse_args()
    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"Source image not found: {image_path}")

    with Image.open(image_path) as source:
        width, height = parse_size(args.pad_to, source.size)

    mask = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(mask, "RGBA")
    for x, y, w, h in args.rect:
        draw.rectangle([x, y, x + w, y + h], fill=(255, 255, 255, 0))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    mask.save(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
