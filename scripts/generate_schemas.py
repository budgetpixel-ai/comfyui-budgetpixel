#!/usr/bin/env python3
"""Regenerate schemas/*.json from the BudgetPixel /v1 OpenAPI spec.

The committed schemas are the pack's source of truth (nodes are built from them
at import time). Run this when models are added or params change, review the
JSON diff, bump the version in pyproject.toml, and publish.

Usage:
  python scripts/generate_schemas.py                          # prod spec, image models
  python scripts/generate_schemas.py --spec path/to/spec.yaml # local spec dump
  python scripts/generate_schemas.py --kinds image,upscale
  python scripts/generate_schemas.py --key bpx_live_...       # adds pricing + filters
                                                              # to API-available models

With --key the script also calls GET /v1/models to (a) drop models the API has
disabled and (b) embed pricing into each node's description. Without it, every
model in the spec is emitted, without pricing text.
"""

import argparse
import json
import os
import re
import sys
import urllib.request

try:
    import yaml
except ImportError:
    sys.exit("pyyaml is required: pip install pyyaml")

DEFAULT_SPEC = "https://api.budgetpixel.com/v1/openapi.yaml"

# path prefix -> (kind, poll path); create paths look like /<prefix>/<model-id>
KIND_BY_PREFIX = {
    "images": ("image", "/images/{id}"),
    "videos": ("video", "/videos/{id}"),
    "audios": ("audio", "/audios/{id}"),
    "upscales": ("upscale", "/upscales/{id}"),
    "video-upscales": ("video-upscale", "/video-upscales/{id}"),
    "lip-sync": ("lip-sync", "/lip-sync/{id}"),
    "motion-control": ("motion-control", "/motion-control/{id}"),
}


def read_spec(source):
    if re.match(r"^https?://", source):
        with urllib.request.urlopen(source, timeout=60) as resp:
            return yaml.safe_load(resp.read())
    with open(source, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_models(base_url, key):
    req = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": "Bearer " + key, "User-Agent": "comfyui-budgetpixel-codegen"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    if isinstance(data, dict):
        for k in ("models", "data"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    return {m["name"]: m for m in data if isinstance(m, dict) and m.get("name")}


def pricing_text(m):
    if not m:
        return ""
    unit = m.get("credits_per_unit")
    if unit:
        text = "Pricing: %s credits per %s" % (unit, m.get("unit_type") or "unit")
        floor = m.get("min_billable_seconds")
        if floor:
            text += " (%ss minimum)" % floor
        return text + "."
    per_gen = m.get("credits_per_generation")
    if per_gen:
        text = "Pricing: %s credits per generation" % per_gen
        if m.get("resolution_pricing"):
            text += " (varies by resolution)"
        return text + "."
    return ""


def clean_description(op):
    desc = op.get("description", "") or op.get("summary", "")
    # The spec description appends polling boilerplate + a docs link; the node
    # runtime handles polling, so keep only the model blurb.
    return desc.split("\n\n**Asynchronous.**")[0].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=DEFAULT_SPEC, help="OpenAPI spec URL or file path")
    ap.add_argument("--kinds", default="all",
                    help="'all' (default) or comma list: image,video,audio,upscale,video-upscale,lip-sync,motion-control")
    ap.add_argument("--key", default=os.environ.get("BUDGETPIXEL_API_KEY", ""),
                    help="API key for GET /v1/models (pricing + availability filter)")
    ap.add_argument("--base-url", default=os.environ.get("BUDGETPIXEL_API_BASE",
                    "https://api.budgetpixel.com/v1"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "schemas"))
    args = ap.parse_args()

    all_kinds = {kind for kind, _ in KIND_BY_PREFIX.values()}
    if args.kinds.strip() == "all":
        wanted_kinds = all_kinds
    else:
        wanted_kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
        unknown = wanted_kinds - all_kinds
        if unknown:
            sys.exit("unknown kinds: %s (valid: %s)" % (", ".join(unknown), ", ".join(sorted(all_kinds))))
    spec = read_spec(args.spec)
    models_by_name = {}
    if args.key:
        models_by_name = fetch_models(args.base_url, args.key)
        print("GET /v1/models: %d models available to this account's API" % len(models_by_name))

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    emitted, skipped_unavailable = [], []
    for path, ops in sorted(spec.get("paths", {}).items()):
        m = re.match(r"^/([a-z-]+)/([^{/}]+)$", path)
        if not m or "post" not in ops:
            continue
        prefix, model_id = m.group(1), m.group(2)
        if prefix not in KIND_BY_PREFIX:
            continue
        kind, poll = KIND_BY_PREFIX[prefix]
        if kind not in wanted_kinds:
            continue
        if models_by_name and model_id not in models_by_name:
            skipped_unavailable.append(model_id)
            continue

        op = ops["post"]
        # Retired models are marked deprecated in the spec. They still have a
        # path (the endpoint answers 410 naming the successor), but a node built
        # from one can only ever fail, so it must not ship in the pack. The
        # models_by_name gate above catches this too when generating against a
        # live API — this covers generating from a spec file alone.
        if op.get("deprecated"):
            skipped_unavailable.append(model_id)
            continue
        body_schema = (
            op.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        # Summaries read "<verb phrase> with <Model Title>" — take the title part,
        # whatever the verb (generate/upscale/lip-sync/...).
        title = op.get("summary", model_id)
        if " with " in title:
            title = title.rsplit(" with ", 1)[1]

        schema = {
            "id": model_id,
            "kind": kind,
            "path": path,
            "poll_path": poll,
            "title": title,
            "category": (op.get("tags") or ["Models"])[0],
            "summary": op.get("summary", ""),
            "description": clean_description(op),
            "pricing_text": pricing_text(models_by_name.get(model_id)),
            "input": {
                "properties": body_schema.get("properties", {}),
                "required": body_schema.get("required", []),
            },
        }
        out_path = os.path.join(out_dir, model_id + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
            f.write("\n")
        emitted.append(model_id)

    print("wrote %d schemas to %s" % (len(emitted), out_dir))
    if skipped_unavailable:
        print("skipped (not API-available per /v1/models): %s" % ", ".join(skipped_unavailable))


if __name__ == "__main__":
    main()
