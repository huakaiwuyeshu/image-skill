#!/usr/bin/env python3
"""Stable wrapper around the installed gpt-image CLI backend."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or edit images with gpt-image-2.")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("-p", "--prompt", help="Final optimized prompt.")
    prompt_group.add_argument("--prompt-file", help="Explicit path to the final optimized prompt file.")
    parser.add_argument("--save-prompt", help="Save the final optimized prompt to this explicit path.")
    parser.add_argument("-f", "--output", "--file", dest="output", required=True, help="Output image path.")
    parser.add_argument("-i", "--image", action="append", default=[], help="Reference image path. Repeatable.")
    parser.add_argument("-m", "--mask", help="Mask image path for inpainting.")
    parser.add_argument("--model", default="gpt-image-2", help="Image model. Defaults to gpt-image-2.")
    parser.add_argument("--size", default="landscape", help="Size shortcut or literal size.")
    parser.add_argument("--quality", default="high", choices=["auto", "low", "medium", "high"])
    parser.add_argument("--format", default="png", choices=["png", "jpeg", "webp"])
    parser.add_argument("-n", "--n", type=int, default=1)
    parser.add_argument("--background", choices=["auto", "opaque"])
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


def validate(args: argparse.Namespace) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set.")
    for image in args.image:
        if not Path(image).is_file():
            raise SystemExit(f"Reference image not found: {image}")
    if args.mask and not Path(args.mask).is_file():
        raise SystemExit(f"Mask image not found: {args.mask}")
    Path(args.output).resolve().parent.mkdir(parents=True, exist_ok=True)


def build_cli_args(args: argparse.Namespace, prompt: str) -> list[str]:
    cli_args = [
        "-p",
        prompt,
        "-f",
        args.output,
        "--model",
        args.model,
        "--size",
        args.size,
        "--quality",
        args.quality,
        "--format",
        args.format,
        "-n",
        str(args.n),
    ]
    for image in args.image:
        cli_args.extend(["-i", image])
    if args.mask:
        cli_args.extend(["-m", args.mask])
    if args.background:
        cli_args.extend(["--background", args.background])
    if args.moderation:
        cli_args.extend(["--moderation", args.moderation])
    if args.compression is not None:
        cli_args.extend(["--compression", str(args.compression)])
    if args.user:
        cli_args.extend(["--user", args.user])
    return cli_args


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


def main() -> int:
    args = parse_args()
    validate(args)
    prompt = resolve_prompt(args)
    if not prompt:
        raise SystemExit("Prompt is empty.")
    save_prompt_if_requested(prompt, args)
    cli_args = build_cli_args(args, prompt)
    exit_code = run_installed_module(cli_args)
    if exit_code is None:
        exit_code = run_executable(cli_args)
    if exit_code == 0 and Path(args.output).is_file():
        print(args.output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
