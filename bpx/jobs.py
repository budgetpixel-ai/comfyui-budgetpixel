"""Async job flow: POST create → poll type-matched status endpoint.

Job ids are opaque strings (img_*/aud_* public ids, UUIDs for video and the
enhancement pipelines) — never parsed, only substituted into the poll path.
`succeeded` guarantees retrievable output URLs (the server reports `completing`
until outputs are uploaded), so callers can download immediately.
"""

import time

from .client import BudgetPixelAPIError

TERMINAL_FAILURES = ("failed", "timeout", "canceled", "cancelled")

# Rough progress per reported status, for the ComfyUI progress bar.
_STATUS_PROGRESS = {
    "pending": 10,
    "starting": 25,
    "processing": 60,
    "completing": 90,
    "succeeded": 100,
}


def _progress_bar():
    try:
        from comfy.utils import ProgressBar  # noqa: PLC0415

        return ProgressBar(100)
    except Exception:
        return None


def _check_interrupted():
    try:
        import comfy.model_management as mm  # noqa: PLC0415

        mm.throw_exception_if_processing_interrupted()
    except ImportError:
        pass


def submit_and_poll(client, create_path, payload, poll_path_template, interval=5.0, timeout_s=1800):
    """Create a job and poll until success; returns the final status body.

    Raises on failure statuses and on ComfyUI interrupts. An interrupt abandons
    the poll — the job keeps running server-side and still bills.
    """
    created = client.post_json(create_path, payload)
    job_id = created.get("id")
    if not job_id:
        raise BudgetPixelAPIError(0, "api_error", "no_job_id", "Create response had no job id: %r" % created)

    poll_path = poll_path_template.replace("{id}", str(job_id))
    bar = _progress_bar()
    started = time.time()
    last_status = ""
    while True:
        _check_interrupted()
        if time.time() - started > timeout_s:
            raise BudgetPixelAPIError(
                0, "timeout", "client_timeout",
                "Gave up waiting for job %s after %ds (still running server-side; it will still bill)."
                % (job_id, timeout_s),
            )
        body = client.get_json(poll_path)
        status = str(body.get("status", ""))
        if status != last_status:
            print("[BudgetPixel] job %s: %s" % (job_id, status))
            last_status = status
        if bar is not None:
            bar.update_absolute(_STATUS_PROGRESS.get(status, 50), 100)
        if status == "succeeded":
            return body
        if status in TERMINAL_FAILURES:
            raise BudgetPixelAPIError(
                0, "generation_failed", status,
                body.get("error") or body.get("error_message")
                or "Generation %s (job %s)." % (status, job_id),
            )
        time.sleep(interval)
