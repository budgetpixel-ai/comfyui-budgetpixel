# comfyui-budgetpixel

Official [BudgetPixel](https://budgetpixel.com) nodes for [ComfyUI](https://github.com/comfyanonymous/ComfyUI): generate with 60+ hosted image, video, music and sound-effect models — FLUX 2, Seedream 5.0, Qwen-Image 3.0, Kling v3, Nano Banana, GPT-Image, Seedance, Wan, and more — straight from your graph, using your BudgetPixel API key. No local GPU or model downloads needed for these nodes.

> Status: **beta** — full API parity: 58 model nodes across image (26), video (17), music & sound effects (8), upscaling (3), lip sync (2) and motion control (2), plus account utilities. Everything the [BudgetPixel API](https://docs.budgetpixel.com) exposes is a node here.

## Install

**ComfyUI-Manager** (recommended): search for **BudgetPixel** and install, then restart ComfyUI.

**Manual:**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/budgetpixel-ai/comfyui-budgetpixel.git
pip install -r comfyui-budgetpixel/requirements.txt
```

## API key

The nodes call the [BudgetPixel API](https://docs.budgetpixel.com), which is included in **every paid plan**. [Create a key](https://budgetpixel.com/settings/api-keys?utm_source=comfyui) and provide it one of two ways:

- environment variable: `BUDGETPIXEL_API_KEY=bpx_live_...`
- a `budgetpixel.json` file inside the `comfyui-budgetpixel` folder:

```json
{ "api_key": "bpx_live_..." }
```

Your key is **never stored in workflow JSON** — workflows you share stay safe to share. (That's also why the nodes have no api_key widget.)

## Nodes

Everything lives under **Add Node → BudgetPixel**. One node per model — each node's help text shows its credit price, and every widget mirrors the API's typed parameters (enums, ranges, defaults).

- **BudgetPixel/Image** — text-to-image, image editing and multi-reference composition (`FLUX 2 Pro`, `Seedream 5.0 Pro`, `Nano Banana Pro`, …). Image inputs are normal `IMAGE` connections; batches map onto multi-reference models automatically.
- **BudgetPixel/Video** — text-to-video, image-to-video (start/end frame), reference-to-video and video editing (`Kling v3`, `Seedance 2.5`, `Wan 3.0`, `MiniMax H3`, …). Outputs are core `VIDEO` values — wire into Save Video or frame extractors.
- **BudgetPixel/Audio** — music (`Music 3.0`, `Lyria 3`, `Mureka V9`, …) and sound effects (`Sonilo SFX`). Video-to-SFX and video-to-music take a `VIDEO` input; Sonilo Video SFX also returns the source video with the effects mixed in.
- **BudgetPixel/Upscale** — image upscalers plus Topaz Labs video upscaling.
- **BudgetPixel/Lip Sync**, **BudgetPixel/Motion Control** — talking-head sync from `IMAGE`/`VIDEO` + `AUDIO`, and motion transfer from a reference video.
- **BudgetPixel/Account** — `BudgetPixel Credits` (live balance) and `BudgetPixel Cost Estimate` (exact pre-flight price, discount-aware for your account).
- **BudgetPixel/Media** — `BudgetPixel Upload Image` (temporary URL for an image, e.g. for debugging payloads).

Generation is asynchronous server-side: nodes show progress and poll until the result is ready, then download it into the graph. Interrupting a running graph stops the wait, but a job already submitted keeps running (and billing) server-side. Video and audio inputs are uploaded via the API's temporary storage; nothing is stored in your workflow file except normal node values.

> `VIDEO` outputs use the ComfyUI core video type — use a recent ComfyUI (2025+) for video and audio nodes.

## Pricing

Generations are billed in BudgetPixel credits from your plan, identically to the web app — the node help text shows each model's price, and the **Cost Estimate** node gives an exact pre-flight number including your account's discounts. Prices summary: [budgetpixel.com/pricing](https://budgetpixel.com/pricing?utm_source=comfyui).

## Development / how models stay current

Nodes are built at import time from committed `schemas/*.json` snapshots of the [public OpenAPI spec](https://api.budgetpixel.com/v1/openapi.yaml) — adding a model to the pack is a JSON diff, not new Python. Three ways they update:

1. **On demand**: the `sync models from API` workflow (Actions tab → run) regenerates the schemas from the live spec and opens a PR when models or params changed. Merge, bump the version in `pyproject.toml`, and the publish workflow ships to the Comfy Registry.
2. **Locally**: `python scripts/generate_schemas.py` (add `BUDGETPIXEL_API_KEY` for pricing text + availability filtering).
3. **Verification**: `python tests/test_nodes_build.py` — offline check that every schema builds a well-formed node (no ComfyUI/torch needed); runs in CI on every PR.

`scripts/e2e_smoke.py` / `scripts/e2e_node.py` are live end-to-end tests against a real API (they spend credits; use a test account).

Issues and PRs welcome.
