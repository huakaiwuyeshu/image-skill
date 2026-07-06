---
name: image-2-workflow
description: "Use this skill for all image generation or image editing tasks: generate an image, draw a prototype, make a design mockup, turn a PRD or HTML prototype into editable prototype images, make an interaction/visual direction more exciting, create posters, edit existing images, UI/prototype/design-image generation, Chinese poster/design images, reference-image editing, language-described region edits, multi-area local edits, or any GPT Image 2/image-2 request. Always optimize the user's rough instruction into a production-ready prompt first, then generate using the local API-backed gpt-image CLI with model gpt-image-2. For PRD-only prototype work, infer product structure and design direction before prompting. For existing images, support user-marked regions, semantic region selection, and HTML prototype slicing before edit. Do not use host-native image generation unless explicitly requested."
---

# Image 2 Workflow

Default to this skill for image work. It combines prompt improvement with the installed `wuyoscar/GPT-Image2-Skill` CLI backend.

## Workflow

1. Classify the task as text-to-image, HTML prototype slicing, reference edit, inpaint/local edit, multi-reference edit, or free redesign.
2. Improve the user's rough instruction into a concise production prompt before generating.
3. Use local API-backed generation only:
   - Preferred wrapper: `scripts/run_gpt_image.py`
   - Backend: installed `gpt-image-cli`
   - Model: `gpt-image-2`
   - Environment: `OPENAI_API_KEY` and `OPENAI_BASE_URL`
4. Save the optimized prompt to an explicit per-image prompt file before generation. Use a matching basename, for example `outputs/gpt-image/prompts/<short-name>-<timestamp>.prompt.md` and `outputs/gpt-image/<short-name>-<timestamp>.png`.
5. Save outputs to a user-specified path when given. Otherwise use a sensible workspace path such as `outputs/gpt-image/<short-name>-<timestamp>.png`.
6. Report the final image path, prompt path, model, size, quality, and whether the request used text-to-image or edit mode.

Do not call host-native image generation tools. Do not create new ad-hoc OpenAI image scripts for normal use. Do not print API keys.

## Prototype Scenarios

Handle prototype/design-image requests in two distinct modes.

### 1. Requirement-Only Prototype

Use when the user provides only a PRD, requirement text, product idea, workflow description, or a rough command like "generate a prototype image".

Process:

- Extract the target platform, user role, core workflow, screen count if implied, and the most important product information.
- Parse product objects, key data fields, decision points, constraints, risk/compliance cues, and required UI states such as empty, loading, error, success, paid/locked, permission, and review states.
- Choose a reasonable screen/state if the user did not specify one.
- Choose the page architecture: navigation model, primary content zones, action hierarchy, detail panels, feedback surfaces, and state transitions.
- Choose a design language from the domain, audience, and any style words in the user's request. If the user asks for a more exciting, premium, imaginative, motion-heavy, cinematic, immersive, or unconventional result, trigger Creative Direction Mode below.
- Optimize the rough request into a complete UI/prototype prompt.
- Generate with text-to-image mode, without asking follow-up questions unless the missing choice would materially change the result.

The prompt must include interface hierarchy, realistic Chinese UI copy, visual density, components, layout, device/frame, and style.

### 1.a PRD-To-New-Prototype Playbook

When no existing design reference is available, do not default to generic safe UI and do not spend time browsing random design trend pages. Build enough design context from the PRD, then generate.

Required steps:

1. Convert the PRD into a compact design brief: product goal, target users, main scenario, primary workflow, important entities/data, business rules, and the screen/state to render.
2. Decide the output format: mobile screen, desktop page, multi-screen board, dashboard, web app, app prototype, poster-like concept UI, or interaction storyboard.
3. Define the information architecture before style: nav, content hierarchy, task flow, dominant module, secondary modules, calls to action, status/error surfaces, and realistic Chinese copy.
4. Pick a visual strategy:
   - Product-polished: usable, credible, production UI.
   - Premium editorial: stronger typography, asymmetric layout, refined imagery/materials.
   - Immersive/spatial: layered depth, cinematic lighting, 3D or spatial metaphors, motion cues.
   - Motion-first concept: interaction states, animated transition hints, timeline strips, gesture feedback, kinetic hierarchy.
   - Domain-native: visual language borrowed from the product domain, such as finance, game, retail, healthcare, logistics, developer tools, or enterprise operations.
5. Write one optimized prompt that combines the product structure and the selected visual strategy. If the user asks for multiple directions or the request is especially vague and high-stakes, create 2-3 distinct optimized direction prompts and, when budget allows, generate separate images for comparison.

### 2. Existing Prototype Modification

Use when the user provides one or more existing prototype/design images and asks to modify features, add modules, adjust layout, iterate a screen, or produce a new version based on them.

This analysis is required before generation:

- Inspect the provided image(s) and identify screen type, layout structure, navigation, component hierarchy, visual style, color palette, typography feel, spacing, and existing Chinese copy.
- Identify exactly what should be preserved and what should change.
- If the user describes the target area in words instead of drawing a box, locate the target semantically from the image before editing. Examples: top-left shelf card, the first row price column, the warning banner, the button under the amount field, the avatar area, the right-side summary panel.
- If the user asks to "continue", "modify", "add", "optimize", or gives no new style direction, preserve the original design style by default.
- If the user explicitly asks for a new style, redesign accordingly while still respecting the requested functional changes.
- Use reference-image edit mode with `--image` whenever a usable source image is provided. Use text-to-image only if the user explicitly wants a fresh redraw rather than a reference-based iteration.

The final prompt should mention the reference image and include preservation rules, for example: preserve the original visual language, layout density, typography feel, color system, device framing, and unchanged modules; update only the requested feature area.

### 3. HTML Prototype To Image Edit

Use when the user provides an HTML prototype, local HTML file, URL, exported web prototype, or a folder with HTML plus static assets and wants visual edits through the image workflow.

Process:

1. Render the HTML in a browser-equivalent environment before editing. Do not edit blindly from source code unless the user asks to change the HTML itself.
2. Slice the prototype into PNG assets with `scripts/slice_html_prototype.py`. Prefer screen/artboard/page-level slices over tiny image-only slices because downstream image editing needs full UI context.
3. Create a manifest so each slice has a stable path, source selector, visible text, bounds, and index.
4. Select the relevant slice from the user's description, manifest, and visual inspection. If unclear, ask one concise question or show the slice list.
5. Run the existing image edit flow on the selected PNG: semantic region selection, mask creation if needed, optimized prompt saving, then `scripts/run_gpt_image.py`.
6. If the user needs the HTML updated with the edited image, replace or add the saved PNG as a static asset only after confirming that is desired. The default deliverable is the edited PNG.

When the HTML contains many static images, choose among three strategies:

- Screen slicing: save each visible screen/card/page as one PNG. Use this for prototype iteration.
- Image-element slicing: save each large `<img>` as one PNG. Use this when the user asks to edit embedded artwork or banners.
- Full-page capture: save the entire rendered page when no reliable screen container exists.

Read `references/prompt-patterns.md` when writing prompts for HTML-derived edits.

## Edit Mode Decision

When the user provides an existing image, choose one of two modes.

### A. Faithful Local Edit

Use this mode when the user asks to add, remove, replace, mark, highlight, or slightly adjust specific content on the original image.

Required behavior:

- Preserve all unmodified regions as much as possible.
- Preserve the original visual style, color palette, typography feel, spacing, proportions, and screenshot layout unless the user explicitly asks otherwise.
- Use a mask whenever the target region is identifiable, whether the user marked it visually or described it in words. Create the mask with `scripts/make_mask.py` or another exact mask source.
- Keep the mask tight enough to prevent unrelated regions from changing, but large enough to fit the new content cleanly.
- The optimized prompt must include explicit preservation rules: "Edit only the masked area" and "Preserve the rest of the screenshot exactly."

This is the default for commands like "add a tag here", "modify this button", "replace this block", "add something inside the red box", or "keep all other areas unchanged".

## Region Selection For Existing Images

Support four ways to identify edit regions. Prefer the least burdensome method that is reliable.

1. User-marked region: use the red box/circle/annotation when provided.
2. Semantic region selection: when the user describes an area in words, inspect the image, infer the target module, estimate its bounding rectangle, then create a mask. Do not ask the user to draw if the target is clear.
3. Multi-region selection: for several local changes, infer one rectangle per target and pass repeated `--rect` values to `scripts/make_mask.py`. Keep a single optimized prompt that maps each requested change to its region. If unrelated edits risk bleeding into each other, run sequential edits and save each intermediate image explicitly.
4. Whole-module or free reference edit: if the requested change affects layout flow, typography across a section, or a large ambiguous module, use a larger module mask or reference edit mode instead of pretending it is a pixel-exact local edit.

Semantic locator rules:

- Use image dimensions and visible layout landmarks to estimate rectangles. Prefer slightly larger boxes around cards, badges, text blocks, buttons, and table cells so new content has room.
- Preserve context by masking only the editable region, not the whole screen.
- When there are multiple plausible targets, ask one concise question or generate a lightweight annotated preview/grid before spending API quota.
- When the user says "all", "each", or names repeated elements, select all matching visible instances.
- Record the selected region meaning and coordinates in the work notes or final response, for example: region: first product card badge area, rect x,y,w,h.
- For text-only changes in UI screenshots, mask the full text container rather than only the glyphs so typography can regenerate cleanly.

### B. Free Redesign

Use this mode when the user asks for a new page, new version, new style, redesign, creative exploration, or free-form visual exploration.

Required behavior:

- Use the existing image as inspiration/reference if provided, but do not promise pixel-level preservation.
- It is acceptable to change layout, style, visual hierarchy, copywriting, and component treatment according to the user's direction.
- Use text-to-image when no source image is needed; use reference-image edit without a tight mask when the old image should influence the new design.
- The optimized prompt should focus on the desired new page/design outcome, not strict preservation.

If the user's wording is ambiguous, default to Faithful Local Edit for modification requests and Free Redesign for new-page/design requests.

## Creative Direction Mode

Use this mode when the user says things like "make it visually exciting", "more imaginative", "strong interaction", "break the usual product UI", "premium", "cinematic", "cooler", or gives a new business idea with no style reference.

Purpose: avoid the generic AI product UI default while keeping the result usable and aligned with the PRD.

Process:

- If an existing image, brand guide, UI kit, or product screenshot exists, start from that context. Strong creativity should extend the context, not erase it unless the user asks for a fresh redesign.
- If no reference exists, choose one of these paths:
  - Single direct output: infer the best creative intensity from the user wording and generate one optimized prompt.
  - Direction exploration: produce 2-3 distinct direction prompts with different layout, interaction, material, and mood choices; generate multiple images only when the user asks for a set or comparison.
- Use a creative intensity ladder:
  - Level 1: polished production UI, stronger hierarchy and details.
  - Level 2: premium editorial/product UI, more expressive typography and composition.
  - Level 3: immersive/spatial UI, cinematic depth, layered surfaces, motion cues.
  - Level 4: experimental or motion-first concept, bolder interaction metaphors, game-like or entertainment-grade energy where appropriate.
- Encode interaction into the still image: hover/pressed states, drag handles, progress moments, before/after panels, timeline strips, microcopy feedback, gesture hints, state morphs, or transition ghosting.
- Avoid generic AI slop unless the domain explicitly calls for it: default purple gradients, random neon glow, emoji-as-icons, meaningless stats, over-rounded card soup, fake decoration, and placeholder gibberish.
- Browse only when current facts, real brands, real products, or a named benchmark need verification. Otherwise use reasoning and the user's product context instead of chasing trend lists.

For creative direction prompts, read `references/prompt-patterns.md` and use the PRD/prototype patterns there.

## Prompt Optimization

For rough requests, transform them into a complete prompt with:

- Subject and purpose.
- Visual medium: UI mockup, prototype screenshot, poster, product render, infographic, diagram, photo, illustration, etc.
- Layout and composition.
- Exact visible text, especially Chinese text.
- Style, color, lighting, material, atmosphere, and camera/framing.
- Output constraints: aspect ratio, no unwanted text, no real celebrity likenesses unless the user supplied permitted references.

Keep the final prompt direct. Do not explain the prompt inside the prompt. For UI/prototype/design images, specify interface density, device/frame, component hierarchy, realistic Chinese copy, and clear spacing.

## Generation Defaults

- Model: `gpt-image-2`.
- Quality: `high` for final posters, Chinese text, UI, diagrams, or detailed design images; `medium` for exploration; `low` only for cheap tests.
- Size:
  - `landscape` for horizontal posters, web hero images, dashboards, and desktop prototypes.
  - `portrait` for mobile screens, vertical posters, and app mockups.
  - `square` or `1k` for simple tests and social images.
  - `2k` or `4k` only when the user needs higher resolution.
- Format: `png` unless the user asks otherwise.

## Wrapper Usage

Use the bundled wrapper to avoid shell quoting issues with long Chinese prompts:

```bash
python "<skill-dir>/scripts/run_gpt_image.py" --prompt "..." --save-prompt "outputs/gpt-image/prompts/result.prompt.md" --output "outputs/gpt-image/result.png" --size landscape --quality high
```

For long prompts, first write the optimized prompt to an explicit file, then call the wrapper with that exact path:

```bash
python "<skill-dir>/scripts/run_gpt_image.py" --prompt-file "outputs/gpt-image/prompts/result.prompt.md" --output "outputs/gpt-image/result.png" --size landscape --quality high
```

Reference edit:

```bash
python "<skill-dir>/scripts/run_gpt_image.py" --prompt-file "outputs/gpt-image/prompts/edit.prompt.md" --output "outputs/gpt-image/edit.png" --image "input.png" --size landscape --quality high
```

Inpaint with mask:

```bash
python "<skill-dir>/scripts/run_gpt_image.py" --prompt "..." --output "outputs/gpt-image/inpaint.png" --image "input.png" --mask "mask.png" --size landscape --quality high
```

Create a rectangular mask for faithful local edits:

```bash
python "<skill-dir>/scripts/make_mask.py" --image "input.png" --output "mask.png" --rect x,y,w,h
```

Mask semantics: opaque white means preserve; transparent means regenerate/edit.

Slice an HTML prototype into editable PNG assets:

```bash
python "<skill-dir>/scripts/slice_html_prototype.py" --html "prototype/index.html" --output-dir "outputs/gpt-image/html-slices/<name>" --mode auto --viewport 1440x1200
```

Use `--selector ".screen"` or `--selector "[data-screen]"` when the prototype has known screen containers. Use `--mode img` only when the user specifically wants embedded image assets rather than full UI screens.

The wrapper calls `gpt_image_cli.cli` directly when installed. If that import is unavailable, it delegates to `gpt-image` on PATH.

## Prompt File Safety

Prompt saving must be explicit and deterministic:

- Never scan a prompt directory and never guess the latest prompt.
- Always pass either `--prompt "..."` or `--prompt-file "<exact path>"`.
- When saving prompts, use `--save-prompt "<exact path>"`.
- Use matching basenames for the prompt and image files.
- If using `--prompt-file`, verify that exact file exists before generation.

## Preflight

Before spending API quota:

- Confirm `OPENAI_API_KEY` is present without printing it.
- Confirm `OPENAI_BASE_URL` is set when using a gateway.
- For edits, verify all `--image` and `--mask` paths exist.
- For HTML slicing, verify the HTML path or URL is reachable and Playwright/Chromium is available. If not available, install or use an existing browser screenshot tool before proceeding.
- For expensive or ambiguous requests, ask at most one concise question. For clear "generate now" requests, proceed.

## Failure Handling

- Authentication errors mean the key or gateway is wrong; report the status and do not retry repeatedly.
- Argument parsing errors usually mean the prompt was passed through the shell incorrectly; use `scripts/run_gpt_image.py`.
- Long-running high-quality generations can take several minutes. If the tool times out, check whether the target file appeared before retrying.
