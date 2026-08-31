"""Hand-written utility nodes: account/credits, pre-flight cost, media upload."""

import json
import time

from .client import Client
from .media import image_batch_to_api_values


class BudgetPixelCredits:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"refresh": ("BOOLEAN", {"default": True, "tooltip": "Re-fetch on every run."})}}

    @classmethod
    def IS_CHANGED(cls, refresh=True):
        return time.time() if refresh else ""

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("credits",)
    FUNCTION = "fetch"
    CATEGORY = "BudgetPixel/Account"
    DESCRIPTION = "Your BudgetPixel credit balance (GET /v1/account/credits)."

    def fetch(self, refresh=True):
        b = Client().get_json("/account/credits")
        text = "Available: %s credits (monthly %s/%s used, extra %s)" % (
            b.get("total_available"),
            b.get("monthly_used"),
            b.get("monthly_limit"),
            b.get("extra_credits"),
        )
        print("[BudgetPixel] " + text)
        return (text,)


class BudgetPixelCostEstimate:
    """Pre-flight price check so a graph's spend is visible before running it."""

    MODEL_IDS = []  # filled by the pack's __init__ from the loaded schemas

    @classmethod
    def INPUT_TYPES(cls):
        models = cls.MODEL_IDS or ["(no models loaded)"]
        return {
            "required": {
                "model": (models, {}),
                "params_json": (
                    "STRING",
                    {
                        "default": "{}",
                        "multiline": True,
                        "tooltip": "Generation params as JSON, e.g. {\"num_images\": 2, \"size\": \"2K\"} — same fields as the model node.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("estimate",)
    FUNCTION = "estimate"
    CATEGORY = "BudgetPixel/Account"
    DESCRIPTION = "Estimated credit cost for a generation (POST /v1/cost). Discount-aware for your account."

    def estimate(self, model, params_json):
        try:
            params = json.loads(params_json) if params_json.strip() else {}
        except ValueError as e:
            raise ValueError("params_json is not valid JSON: %s" % e)
        body = {"model": model}
        body.update(params)
        result = Client().post_json("/cost", body)
        credits = result.get("credits", result)
        text = "%s: ~%s credits" % (model, credits)
        print("[BudgetPixel] " + text)
        return (text,)


class BudgetPixelUploadImage:
    """IMAGE → ephemeral upload URL(s) (POST /v1/uploads, 24h). Useful for
    feeding image URLs into string params or for debugging payloads."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE", {})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("url",)
    FUNCTION = "upload"
    CATEGORY = "BudgetPixel/Media"
    DESCRIPTION = "Uploads image frame(s) and returns their temporary URL(s), one per line."

    def upload(self, image):
        client = Client()
        values = []
        for i in range(image.shape[0]):
            from .media import tensor_to_png_bytes  # noqa: PLC0415

            values.append(client.upload(tensor_to_png_bytes(image[i]), "upload-%d.png" % i, "image/png"))
        return ("\n".join(values),)


UTILITY_NODES = {
    "BudgetPixelCredits": ("BudgetPixel Credits", BudgetPixelCredits),
    "BudgetPixelCostEstimate": ("BudgetPixel Cost Estimate", BudgetPixelCostEstimate),
    "BudgetPixelUploadImage": ("BudgetPixel Upload Image", BudgetPixelUploadImage),
}
