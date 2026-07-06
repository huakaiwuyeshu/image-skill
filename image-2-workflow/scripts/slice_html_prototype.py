#!/usr/bin/env python3
"""Render an HTML prototype and slice visible screens/images into PNG files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


COMMON_SCREEN_SELECTORS = [
    "[data-screen]",
    "[data-page]",
    "[data-artboard]",
    ".screen",
    ".page",
    ".artboard",
    ".frame",
    ".prototype-screen",
    ".prototype-page",
    ".mobile-screen",
    ".phone-screen",
    ".device-screen",
    ".canvas",
    "main > section",
    "body > section",
]


def parse_size(value: str) -> tuple[int, int]:
    if "x" not in value.lower():
        raise argparse.ArgumentTypeError("size must be WxH, for example 1440x1200")
    width_s, height_s = value.lower().split("x", 1)
    try:
        width, height = int(width_s), int(height_s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size values must be integers") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("size values must be positive")
    return width, height


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Slice an HTML prototype into PNG assets.")
    parser.add_argument("--html", required=True, help="Local HTML file or URL.")
    parser.add_argument("--output-dir", required=True, help="Directory for PNG slices and manifest.")
    parser.add_argument(
        "--mode",
        choices=["auto", "selector", "screen", "img", "fullpage"],
        default="auto",
        help="Slice strategy. auto tries selectors, then large images, then full page.",
    )
    parser.add_argument("--selector", action="append", default=[], help="CSS selector to screenshot. Repeatable.")
    parser.add_argument("--viewport", type=parse_size, default=parse_size("1440x1200"), help="Viewport WxH.")
    parser.add_argument("--scale", type=float, default=1.0, help="Device scale factor.")
    parser.add_argument("--wait-ms", type=int, default=1000, help="Extra wait after page load.")
    parser.add_argument("--min-width", type=int, default=180, help="Minimum element width.")
    parser.add_argument("--min-height", type=int, default=180, help="Minimum element height.")
    parser.add_argument("--max-slices", type=int, default=200, help="Maximum number of slices.")
    parser.add_argument("--prefix", default="slice", help="Output filename prefix.")
    parser.add_argument("--manifest", help="Optional manifest path. Defaults to output-dir/slices.json.")
    return parser.parse_args()


def source_to_url(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https", "file", "data"}:
        return source
    path = Path(source)
    if not path.is_file():
        raise SystemExit(f"HTML source not found: {path}")
    return path.resolve().as_uri()


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"\s+", "-", value.strip().lower())
    value = re.sub(r"[^a-z0-9._-]+", "", value)
    value = value.strip("-._")
    return value[:48] or fallback


def selectors_for_mode(mode: str, user_selectors: list[str]) -> list[list[str]]:
    if mode == "selector":
        if not user_selectors:
            raise SystemExit("--selector is required when --mode selector")
        return [user_selectors]
    if mode == "screen":
        return [user_selectors or COMMON_SCREEN_SELECTORS]
    if mode == "img":
        return [["img"]]
    if mode == "auto":
        groups: list[list[str]] = []
        if user_selectors:
            groups.append(user_selectors)
        groups.append(COMMON_SCREEN_SELECTORS)
        groups.append(["img"])
        return groups
    return []


def collect_candidates(page, selectors: list[str], min_width: int, min_height: int, max_slices: int) -> list[dict]:
    return page.evaluate(
        """
        ({ selectors, minWidth, minHeight, maxSlices }) => {
          const seen = new Set();
          const items = [];
          let counter = 0;
          for (const selector of selectors) {
            for (const element of document.querySelectorAll(selector)) {
              if (seen.has(element)) continue;
              seen.add(element);
              const rect = element.getBoundingClientRect();
              const style = window.getComputedStyle(element);
              if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) continue;
              if (rect.width < minWidth || rect.height < minHeight) continue;
              if (rect.bottom < 0 || rect.right < 0) continue;
              const sliceId = `codex-slice-${++counter}`;
              element.setAttribute("data-codex-slice-id", sliceId);
              const className = typeof element.className === "string" ? element.className : (element.getAttribute("class") || "");
              const label = (
                element.getAttribute("data-name") ||
                element.getAttribute("aria-label") ||
                element.getAttribute("alt") ||
                element.id ||
                className ||
                element.tagName.toLowerCase()
              );
              const text = (element.innerText || element.getAttribute("alt") || "").trim().replace(/\\s+/g, " ").slice(0, 160);
              items.push({
                id: sliceId,
                selector,
                tag: element.tagName.toLowerCase(),
                label: String(label).slice(0, 120),
                text,
                src: element.currentSrc || element.src || element.getAttribute("src") || "",
                bounds: {
                  x: Math.round(rect.left + window.scrollX),
                  y: Math.round(rect.top + window.scrollY),
                  width: Math.round(rect.width),
                  height: Math.round(rect.height)
                }
              });
              if (items.length >= maxSlices) return items;
            }
          }
          return items;
        }
        """,
        {
            "selectors": selectors,
            "minWidth": min_width,
            "minHeight": min_height,
            "maxSlices": max_slices,
        },
    )


def wait_until_stable(page, wait_ms: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)
    page.evaluate(
        """
        async () => {
          if (document.fonts && document.fonts.ready) {
            try { await document.fonts.ready; } catch (error) {}
          }
          const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
          const step = Math.max(window.innerHeight * 0.8, 500);
          let lastY = -1;
          for (let i = 0; i < 30; i += 1) {
            window.scrollBy(0, step);
            await sleep(80);
            if (window.scrollY === lastY) break;
            lastY = window.scrollY;
          }
          window.scrollTo(0, 0);
          await sleep(150);
          await Promise.all(Array.from(document.images).map((image) => {
            if (image.complete) return Promise.resolve();
            return new Promise((resolve) => {
              const done = () => resolve();
              image.addEventListener("load", done, { once: true });
              image.addEventListener("error", done, { once: true });
              setTimeout(done, 2000);
            });
          }));
        }
        """
    )


def run() -> int:
    args = parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Python package 'playwright' is required. Install it with: "
            "pip install playwright && python -m playwright install chromium"
        ) from exc

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest).resolve() if args.manifest else output_dir / "slices.json"
    source_url = source_to_url(args.html)
    viewport_width, viewport_height = args.viewport

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            device_scale_factor=args.scale,
        )
        page = context.new_page()
        page.goto(source_url, wait_until="domcontentloaded", timeout=30000)
        wait_until_stable(page, args.wait_ms)

        slices: list[dict] = []
        if args.mode == "fullpage":
            output_path = output_dir / f"{args.prefix}-fullpage.png"
            page.screenshot(path=str(output_path), full_page=True)
            slices.append({"index": 1, "path": str(output_path), "mode": "fullpage"})
        else:
            chosen_group: list[str] | None = None
            candidates: list[dict] = []
            for selectors in selectors_for_mode(args.mode, args.selector):
                candidates = collect_candidates(page, selectors, args.min_width, args.min_height, args.max_slices)
                if candidates:
                    chosen_group = selectors
                    break

            if not candidates and args.mode == "auto":
                output_path = output_dir / f"{args.prefix}-fullpage.png"
                page.screenshot(path=str(output_path), full_page=True)
                slices.append({"index": 1, "path": str(output_path), "mode": "fullpage"})
            else:
                for index, item in enumerate(candidates, start=1):
                    name_part = slugify(item.get("label") or item.get("text") or item.get("tag") or "", f"{index:03d}")
                    output_path = output_dir / f"{args.prefix}-{index:03d}-{name_part}.png"
                    locator = page.locator(f'[data-codex-slice-id="{item["id"]}"]')
                    locator.screenshot(path=str(output_path))
                    item.update({"index": index, "path": str(output_path)})
                    slices.append(item)

        manifest = {
            "source": args.html,
            "url": source_url,
            "mode": args.mode,
            "viewport": {"width": viewport_width, "height": viewport_height, "scale": args.scale},
            "selectors": chosen_group if args.mode != "fullpage" else [],
            "count": len(slices),
            "slices": slices,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        browser.close()

    print(manifest_path)
    for item in slices:
        print(item["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
