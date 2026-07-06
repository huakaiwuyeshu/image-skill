# Image 2 Workflow Skill

Codex skill for GPT Image 2 image generation and image editing. It optimizes rough user requests into production prompts, saves prompts explicitly, and calls a local API-backed `gpt-image` CLI backend with model `gpt-image-2`.

## Install

Install this skill from the repository subdirectory:

```bash
python <codex-skill-installer>/install-skill-from-github.py --url https://github.com/huakaiwuyeshu/image-skill/tree/main/image-2-workflow --method git
```

Then restart Codex so it can discover the new skill.

If installing through a Codex UI that accepts a GitHub URL, use the subdirectory URL above, not the repository root URL.

## Requirements

- The user's own `OPENAI_API_KEY` must have access to `gpt-image-2`.
- Set `OPENAI_API_KEY` in the local environment.
- Set `OPENAI_BASE_URL` only when using a compatible custom gateway.
- Install a compatible `gpt-image` CLI backend, such as `gpt-image-cli`, so `scripts/run_gpt_image.py` can call it.
- For HTML prototype slicing, install Playwright and Chromium: `pip install playwright` and `python -m playwright install chromium`.
- For large prototype canvas image slicing, install Pillow, NumPy, and OpenCV: `pip install pillow numpy opencv-python`.

No API key or gateway URL is stored in this repository.
