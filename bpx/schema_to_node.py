"""Build ComfyUI node classes from the committed per-model JSON schemas.

Each file in schemas/ is a snapshot of one model's public /v1 contract, produced
by scripts/generate_schemas.py from the live OpenAPI spec (media params carry the
spec's `x-bpx-media` marker, so nothing is guessed from names). Conversion to
node classes happens at import time — the same pattern as Replicate's official
pack — so shipping a new model is a JSON diff, not new Python.
"""

import time

from .client import Client
from .jobs import submit_and_poll
from .media import (
    audio_input_to_url,
    audio_url_to_comfy,
    image_batch_to_api_values,
    make_video_output,
    urls_to_image_batch,
    video_input_to_url,
)

INT32_MAX = 2**31 - 1


def _extract_image(body, client):
    images = body.get("images") or []
    urls = [
        img["url"]
        for img in sorted(images, key=lambda i: i.get("position", 0))
        if img.get("url")
    ]
    return (urls_to_image_batch(urls, client),)


def _extract_upscale(body, client):
    url = body.get("image_url")
    if not url:
        raise RuntimeError("Job succeeded but returned no image_url.")
    return (urls_to_image_batch([url], client),)


def _extract_video(body, client):
    url = body.get("video_url")
    if not url:
        raise RuntimeError("Job succeeded but returned no video_url.")
    return (make_video_output(url, client),)


def _extract_audio(body, client):
    url = body.get("audio_url")
    if not url:
        raise RuntimeError("Job succeeded but returned no audio_url.")
    audio = audio_url_to_comfy(url, client)
    # Video-input SFX models also return the source video with effects mixed in;
    # for every other audio model this socket stays unconnected/None.
    video_url = body.get("video_url")
    video = make_video_output(video_url, client) if video_url else None
    return (audio, video)


# Per-kind wiring: menu category, status endpoint, poll cadence, outputs, and
# how a succeeded status body becomes node outputs. Status fields per pipeline
# verified against the server handlers (developer_api*.go).
KIND_CONFIG = {
    "image": {
        "category": "BudgetPixel/Image",
        "poll": "/images/{id}",
        "interval": 2.0,
        "timeout": 600,
        "returns": (("IMAGE", "images"),),
        "extract": _extract_image,
    },
    "upscale": {
        "category": "BudgetPixel/Upscale",
        "poll": "/upscales/{id}",
        "interval": 3.0,
        "timeout": 900,
        "returns": (("IMAGE", "image"),),
        "extract": _extract_upscale,
    },
    "video": {
        "category": "BudgetPixel/Video",
        "poll": "/videos/{id}",
        "interval": 10.0,
        "timeout": 2400,
        "returns": (("VIDEO", "video"),),
        "extract": _extract_video,
    },
    "video-upscale": {
        "category": "BudgetPixel/Upscale",
        "poll": "/video-upscales/{id}",
        "interval": 10.0,
        "timeout": 3600,
        "returns": (("VIDEO", "video"),),
        "extract": _extract_video,
    },
    "lip-sync": {
        "category": "BudgetPixel/Lip Sync",
        "poll": "/lip-sync/{id}",
        "interval": 10.0,
        "timeout": 2400,
        "returns": (("VIDEO", "video"),),
        "extract": _extract_video,
    },
    "motion-control": {
        "category": "BudgetPixel/Motion Control",
        "poll": "/motion-control/{id}",
        "interval": 10.0,
        "timeout": 2400,
        "returns": (("VIDEO", "video"),),
        "extract": _extract_video,
    },
    "audio": {
        "category": "BudgetPixel/Audio",
        "poll": "/audios/{id}",
        "interval": 8.0,
        "timeout": 1200,
        "returns": (("AUDIO", "audio"), ("VIDEO", "video")),
        "extract": _extract_audio,
    },
}

_MEDIA_SOCKET = {"image": "IMAGE", "video": "VIDEO", "audio": "AUDIO"}


def _widget_for_property(name, prop, required):
    """One OpenAPI property → (comfy_type, config) widget tuple or media socket."""
    cfg = {}
    desc = prop.get("description", "")
    if desc:
        cfg["tooltip"] = desc

    media = prop.get("x-bpx-media", "")
    if media:
        socket = _MEDIA_SOCKET.get(media)
        if socket is None:
            raise ValueError("param %r has unknown media type %r" % (name, media))
        return socket, cfg

    ptype = prop.get("type", "string")
    enum = prop.get("enum")
    if enum:
        cfg["default"] = prop.get("default", enum[0])
        return list(enum), cfg

    if ptype == "integer":
        if name == "seed":
            # -1 = "omit and let the server pick a random seed".
            cfg.update({"default": -1, "min": -1, "max": INT32_MAX})
        else:
            lo = prop.get("minimum", 0)
            hi = prop.get("maximum", INT32_MAX)
            cfg.update({"default": prop.get("default", lo), "min": lo, "max": hi})
        return "INT", cfg
    if ptype == "number":
        cfg.update(
            {
                "default": prop.get("default", prop.get("minimum", 0.0)),
                "min": prop.get("minimum", 0.0),
                "max": prop.get("maximum", 1e9),
                "step": 0.01,
            }
        )
        return "FLOAT", cfg
    if ptype == "boolean":
        cfg["default"] = bool(prop.get("default", False))
        return "BOOLEAN", cfg
    if ptype == "array":
        # Non-media string arrays are edited one-item-per-line.
        cfg["default"] = ""
        cfg["multiline"] = True
        cfg["tooltip"] = (desc + " (one item per line)").strip()
        return "STRING", cfg

    cfg["default"] = prop.get("default", "")
    if "prompt" in name or name == "lyrics":
        cfg["multiline"] = True
        if "template" not in name:
            cfg["dynamicPrompts"] = True
    return "STRING", cfg


def _ordered_param_names(schema):
    """Required params first (spec order), then the rest — the merged spec
    alphabetizes properties, which would bury `prompt` mid-widget-list."""
    props = schema["input"].get("properties", {})
    required = [n for n in schema["input"].get("required", []) if n in props]
    return required + [n for n in props if n not in required]


def build_input_types(schema):
    props = schema["input"].get("properties", {})
    required_names = set(schema["input"].get("required", []))
    input_types = {"required": {}, "optional": {}}
    for name in _ordered_param_names(schema):
        widget = _widget_for_property(name, props[name], name in required_names)
        bucket = "required" if name in required_names else "optional"
        input_types[bucket][name] = widget
    input_types["optional"]["force_rerun"] = ("BOOLEAN", {"default": False})
    return input_types


def _media_to_api_value(media, name, value, is_array, prop, client):
    if media == "image":
        api_values = image_batch_to_api_values(value, client)
        if is_array:
            max_items = prop.get("maxItems")
            if max_items and len(api_values) > max_items:
                print(
                    "[BudgetPixel] %s: got %d images, model takes %d — extra frames dropped"
                    % (name, len(api_values), max_items)
                )
                api_values = api_values[:max_items]
            return api_values
        if value.shape[0] > 1:
            print("[BudgetPixel] %s takes one image — using the first frame of the batch" % name)
        return api_values[0]
    if media == "video":
        url = video_input_to_url(value, client, name)
        return [url] if is_array else url
    if media == "audio":
        url = audio_input_to_url(value, client, name)
        return [url] if is_array else url
    raise ValueError("unknown media type %r" % media)


def _prepare_payload(schema, client, kwargs):
    props = schema["input"].get("properties", {})
    required_names = set(schema["input"].get("required", []))
    payload = {}
    for name, prop in props.items():
        value = kwargs.get(name)
        media = prop.get("x-bpx-media", "")
        is_array = prop.get("type") == "array"

        if media:
            if value is None:
                if name in required_names:
                    raise ValueError(
                        "Input '%s' is required — connect a %s." % (name, _MEDIA_SOCKET[media])
                    )
                continue
            payload[name] = _media_to_api_value(media, name, value, is_array, prop, client)
            continue

        if value is None:
            continue
        if name == "seed" and value == -1:
            continue
        if is_array:
            items = [line.strip() for line in str(value).splitlines() if line.strip()]
            if items:
                payload[name] = items
            continue
        if isinstance(value, str):
            if value == "" and name not in required_names:
                continue
            payload[name] = value
            continue
        payload[name] = value
    return payload


def build_node(schema):
    """One schema dict → (mapping_key, display_name, node_class), or None if the
    schema's kind isn't supported."""
    kind_cfg = KIND_CONFIG.get(schema.get("kind"))
    if kind_cfg is None:
        return None

    create_path = schema["path"]
    pricing_text = schema.get("pricing_text", "")
    description = (schema.get("description") or schema.get("summary") or "").strip()
    if pricing_text:
        description = (description + "\n\n" + pricing_text).strip()

    class BudgetPixelModelNode:
        @classmethod
        def INPUT_TYPES(cls):
            return build_input_types(schema)

        @classmethod
        def IS_CHANGED(cls, **kwargs):
            return time.time() if kwargs.get("force_rerun") else ""

        RETURN_TYPES = tuple(t for t, _ in kind_cfg["returns"])
        RETURN_NAMES = tuple(n for _, n in kind_cfg["returns"])
        FUNCTION = "generate"
        CATEGORY = kind_cfg["category"]
        DESCRIPTION = description

        def generate(self, **kwargs):
            client = Client()
            payload = _prepare_payload(schema, client, kwargs)
            body = submit_and_poll(
                client,
                create_path,
                payload,
                kind_cfg["poll"],
                interval=kind_cfg["interval"],
                timeout_s=kind_cfg["timeout"],
            )
            return kind_cfg["extract"](body, client)

    mapping_key = "BudgetPixel_" + schema["id"]
    display_name = "%s (BudgetPixel)" % schema.get("title", schema["id"])
    return mapping_key, display_name, BudgetPixelModelNode
