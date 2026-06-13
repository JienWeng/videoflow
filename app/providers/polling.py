"""Generic async poll loop shared by image (inline) and video (worker) flows."""

from __future__ import annotations

import asyncio
import logging
import re

from app.errors import ProviderError, TimeoutError_
from app.providers.base import PollResult

logger = logging.getLogger("videoflow.polling")


# Known provider error signatures -> (human message, suggested action). Keys are
# matched case-insensitively as substrings against the raw provider error, so a
# wrapped message like "AtlasCloud ... ret:1201 max number is 7" still maps. The
# Kling o3-pro gateway returns numeric ret: codes; we translate the ones we know
# into plain language with a concrete next step the user can act on.
_PROVIDER_ERROR_RULES: list[tuple[str, str, str]] = [
    (
        "ret:1201",
        "The video model rejected the request (too many reference images or an "
        "invalid parameter).",
        "Reduce the number of reference images (the Kling limit is 7) or simplify "
        "the shot, then retry.",
    ),
    (
        "ret:1000",
        "The video model had an internal error.",
        "This is usually transient — retry the render in a moment.",
    ),
    (
        "sensitive",
        "The video model flagged the prompt or a reference image as sensitive "
        "content.",
        "Edit the prompt to remove flagged wording and retry.",
    ),
    (
        "risk control",
        "The video model flagged the prompt or a reference image as sensitive "
        "content.",
        "Edit the prompt to remove flagged wording and retry.",
    ),
    (
        "timed out",
        "The render took longer than the allowed time and was stopped.",
        "Retry — generation load varies, and a second attempt often completes.",
    ),
    (
        "no reference image",
        "The render needs at least one reference image.",
        "Attach a character sheet or scene asset, then retry.",
    ),
]

# Pull a bare ret:NNNN code out of a raw error for inclusion in the human message.
_RET_CODE_RE = re.compile(r"ret:(\d+)", re.IGNORECASE)


def humanize_provider_error(raw: str | None) -> dict:
    """Map a raw provider error to {message, action, raw, code}.

    `message` is plain-language; `action` is a concrete suggested next step (may
    be ""). Unknown errors fall back to the raw text with a generic retry hint.
    Pure — safe to call from poll_service and the API."""
    raw = (raw or "").strip()
    if not raw:
        return {
            "message": "The render failed for an unknown reason.",
            "action": "Retry the render.",
            "raw": raw,
            "code": None,
        }
    low = raw.lower()
    code_match = _RET_CODE_RE.search(raw)
    code = f"ret:{code_match.group(1)}" if code_match else None
    for needle, message, action in _PROVIDER_ERROR_RULES:
        if needle in low:
            return {"message": message, "action": action, "raw": raw, "code": code}
    return {
        "message": raw,
        "action": "Retry the render; if it keeps failing, simplify the prompt or "
        "reference images.",
        "raw": raw,
        "code": code,
    }


async def poll_until_terminal(
    provider,
    job_id: str,
    *,
    interval_s: float,
    timeout_s: float,
    max_transient_failures: int = 5,
) -> PollResult:
    """Poll provider.poll(job_id) until succeeded/failed or timeout.

    Transient poll errors (e.g. a 502 from the gateway while the job is still
    running) are tolerated: they're logged and retried, and only abort the wait
    after `max_transient_failures` in a row. The underlying job keeps running on
    the provider regardless of a hiccup on the status endpoint.
    """
    waited = 0.0
    delay = interval_s
    consecutive_failures = 0
    while True:
        try:
            result: PollResult = await provider.poll(job_id)
            consecutive_failures = 0
            if result.status == "succeeded":
                return result
            if result.status == "failed":
                raise ProviderError(result.error or "generation failed", raw=result.raw)
        except ProviderError as exc:
            # A 'failed' status is terminal; a transient transport error is not.
            if getattr(exc, "extra", {}).get("raw"):
                raise
            consecutive_failures += 1
            logger.warning(
                "transient poll error (%d/%d) for %s: %s",
                consecutive_failures, max_transient_failures, job_id, exc,
            )
            if consecutive_failures >= max_transient_failures:
                raise
        if waited >= timeout_s:
            raise TimeoutError_(f"generation timed out after {timeout_s}s")
        await asyncio.sleep(delay)
        waited += delay
        delay = min(delay * 1.5, 30.0)  # capped backoff
