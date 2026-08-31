"""Offline smoke test: every committed schema builds a well-formed node class.

Runs without ComfyUI or torch (INPUT_TYPES construction is pure). Usage:
    python tests/test_nodes_build.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bpx.schema_to_node import KIND_CONFIG, build_input_types, build_node  # noqa: E402

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")

VALID_WIDGET_TYPES = {"INT", "FLOAT", "BOOLEAN", "STRING", "IMAGE", "VIDEO", "AUDIO"}


def check_schema(schema):
    problems = []
    built = build_node(schema)
    if built is None:
        if schema.get("kind") in KIND_CONFIG:
            problems.append("kind %r supported but build_node returned None" % schema.get("kind"))
        return problems
    key, display, cls = built
    if not key.startswith("BudgetPixel_"):
        problems.append("bad mapping key %r" % key)
    expected_returns = tuple(t for t, _ in KIND_CONFIG[schema["kind"]]["returns"])
    if cls.RETURN_TYPES != expected_returns:
        problems.append(
            "%s: RETURN_TYPES %r != expected %r for kind %s"
            % (schema["id"], cls.RETURN_TYPES, expected_returns, schema["kind"])
        )
    input_types = cls.INPUT_TYPES()
    for bucket in ("required", "optional"):
        for name, widget in input_types.get(bucket, {}).items():
            wtype, cfg = widget
            if isinstance(wtype, list):
                if not wtype:
                    problems.append("%s: empty enum for %s" % (schema["id"], name))
            elif wtype not in VALID_WIDGET_TYPES:
                problems.append("%s: widget %s has unknown type %r" % (schema["id"], name, wtype))
            if not isinstance(cfg, dict):
                problems.append("%s: widget %s config not a dict" % (schema["id"], name))
    for req in schema["input"].get("required", []):
        if req not in input_types.get("required", {}):
            problems.append("%s: required param %s not in required inputs" % (schema["id"], req))
    if "force_rerun" not in input_types.get("optional", {}):
        problems.append("%s: force_rerun missing" % schema["id"])
    # Media params must have become typed sockets, not free-text widgets.
    socket_for = {"image": "IMAGE", "video": "VIDEO", "audio": "AUDIO"}
    for name, prop in schema["input"].get("properties", {}).items():
        media = prop.get("x-bpx-media")
        if media:
            bucket = "required" if name in schema["input"].get("required", []) else "optional"
            wtype = input_types[bucket][name][0]
            if wtype != socket_for.get(media):
                problems.append(
                    "%s: media param %s became %r, want %s"
                    % (schema["id"], name, wtype, socket_for.get(media))
                )
    return problems


def main():
    files = sorted(f for f in os.listdir(SCHEMAS_DIR) if f.endswith(".json"))
    if not files:
        sys.exit("no schemas found in %s — run scripts/generate_schemas.py" % SCHEMAS_DIR)
    all_problems = []
    built_count = 0
    for fname in files:
        with open(os.path.join(SCHEMAS_DIR, fname), "r", encoding="utf-8") as f:
            schema = json.load(f)
        problems = check_schema(schema)
        if build_node(schema) is not None:
            built_count += 1
        all_problems.extend("%s: %s" % (fname, p) for p in problems)
    if all_problems:
        print("\n".join(all_problems))
        sys.exit("%d problem(s) across %d schema files" % (len(all_problems), len(files)))
    print("OK: %d schema files, %d node classes built cleanly" % (len(files), built_count))


if __name__ == "__main__":
    main()
