#!/usr/bin/env python3
"""Deterministic helpers for GPT Image local edits.

The image backend only accepts output sizes that are 16px multiples, have
edges <= 3840px, an aspect ratio <= 3:1, and 655,360-8,294,400 pixels.  For a
masked edit the source image, mask, and output must share one canvas, so the
source is fitted into a valid work canvas:

1. scale proportionally only when the source is too small or too large;
2. pad the bottom/right edges (repeating edge pixels) up to 16px multiples and,
   when needed, up to a 3:1 aspect ratio.

After generation the work result is cropped back to the scaled content, scaled
back to the source size, and protected mask areas are hard-composited from the
original pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image


MULTIPLE = 16
MAX_EDGE = 3840
MAX_RATIO = 3
MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
MASK_THRESHOLD = 128


@dataclass(frozen=True)
class EditGeometry:
    """How a source image maps onto the API work canvas."""

    original_size: tuple[int, int]
    content_size: tuple[int, int]  # source size after scaling, before padding
    work_size: tuple[int, int]  # padded canvas sent to the API

    @property
    def scaled(self) -> bool:
        return self.content_size != self.original_size

    @property
    def padded(self) -> bool:
        return self.work_size != self.content_size

    def describe(self) -> str:
        ow, oh = self.original_size
        cw, ch = self.content_size
        ww, wh = self.work_size
        parts = [f"original {ow}x{oh}"]
        if self.scaled:
            parts.append(f"scaled to {cw}x{ch} ({cw / ow:.3f}x)")
        parts.append(f"work {ww}x{wh}")
        return "; ".join(parts)


def ceil_to_multiple(value: int, multiple: int = MULTIPLE) -> int:
    if value <= 0:
        raise ValueError("image dimensions must be positive")
    return ((value + multiple - 1) // multiple) * multiple


def is_valid_size(size: tuple[int, int]) -> bool:
    width, height = size
    return (
        min(width, height) > 0
        and width % MULTIPLE == 0
        and height % MULTIPLE == 0
        and max(width, height) <= MAX_EDGE
        and max(width, height) <= MAX_RATIO * min(width, height)
        and MIN_PIXELS <= width * height <= MAX_PIXELS
    )


def _padded_canvas(content: tuple[int, int]) -> tuple[int, int]:
    """Smallest 16px-aligned canvas >= content whose aspect ratio is <= 3:1."""
    width = ceil_to_multiple(content[0])
    height = ceil_to_multiple(content[1])
    if width > MAX_RATIO * height:
        height = ceil_to_multiple(math.ceil(width / MAX_RATIO))
    elif height > MAX_RATIO * width:
        width = ceil_to_multiple(math.ceil(height / MAX_RATIO))
    return width, height


def plan_geometry(original_size: tuple[int, int]) -> EditGeometry:
    """Choose the gentlest scale (1.0 when possible) that yields a valid canvas."""
    width, height = original_size
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")

    def canvas_for(scale: float) -> tuple[tuple[int, int], tuple[int, int]]:
        content = (max(1, round(width * scale)), max(1, round(height * scale)))
        return content, _padded_canvas(content)

    content, work = canvas_for(1.0)
    if is_valid_size(work):
        return EditGeometry(original_size, content, work)

    # Too small: grow until the padded canvas reaches the pixel floor.
    # Too large: shrink until edge and pixel ceilings hold.
    if work[0] * work[1] < MIN_PIXELS:
        scale = math.sqrt(MIN_PIXELS / (work[0] * work[1]))
        step = 1.01
    else:
        scale = min(
            MAX_EDGE / max(work),
            math.sqrt(MAX_PIXELS / (work[0] * work[1])),
        )
        step = 0.99
    for _ in range(400):
        content, work = canvas_for(scale)
        if is_valid_size(work):
            return EditGeometry(original_size, content, work)
        scale *= step
    raise ValueError(f"could not fit {width}x{height} into the image API size limits")


def _normal_image_mode(image: Image.Image) -> Image.Image:
    if image.mode in {"RGB", "RGBA", "L", "LA"}:
        return image.copy()
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def pad_image_edge(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    """Pad bottom/right by repeating edge pixels; source pixels are untouched."""
    image = _normal_image_mode(image)
    source_width, source_height = image.size
    target_width, target_height = target_size
    if target_width < source_width or target_height < source_height:
        raise ValueError(f"target size {target_size} is smaller than source size {image.size}")
    if image.size == target_size:
        return image

    canvas = Image.new(image.mode, target_size)
    canvas.paste(image, (0, 0))
    extra_width = target_width - source_width
    extra_height = target_height - source_height
    if extra_width:
        edge = image.crop((source_width - 1, 0, source_width, source_height))
        canvas.paste(edge.resize((extra_width, source_height), Image.Resampling.NEAREST), (source_width, 0))
    if extra_height:
        edge = image.crop((0, source_height - 1, source_width, source_height))
        canvas.paste(edge.resize((source_width, extra_height), Image.Resampling.NEAREST), (0, source_height))
    if extra_width and extra_height:
        corner = image.crop((source_width - 1, source_height - 1, source_width, source_height))
        canvas.paste(corner.resize((extra_width, extra_height), Image.Resampling.NEAREST), (source_width, source_height))
    return canvas


def make_work_image(image: Image.Image, geometry: EditGeometry) -> Image.Image:
    """Scale (only if required) and pad the source onto the work canvas."""
    image = _normal_image_mode(image)
    if image.size != geometry.original_size:
        raise ValueError(f"image size {image.size} does not match planned {geometry.original_size}")
    if geometry.scaled:
        image = image.resize(geometry.content_size, Image.Resampling.LANCZOS)
    return pad_image_edge(image, geometry.work_size)


def mask_preserve_channel(mask: Image.Image, threshold: int = MASK_THRESHOLD) -> Image.Image:
    """Return a hard L channel: 255 = preserve, 0 = editable.

    Masks with alpha follow the GPT Image convention (opaque = preserve).  Masks
    without alpha use luminance (white = preserve).
    """
    if "A" in mask.getbands() or "transparency" in mask.info:
        channel = mask.convert("RGBA").getchannel("A")
    else:
        channel = mask.convert("L")
    return channel.point(lambda value: 255 if value >= threshold else 0, mode="L")


def make_work_mask(mask: Image.Image, geometry: EditGeometry) -> Image.Image:
    """Map a source-sized mask onto the work canvas; padding is always preserved."""
    if mask.size != geometry.original_size:
        raise ValueError(
            f"mask size {mask.size} must match the source image size {geometry.original_size}"
        )
    preserve = mask_preserve_channel(mask)
    if geometry.scaled:
        preserve = preserve.resize(geometry.content_size, Image.Resampling.NEAREST)
    canvas = Image.new("L", geometry.work_size, 255)
    canvas.paste(preserve, (0, 0))
    white = Image.new("L", geometry.work_size, 255)
    return Image.merge("RGBA", (white, white, white, canvas))


def restore_generated_result(generated: Image.Image, geometry: EditGeometry) -> Image.Image:
    """Map a generated work image back to the exact source dimensions."""
    result = _normal_image_mode(generated)
    if result.size != geometry.work_size:
        result = result.resize(geometry.work_size, Image.Resampling.LANCZOS)
    result = result.crop((0, 0, geometry.content_size[0], geometry.content_size[1]))
    if geometry.scaled:
        result = result.resize(geometry.original_size, Image.Resampling.LANCZOS)
    return result


def composite_preserve(original: Image.Image, generated: Image.Image, mask: Image.Image) -> Image.Image:
    """Keep preserved mask areas from ``original`` and editable areas from ``generated``."""
    if not (original.size == generated.size == mask.size):
        raise ValueError(
            f"composite sizes must match: original={original.size}, generated={generated.size}, mask={mask.size}"
        )
    output_mode = "RGBA" if "A" in original.getbands() else "RGB"
    return Image.composite(
        original.convert(output_mode),
        generated.convert(output_mode),
        mask_preserve_channel(mask),
    )


def restore_and_composite(
    original: Image.Image,
    generated: Image.Image,
    mask: Image.Image | None,
    geometry: EditGeometry,
) -> Image.Image:
    restored = restore_generated_result(generated, geometry)
    if mask is None:
        return restored
    return composite_preserve(original, restored, mask)


def rect_to_box(rect: tuple[int, int, int, int], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Convert x,y,w,h to a clipped Pillow box."""
    x, y, width, height = rect
    image_width, image_height = image_size
    left = max(0, min(image_width, x))
    top = max(0, min(image_height, y))
    right = max(left, min(image_width, x + width))
    bottom = max(top, min(image_height, y + height))
    return left, top, right, bottom
