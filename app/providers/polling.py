"""Generic async poll loop shared by image (inline) and video (worker) flows."""

from __future__ import annotations

import asyncio
import logging

from app.errors import ProviderError, TimeoutError_
from app.providers.base import PollResult

logger = logging.getLogger("videoflow.polling")


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
