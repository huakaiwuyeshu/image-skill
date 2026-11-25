#!/usr/bin/env python3
"""Stable wrapper around the installed gpt-image CLI backend."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

try:
    from .image_edit_utils import EditGeometry, make_work_image, make_work_mask, plan_geometry, restore_and_composite
except ImportError:  # Direct execution: python3 scripts/run_gpt_image.py
    from image_edit_utils import EditGeometry, make_work_image, make_work_mask, plan_geometry, restore_and_composite


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or edit images with gpt-image-2.5-sunburst. Masked edits are fitted to the API size limits "
            "automatically, restored to the source size, and protected areas are composited from the original."
        )
    )
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("-p", "--prompt", help="Final optimized prompt.")
    prompt_group.add_argument("--prompt-file", help="Explicit path to the final optimized prompt file.")
    parser.add_argument("--save-prompt", help="Save the final optimized prompt to this explicit path.")
    parser.add_argument("-f", "--output", "--file", dest="output", required=True, help="Output image path.")
    parser.add_argument("-i", "--image", action="append", default=[], help="Reference image path. Repeatable.")
    parser.add_argument("-m", "--mask", help="Mask image path for inpainting.")
    parser.add_argument(
        "--no-composite",
        action="store_true",
        help="Masked edits only: skip hard compositing of protected areas; the result is still restored to the source size.",
    )
    parser.add_argument("--model", default="gpt-image-2.5-sunburst", help="Image model. Defaults to gpt-image-2.5-sunburst.")
    parser.add_argument(
        "--size",
        default="landscape",
        help="Size shortcut or literal size. Ignored for masked edits, which always keep the source size.",
    )
    parser.add_argument("--quality", default="high", choices=["auto", "low", "medium", "high"])
    parser.add_argument("--format", default="png", choices=["png", "jpeg", "webp"])
    parser.add_argument("-n", "--n", type=int, default=1)
    parser.add_argument("--background", choices=["auto", "opaque"])
    parser.add_argument(
        "--keep-alpha",
        action="store_true",
        help="Keep transparent pixels in the output. By default transparent areas are flattened onto white.",
    )
    parser.add_argument("--moderation", choices=["auto", "low"])
    parser.add_argument("--compression", type=int)
    parser.add_argument("--user")
    return parser.parse_args()


def resolve_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.is_file():
            raise SystemExit(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8").strip()
    return str(args.prompt).strip()


def save_prompt_if_requested(prompt: str, args: argparse.Namespace) -> None:
    if not args.save_prompt:
        return
    prompt_path = Path(args.save_prompt).resolve()
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt.rstrip() + "\n", encoding="utf-8")


def read_custom_provider(path: Path) -> tuple[str, str]:
    """Read Codex's custom provider. Returns (base_url, bearer_token)."""
    if not path.is_file():
        return "", ""
    section = ""
    base = ""
    token = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "model_providers.custom" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip() == "base_url":
            base = value
        elif key.strip() == "experimental_bearer_token":
            token = value
    return base, token


def load_dotenv_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key in {"OPENAI_API_KEY", "OPENAI_BASE_URL"} and not os.environ.get(key):
            os.environ[key] = value


def sanitize_no_proxy() -> None:
    """Drop NO_PROXY entries httpx2 cannot parse, in this process only.

    httpx2 raises InvalidURL ("Invalid port: ':1]'") on bracketed IPv6 entries
    such as [::1]. The system proxy (http_proxy/https_proxy) is left untouched;
    subprocesses inherit the cleaned value through os.environ.
    """
    for name in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(name)
        if value is None:
            continue
        kept = [item.strip() for item in value.split(",") if item.strip() and "[" not in item and "]" not in item]
        os.environ[name] = ",".join(kept)


def load_provider_env() -> None:
    """Use ~/.codex/config.toml as the source of truth for the image gateway.

    Native Codex reads [model_providers.custom]. Inherited OPENAI_* values (for
    example in a subagent) are always overridden when config.toml has both base
    and token. ~/.codex/.env is only a fallback. The local quota server on 4319
    is never used.
    """
    sanitize_no_proxy()
    base, token = read_custom_provider(Path.home() / ".codex" / "config.toml")
    if base and token:
        os.environ["OPENAI_BASE_URL"] = base
        os.environ["OPENAI_API_KEY"] = token
    else:
        env_path = Path.home() / ".codex" / ".env"
        if env_path.is_file():
            load_dotenv_file(env_path)
    current_base = os.environ.get("OPENAI_BASE_URL", "")
    if "127.0.0.1:4319" in current_base or "localhost:4319" in current_base:
        raise SystemExit("OPENAI_BASE_URL points at the local 4319 gateway, which has no image routes. Fix ~/.codex/config.toml [model_providers.custom].")


def validate(args: argparse.Namespace) -> None:
    load_provider_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Expected it in ~/.codex/config.toml [model_providers.custom].")
    if not os.environ.get("OPENAI_BASE_URL"):
        raise SystemExit("OPENAI_BASE_URL is not set. Expected it in ~/.codex/config.toml [model_providers.custom].")
    for image in args.image:
        if not Path(image).is_file():
            raise SystemExit(f"Reference image not found: {image}")
    if args.mask and not Path(args.mask).is_file():
        raise SystemExit(f"Mask image not found: {args.mask}")
    Path(args.output).resolve().parent.mkdir(parents=True, exist_ok=True)


def build_cli_args(
    args: argparse.Namespace,
    prompt: str,
    *,
    output_path: str | None = None,
    image_paths: list[str] | None = None,
    mask_path: str | None = None,
    size_override: str | None = None,
) -> list[str]:
    cli_args = [
        "-p",
        prompt,
        "-f",
        output_path or args.output,
        "--model",
        args.model,
        "--size",
        size_override or args.size,
        "--quality",
        args.quality,
        "--format",
        args.format,
        "-n",
        str(args.n),
    ]
    for image in image_paths if image_paths is not None else args.image:
        cli_args.extend(["-i", image])
    if mask_path or args.mask:
        cli_args.extend(["-m", mask_path or args.mask])
    if args.background:
        cli_args.extend(["--background", args.background])
    if args.moderation:
        cli_args.extend(["--moderation", args.moderation])
    if args.compression is not None:
        cli_args.extend(["--compression", str(args.compression)])
    if args.user:
        cli_args.extend(["--user", args.user])
    return cli_args


@dataclass
class EditContext:
    """Temporary masked-edit inputs and metadata needed after the API call."""

    original_path: Path
    original_mask_path: Path
    image_paths: list[str]
    mask_path: str
    geometry: EditGeometry


def prepare_edit_context(args: argparse.Namespace, temp_dir: Path) -> EditContext:
    """Fit the primary image and mask onto a valid work canvas without touching the source files."""
    original_path = Path(args.image[0]).resolve()
    try:
        with Image.open(original_path) as source:
            geometry = plan_geometry(source.size)
            work_image_path = temp_dir / "image-0.png"
            make_work_image(source, geometry).save(work_image_path, format="PNG")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not prepare reference image {original_path}: {exc}") from exc

    original_mask_path = Path(args.mask).resolve()
    try:
        with Image.open(original_mask_path) as mask:
            work_mask_path = temp_dir / "mask.png"
            make_work_mask(mask, geometry).save(work_mask_path, format="PNG")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not prepare edit mask {original_mask_path}: {exc}") from exc

    # Extra reference images keep their own size; only the primary image shares the mask canvas.
    image_paths = [str(work_image_path)] + [str(Path(path).resolve()) for path in args.image[1:]]
    return EditContext(
        original_path=original_path,
        original_mask_path=original_mask_path,
        image_paths=image_paths,
        mask_path=str(work_mask_path),
        geometry=geometry,
    )


def output_paths(output: Path, count: int) -> list[Path]:
    """Return the same output naming convention as the installed CLI."""
    if count == 1:
        return [output]
    suffix = output.suffix
    stem = output.with_suffix("")
    return [stem.parent / f"{stem.name}_{index}{suffix}" for index in range(count)]


def save_processed_image(image: Image.Image, output: Path, args: argparse.Namespace) -> None:
    """Write a post-processed result using the wrapper's requested output format."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output_format = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[args.format]
    if output_format == "JPEG":
        image = image.convert("RGB")
    save_kwargs: dict[str, int] = {}
    if args.compression is not None and output_format in {"JPEG", "WEBP"}:
        save_kwargs["quality"] = max(1, min(100, 100 - args.compression))
    image.save(output, format=output_format, **save_kwargs)


def process_edit_outputs(
    context: EditContext,
    generated_paths: list[Path],
    final_paths: list[Path],
    args: argparse.Namespace,
) -> None:
    """Restore generated work images to the source size and hard-composite protected areas."""
    with Image.open(context.original_path) as source:
        original = source.copy()
    mask = None
    if not args.no_composite:
        with Image.open(context.original_mask_path) as source_mask:
            mask = source_mask.copy()

    for generated_path, final_path in zip(generated_paths, final_paths):
        if not generated_path.is_file():
            raise SystemExit(f"Image backend returned success but output was not found: {generated_path}")
        with Image.open(generated_path) as generated_file:
            generated = generated_file.copy()
        if generated.size != context.geometry.work_size:
            print(
                f"[edit] warning: backend returned {generated.size[0]}x{generated.size[1]}, "
                f"expected {context.geometry.work_size[0]}x{context.geometry.work_size[1]}; resizing before restore",
                file=sys.stderr,
            )
        result = restore_and_composite(original, generated, mask, context.geometry)
        save_processed_image(result, final_path, args)


def run_installed_module(cli_args: list[str]) -> int | None:
    try:
        from gpt_image_cli.cli import main
    except ModuleNotFoundError:
        return None

    old_argv = sys.argv
    try:
        sys.argv = ["gpt-image", *cli_args]
        result = main()
        return int(result or 0)
    finally:
        sys.argv = old_argv


def run_executable(cli_args: list[str]) -> int:
    executable = shutil.which("gpt-image")
    if not executable:
        fallback = Path(os.environ.get("APPDATA", "")) / "Python" / "Python312" / "Scripts" / "gpt-image.exe"
        if fallback.is_file():
            executable = str(fallback)
    if not executable:
        raise SystemExit("Could not find gpt-image CLI backend.")
    completed = subprocess.run([executable, *cli_args], check=False)
    return completed.returncode


def flatten_transparency(path: Path, args: argparse.Namespace) -> None:
    """Flatten transparent pixels onto white unless --keep-alpha is set.

    The backend sometimes returns diagrams with a transparent background. Viewers that
    render transparency as white hide the problem, but dark themes show garbled text.
    """
    if args.keep_alpha or not path.is_file():
        return
    with Image.open(path) as image:
        if "A" not in image.getbands() and "transparency" not in image.info:
            return
        rgba = image.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] == 255:
        return
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.alpha_composite(rgba)
    save_processed_image(background.convert("RGB"), path, args)
    print(f"[output] flattened transparent background onto white: {path}", file=sys.stderr)


def run_backend(cli_args: list[str]) -> int:
    exit_code = run_installed_module(cli_args)
    if exit_code is None:
        exit_code = run_executable(cli_args)
    return exit_code


def main() -> int:
    args = parse_args()
    validate(args)
    if args.mask and not args.image:
        raise SystemExit("--mask requires --image (the image the mask belongs to).")
    prompt = resolve_prompt(args)
    if not prompt:
        raise SystemExit("Prompt is empty.")
    save_prompt_if_requested(prompt, args)

    # Text-to-image and maskless reference edits: pass --size through unchanged.
    if not args.mask:
        exit_code = run_backend(build_cli_args(args, prompt))
        if exit_code == 0:
            for path in output_paths(Path(args.output), args.n):
                if path.is_file():
                    flatten_transparency(path, args)
                    print(path)
        return exit_code

    # Masked (local) edit: fit to API limits, then restore and composite.
    final_output = Path(args.output).resolve()
    final_paths = output_paths(final_output, args.n)
    display_paths = output_paths(Path(args.output), args.n)
    composite_label = "no (--no-composite)" if args.no_composite else "yes"
    with tempfile.TemporaryDirectory(prefix="image-edit-") as temp_name:
        temp_dir = Path(temp_name)
        context = prepare_edit_context(args, temp_dir)
        geometry = context.geometry
        print(f"[edit] {geometry.describe()}; composite: {composite_label}", file=sys.stderr)
        if args.size not in {"landscape", f"{geometry.original_size[0]}x{geometry.original_size[1]}"}:
            print(f"[edit] note: --size {args.size} ignored; masked edits keep the source size", file=sys.stderr)

        generated_base = temp_dir / (final_output.name or "edited.png")
        cli_args = build_cli_args(
            args,
            prompt,
            output_path=str(generated_base),
            image_paths=context.image_paths,
            mask_path=context.mask_path,
            size_override=f"{geometry.work_size[0]}x{geometry.work_size[1]}",
        )
        exit_code = run_backend(cli_args)
        if exit_code != 0:
            return exit_code

        process_edit_outputs(context, output_paths(generated_base, args.n), final_paths, args)
        print(
            f"[edit] restored {geometry.original_size[0]}x{geometry.original_size[1]}; composite: {composite_label}",
            file=sys.stderr,
        )
        for path in final_paths:
            flatten_transparency(path, args)
        for path in display_paths:
            print(path)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
