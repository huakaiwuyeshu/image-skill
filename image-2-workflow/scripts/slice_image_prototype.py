#!/usr/bin/env python3
"""Slice a large prototype canvas image into editable PNG assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Slice a prototype canvas image into PNG assets.")
    parser.add_argument("--image", required=True, help="Source PNG/JPEG prototype canvas.")
    parser.add_argument("--output-dir", required=True, help="Directory for slices and manifest.")
    parser.add_argument(
        "--mode",
        choices=["auto", "phone", "module", "full"],
        default="auto",
        help="Slice strategy. auto prefers phone/app screens, then modules, then full image.",
    )
    parser.add_argument("--threshold", type=int, default=248, help="Near-white background threshold.")
    parser.add_argument("--kernel", type=int, default=21, help="Morphology kernel size.")
    parser.add_argument("--pad", type=int, default=6, help="Padding around detected boxes.")
    parser.add_argument("--max-slices", type=int, default=200, help="Maximum slices to save.")
    parser.add_argument("--min-width", type=int, default=120, help="Minimum module width.")
    parser.add_argument("--min-height", type=int, default=120, help="Minimum module height.")
    parser.add_argument("--prefix", default="slice", help="Output filename prefix.")
    parser.add_argument("--manifest", help="Optional manifest path. Defaults to output-dir/slices.json.")
    return parser.parse_args()


def clamp_box(box: list[int], image_size: tuple[int, int], pad: int) -> list[int]:
    x, y, w, h = box
    width, height = image_size
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(width, x + w + pad)
    y2 = min(height, y + h + pad)
    return [x1, y1, x2 - x1, y2 - y1]


def iou(box_a: list[int], box_b: list[int]) -> float:
    ax, ay, aw, ah = box_a[:4]
    bx, by, bw, bh = box_b[:4]
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    return inter / float(aw * ah + bw * bh - inter)


def connected_boxes(image: Image.Image, threshold: int, kernel_size: int) -> list[list[int]]:
    arr = np.array(image.convert("RGB"))
    mask = np.any(arr < threshold, axis=2).astype("uint8") * 255
    kernel_size = max(3, int(kernel_size))
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    merged = cv2.dilate(merged, kernel, iterations=1)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(merged, 8)
    boxes: list[list[int]] = []
    for index in range(1, count):
        x, y, w, h, area = [int(value) for value in stats[index]]
        if w * h < 4000:
            continue
        boxes.append([x, y, w, h, area])
    return sorted(boxes, key=lambda item: (item[1], item[0]))


def looks_like_sticky_note(image: Image.Image, box: list[int]) -> bool:
    x, y, w, h = box
    crop = np.array(image.crop((x, y, x + w, y + h)).convert("RGB"))
    if crop.size == 0:
        return False
    rgb = crop.reshape(-1, 3).astype("int16")
    red, green, blue = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    yellow = (red > 190) & (green > 150) & (blue < 90) & ((red - blue) > 100)
    non_white = np.any(rgb < 248, axis=1)
    yellow_ratio = float(yellow.mean())
    non_white_ratio = float(non_white.mean())
    return yellow_ratio > 0.35 and non_white_ratio > 0.55


def detect_phone_screens(image: Image.Image, raw_boxes: list[list[int]]) -> list[list[int | str]]:
    obvious_widths = [
        w
        for _x, _y, w, h, _area in raw_boxes
        if 300 <= w <= 520 and 560 <= h <= 1400 and 0.25 <= (w / h) <= 0.75
    ]
    standard_width = int(np.median(obvious_widths)) if obvious_widths else 390
    candidates: list[list[int | str]] = []

    for x, y, w, h, _area in raw_boxes:
        ratio = w / h
        kind: str | None = None
        detected_w = w
        if 300 <= w <= 520 and 560 <= h <= 1400 and 0.25 <= ratio <= 0.75:
            kind = "phone"
            if w > standard_width + 40:
                detected_w = standard_width
                kind = "phone-trim-right"
        elif 520 < w <= 760 and 560 <= h <= 1400 and 0.52 <= ratio <= 0.92:
            # A phone screen may be fused with a nearby sticky note or annotation.
            detected_w = standard_width
            kind = "phone-split-left"
        if kind and looks_like_sticky_note(image, [x, y, detected_w, h]):
            kind = None
        if kind:
            candidates.append([x, y, detected_w, h, kind])

    clean: list[list[int | str]] = []
    for candidate in candidates:
        if all(iou(candidate[:4], saved[:4]) < 0.25 for saved in clean):
            clean.append(candidate)
    return clean


def detect_modules(raw_boxes: list[list[int]], min_width: int, min_height: int) -> list[list[int | str]]:
    candidates: list[list[int | str]] = []
    for x, y, w, h, _area in raw_boxes:
        if w < min_width or h < min_height:
            continue
        if w * h < min_width * min_height:
            continue
        candidates.append([x, y, w, h, "module"])

    clean: list[list[int | str]] = []
    for candidate in candidates:
        duplicate = False
        for saved in clean:
            overlap = iou(candidate[:4], saved[:4])
            contains = (
                candidate[0] >= saved[0]
                and candidate[1] >= saved[1]
                and candidate[0] + candidate[2] <= saved[0] + saved[2]
                and candidate[1] + candidate[3] <= saved[1] + saved[3]
            )
            if overlap > 0.8 or contains:
                duplicate = True
                break
        if not duplicate:
            clean.append(candidate)
    return clean


def draw_overview(source: Image.Image, slices: list[dict], overview_path: Path) -> None:
    overview = source.copy()
    draw = ImageDraw.Draw(overview)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except OSError:
        font = None
    for item in slices:
        box = item["box"]
        x, y, w, h = box["x"], box["y"], box["width"], box["height"]
        color = (0, 120, 255) if "phone" in item["kind"] else (255, 128, 0)
        draw.rectangle([x, y, x + w, y + h], outline=color, width=6)
        draw.rectangle([x, y, x + 64, y + 42], fill=color)
        draw.text((x + 8, y + 4), str(item["index"]), fill=(255, 255, 255), font=font)
    overview.thumbnail((1600, 2400))
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    overview.save(overview_path)


def save_slices(source: Image.Image, boxes: list[list[int | str]], args: argparse.Namespace) -> tuple[list[dict], Path]:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    image_size = source.size
    slices: list[dict] = []
    for index, candidate in enumerate(boxes[: args.max_slices], start=1):
        x, y, w, h = [int(value) for value in candidate[:4]]
        kind = str(candidate[4])
        crop_box = clamp_box([x, y, w, h], image_size, args.pad)
        x1, y1, cw, ch = crop_box
        output_path = output_dir / f"{args.prefix}-{index:02d}.png"
        source.crop((x1, y1, x1 + cw, y1 + ch)).save(output_path)
        slices.append(
            {
                "index": index,
                "path": str(output_path),
                "kind": kind,
                "box": {"x": x1, "y": y1, "width": cw, "height": ch},
                "detected_box": {"x": x, "y": y, "width": w, "height": h},
            }
        )
    overview_path = output_dir / f"{args.prefix}-overview.png"
    draw_overview(source, slices, overview_path)
    return slices, overview_path


def run() -> int:
    args = parse_args()
    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"Source image not found: {image_path}")

    source = Image.open(image_path).convert("RGB")
    raw_boxes = connected_boxes(source, args.threshold, args.kernel)
    selected: list[list[int | str]] = []
    selected_mode = args.mode

    if args.mode in {"auto", "phone"}:
        selected = detect_phone_screens(source, raw_boxes)
        selected_mode = "phone"
    if not selected and args.mode in {"auto", "module"}:
        selected = detect_modules(raw_boxes, args.min_width, args.min_height)
        selected_mode = "module"
    if not selected or args.mode == "full":
        width, height = source.size
        selected = [[0, 0, width, height, "full"]]
        selected_mode = "full"

    slices, overview_path = save_slices(source, selected, args)
    manifest_path = Path(args.manifest).resolve() if args.manifest else Path(args.output_dir).resolve() / "slices.json"
    manifest = {
        "source": str(image_path),
        "source_size": {"width": source.size[0], "height": source.size[1]},
        "mode": selected_mode,
        "count": len(slices),
        "overview": str(overview_path),
        "slices": slices,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(manifest_path)
    print(overview_path)
    for item in slices:
        print(item["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
