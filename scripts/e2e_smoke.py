#!/usr/bin/env python3
"""Headless end-to-end smoke test against a real /v1 API (no ComfyUI/torch).

Exercises the exact code paths the nodes use — Client auth, payload prep from a
committed schema, submit + poll, output download — minus tensor conversion.
SPENDS REAL CREDITS on the account whose key it uses; default model is a cheap
one. Point it at non-production via BUDGETPIXEL_API_BASE.

Usage:
  BUDGETPIXEL_API_KEY=bpx_live_... [BUDGETPIXEL_API_BASE=http://localhost:8080/v1] \
      python scripts/e2e_smoke.py [--model z-image-turbo] [--prompt "..."]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bpx.client import Client  # noqa: E402
from bpx.jobs import submit_and_poll  # noqa: E402
from bpx.schema_to_node import KIND_CONFIG, _prepare_payload  # noqa: E402

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")

MAGIC = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg", b"RIFF": "webp/riff"}


def sniff(data):
    for magic, name in MAGIC.items():
        if data[: len(magic)] == magic:
            return name
    return "unknown(%r)" % data[:8]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="z-image-turbo")
    ap.add_argument("--prompt", default="a tiny pixel-art wizard casting a rainbow spell, white background")
    args = ap.parse_args()

    with open(os.path.join(SCHEMAS_DIR, args.model + ".json"), "r", encoding="utf-8") as f:
        schema = json.load(f)
    kind_cfg = KIND_CONFIG[schema["kind"]]

    client = Client()
    print("base URL:", client.base_url)

    before = client.get_json("/account/credits")
    print("credits before:", before.get("total_available"))

    cost = client.post_json("/cost", {"model": args.model, "prompt": args.prompt})
    print("estimated cost:", cost)

    payload = _prepare_payload(schema, client, {"prompt": args.prompt})
    print("payload:", payload)
    body = submit_and_poll(
        client, schema["path"], payload, schema["poll_path"],
        interval=kind_cfg["interval"], timeout_s=kind_cfg["timeout"],
    )
    images = body.get("images") or []
    urls = [i["url"] for i in sorted(images, key=lambda i: i.get("position", 0)) if i.get("url")]
    print("succeeded — %d image(s)" % len(urls))
    if not urls:
        sys.exit("FAIL: succeeded but no image URLs")
    data = client.download(urls[0])
    print("downloaded %d bytes, format=%s" % (len(data), sniff(data)))

    after = client.get_json("/account/credits")
    print("credits after:", after.get("total_available"))
    print("OK")


if __name__ == "__main__":
    main()
