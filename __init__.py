"""ComfyUI-BudgetPixel — official BudgetPixel nodes for ComfyUI.

Node classes are built at import time from the committed schemas/ JSON snapshots
of the public /v1 API (see bpx/schema_to_node.py). A broken schema file skips
that one node with a console warning instead of taking the whole pack down.
"""

import json
import os

from .bpx.schema_to_node import build_node
from .bpx.util_nodes import UTILITY_NODES, BudgetPixelCostEstimate

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")


def _load_model_nodes():
    if not os.path.isdir(_SCHEMAS_DIR):
        print("[BudgetPixel] schemas/ missing — no model nodes loaded")
        return
    model_ids = []
    for fname in sorted(os.listdir(_SCHEMAS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_SCHEMAS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            built = build_node(schema)
            if built is None:
                continue
            key, display, cls = built
            NODE_CLASS_MAPPINGS[key] = cls
            NODE_DISPLAY_NAME_MAPPINGS[key] = display
            model_ids.append(schema["id"])
        except Exception as e:  # one bad schema must not sink the pack
            print("[BudgetPixel] skipping %s: %s" % (fname, e))
    BudgetPixelCostEstimate.MODEL_IDS = sorted(model_ids)
    print("[BudgetPixel] loaded %d model nodes" % len(model_ids))


_load_model_nodes()

for _key, (_display, _cls) in UTILITY_NODES.items():
    NODE_CLASS_MAPPINGS[_key] = _cls
    NODE_DISPLAY_NAME_MAPPINGS[_key] = _display

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
