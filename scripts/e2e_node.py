#!/usr/bin/env python3
"""Full node-class E2E (needs torch/numpy/PIL, not ComfyUI): builds the real
generated node for a model and runs tensor-in → tensor-out through the live API.
SPENDS CREDITS. Defaults to the cheapest edit-capable model.

  BUDGETPIXEL_API_KEY=... [BUDGETPIXEL_API_BASE=...] python scripts/e2e_node.py \
      [--model flux-2-klein] [--prompt "..."]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bpx.schema_to_node import build_node  # noqa: E402

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")


def synthetic_batch():
    """Two 256x256 solid-color frames as a ComfyUI-style IMAGE batch."""
    import torch

    red = torch.zeros(1, 256, 256, 3)
    red[..., 0] = 1.0
    blue = torch.zeros(1, 256, 256, 3)
    blue[..., 2] = 1.0
    return torch.cat([red, blue], dim=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="flux-2-klein")
    ap.add_argument("--prompt", default="blend these two colors into a smooth abstract gradient poster")
    args = ap.parse_args()

    with open(os.path.join(SCHEMAS_DIR, args.model + ".json"), "r", encoding="utf-8") as f:
        schema = json.load(f)
    key, display, cls = build_node(schema)
    print("node:", key, "|", display)

    input_types = cls.INPUT_TYPES()
    media_params = [
        n for bucket in ("required", "optional")
        for n, w in input_types.get(bucket, {}).items()
        if w[0] == "IMAGE"
    ]
    if not media_params:
        sys.exit("model %s has no IMAGE input — use e2e_smoke.py instead" % args.model)
    print("feeding synthetic 2-frame batch into:", media_params[0])

    kwargs = {"prompt": args.prompt, media_params[0]: synthetic_batch()}
    (out,) = cls().generate(**kwargs)
    print("output tensor shape:", tuple(out.shape), "dtype:", out.dtype)
    if out.dim() != 4 or out.shape[3] != 3:
        sys.exit("FAIL: expected [B,H,W,3] IMAGE tensor")
    print("OK")


if __name__ == "__main__":
    main()
