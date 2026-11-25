#!/usr/bin/env python3
"""Create deterministic local-edit comparisons and report protected-pixel drift."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

try:
    from .image_edit_utils import mask_preserve_channel, rect_to_box
except ImportError:  # Direct execution: python3 scripts/verify_edit.py
    from image_edit_utils import mask_preserve_channel, rect_to_box


def parse_rect(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be x,y,w,h")
    try:
        x, y, width, height = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rect values must be integers") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("rect width and height must be positive")
    return x, y, width, height


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a local image edit without calling an image API.")
    parser.add_argument("--original", required=True, help="Original image path.")
    parser.add_argument("--edited", required=True, help="Edited image path.")
    region_group = parser.add_mutually_exclusive_group(required=True)
    region_group.add_argument("--mask", help="White-opaque preserve / transparent-edit mask path.")
    region_group.add_argument("--rect", action="append", type=parse_rect, help="Editable rectangle x,y,w,h. Repeatable.")
    parser.add_argument("--out-dir", required=True, help="Directory for comparison images.")
    return parser.parse_args()


def connected_components(editable: bytes, size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    """Find 8-connected editable regions using only the standard library."""
    width, height = size
    visited = bytearray(len(editable))
    boxes: list[tuple[int, int, int, int]] = []
    for start, value in enumerate(editable):
        if not value or visited[start]:
            continue
        visited[start] = 1
        stack = [start]
        min_x = max_x = start % width
        min_y = max_y = start // width
        while stack:
            index = stack.pop()
            x = index % width
            y = index // width
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for dy in (-1, 0, 1):
                next_y = y + dy
                if next_y < 0 or next_y >= height:
                    continue
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    next_x = x + dx
                    if next_x < 0 or next_x >= width:
                        continue
                    next_index = next_y * width + next_x
                    if editable[next_index] and not visited[next_index]:
                        visited[next_index] = 1
                        stack.append(next_index)
        boxes.append((min_x, min_y, max_x + 1, max_y + 1))
    return sorted(boxes, key=lambda box: (box[1], box[0], box[3], box[2]))


def editable_data_from_mask(mask: Image.Image, image_size: tuple[int, int]) -> tuple[bytes, list[tuple[int, int, int, int]]]:
    if mask.size != image_size:
        raise SystemExit(f"Mask size {mask.size[0]}x{mask.size[1]} does not match image size {image_size[0]}x{image_size[1]}")
    preserve = mask_preserve_channel(mask)
    editable = bytes(1 if pixel == 0 else 0 for pixel in preserve.tobytes())
    boxes = connected_components(editable, image_size)
    if not boxes:
        raise SystemExit("Mask contains no transparent/editable region.")
    return editable, boxes


def editable_data_from_rects(rects: list[tuple[int, int, int, int]], image_size: tuple[int, int]) -> tuple[bytes, list[tuple[int, int, int, int]]]:
    width, height = image_size
    editable = bytearray(width * height)
    boxes: list[tuple[int, int, int, int]] = []
    for rect in rects:
        box = rect_to_box(rect, image_size)
        if box[0] >= box[2] or box[1] >= box[3]:
            continue
        boxes.append(box)
        left, top, right, bottom = box
        for y in range(top, bottom):
            row_start = y * width
            editable[row_start + left : row_start + right] = b"\x01" * (right - left)
    if not boxes:
        raise SystemExit("No --rect overlaps the image.")
    return bytes(editable), boxes


def crop_with_margin(image: Image.Image, box: tuple[int, int, int, int], margin: int) -> Image.Image:
    left, top, right, bottom = box
    width, height = image.size
    requested_left = left - margin
    requested_top = top - margin
    requested_right = right + margin
    requested_bottom = bottom + margin
    crop_left = max(0, requested_left)
    crop_top = max(0, requested_top)
    crop_right = min(width, requested_right)
    crop_bottom = min(height, requested_bottom)
    crop = image.crop((crop_left, crop_top, crop_right, crop_bottom))

    target_size = (requested_right - requested_left, requested_bottom - requested_top)
    canvas = Image.new(image.mode, target_size)
    offset_x = crop_left - requested_left
    offset_y = crop_top - requested_top
    canvas.paste(crop, (offset_x, offset_y))

    if offset_x:
        left_edge = crop.crop((0, 0, 1, crop.height)).resize((offset_x, crop.height), Image.Resampling.NEAREST)
        canvas.paste(left_edge, (0, offset_y))
    right_gap = target_size[0] - offset_x - crop.width
    if right_gap:
        right_edge = crop.crop((crop.width - 1, 0, crop.width, crop.height)).resize((right_gap, crop.height), Image.Resampling.NEAREST)
        canvas.paste(right_edge, (offset_x + crop.width, offset_y))
    if offset_y:
        top_row = canvas.crop((0, offset_y, target_size[0], offset_y + 1)).resize((target_size[0], offset_y), Image.Resampling.NEAREST)
        canvas.paste(top_row, (0, 0))
    bottom_gap = target_size[1] - offset_y - crop.height
    if bottom_gap:
        bottom_row = canvas.crop((0, offset_y + crop.height - 1, target_size[0], offset_y + crop.height)).resize((target_size[0], bottom_gap), Image.Resampling.NEAREST)
        canvas.paste(bottom_row, (0, offset_y + crop.height))
    return canvas


def make_comparison(before: Image.Image, after: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    region_width = max(1, box[2] - box[0])
    region_height = max(1, box[3] - box[1])
    margin = max(8, min(region_width, region_height) // 5)
    before_crop = crop_with_margin(before, box, margin)
    after_crop = crop_with_margin(after, box, margin)
    if before_crop.size != after_crop.size:
        raise SystemExit("Original and edited crops do not have matching sizes.")

    header_height = max(24, min(48, before_crop.height // 8))
    canvas = Image.new("RGB", (before_crop.width * 2, before_crop.height + header_height), "white")
    canvas.paste(before_crop, (0, header_height))
    canvas.paste(after_crop, (before_crop.width, header_height))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((8, 6), "BEFORE", fill="black", font=font)
    draw.text((before_crop.width + 8, 6), "AFTER", fill="black", font=font)
    draw.line((before_crop.width, header_height, before_crop.width, canvas.height), fill=(190, 190, 190), width=1)
    return canvas.resize((canvas.width * 2, canvas.height * 2), Image.Resampling.LANCZOS)


def count_outside_differences(original: Image.Image, edited: Image.Image, editable: bytes) -> int:
    difference = ImageChops.difference(original, edited).convert("RGB")
    outside = 0
    for index, pixel in enumerate(difference.getdata()):
        if pixel != (0, 0, 0) and not editable[index]:
            outside += 1
    return outside


def main() -> int:
    args = parse_args()
    original_path = Path(args.original).resolve()
    edited_path = Path(args.edited).resolve()
    if not original_path.is_file():
        raise SystemExit(f"Original image not found: {original_path}")
    if not edited_path.is_file():
        raise SystemExit(f"Edited image not found: {edited_path}")

    with Image.open(original_path) as original_file, Image.open(edited_path) as edited_file:
        original = original_file.convert("RGB")
        edited = edited_file.convert("RGB")
    if original.size != edited.size:
        raise SystemExit(f"Original and edited sizes differ: {original.size} vs {edited.size}")

    if args.mask:
        mask_path = Path(args.mask).resolve()
        if not mask_path.is_file():
            raise SystemExit(f"Mask not found: {mask_path}")
        with Image.open(mask_path) as mask_file:
            editable, boxes = editable_data_from_mask(mask_file, original.size)
    else:
        editable, boxes = editable_data_from_rects(args.rect, original.size)

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    comparison_paths: list[Path] = []
    for index, box in enumerate(boxes, start=1):
        comparison_path = out_dir / f"region-{index:02d}-before-after.png"
        make_comparison(original, edited, box).save(comparison_path, format="PNG")
        comparison_paths.append(comparison_path)

    outside_diff = count_outside_differences(original, edited, editable)
    paths = "; ".join(f"region_{index:02d}={path}" for index, path in enumerate(comparison_paths, start=1))
    print(f"outside_diff_pixels={outside_diff}; {paths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
