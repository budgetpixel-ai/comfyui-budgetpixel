"""API key + base-URL resolution.

Keys are resolved out-of-band on purpose: a key widget on nodes would serialize
`bpx_live_...` secrets into workflow JSON, and workflows are the thing people
share. Resolution order:

1. `BUDGETPIXEL_API_KEY` environment variable
2. `budgetpixel.json` next to this node pack (git-ignored), shape:
   {"api_key": "bpx_live_...", "base_url": "https://api.budgetpixel.com/v1"}

`BUDGETPIXEL_API_BASE` overrides the base URL (mainly for testing against
non-production environments).
"""

import json
import os

DEFAULT_BASE_URL = "https://api.budgetpixel.com/v1"
KEYS_URL = "https://budgetpixel.com/settings/api-keys?utm_source=comfyui"
PRICING_URL = "https://budgetpixel.com/pricing?utm_source=comfyui"

_PACK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PACK_ROOT, "budgetpixel.json")


class MissingAPIKeyError(RuntimeError):
    pass


def _read_config_file():
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_base_url():
    env = os.environ.get("BUDGETPIXEL_API_BASE", "").strip()
    if env:
        return env.rstrip("/")
    cfg = _read_config_file().get("base_url", "")
    if isinstance(cfg, str) and cfg.strip():
        return cfg.strip().rstrip("/")
    return DEFAULT_BASE_URL


def get_api_key():
    env = os.environ.get("BUDGETPIXEL_API_KEY", "").strip()
    if env:
        return env
    cfg = _read_config_file().get("api_key", "")
    if isinstance(cfg, str) and cfg.strip():
        return cfg.strip()
    raise MissingAPIKeyError(
        "No BudgetPixel API key found. Set the BUDGETPIXEL_API_KEY environment "
        "variable, or create budgetpixel.json inside the comfyui-budgetpixel "
        'folder containing {"api_key": "bpx_live_..."}. Create a key (any paid '
        "plan) at " + KEYS_URL
    )
