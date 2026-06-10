"""Unit tests for the shared poll loop."""

from __future__ import annotations

import pytest

from app.errors import ProviderError
from app.providers.base import PollResult
from app.providers.polling import poll_until_terminal


class FlakyProvider:
    """Raises transient transport errors before eventually succeeding."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    async def poll(self, job_id: str) -> PollResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError("gateway 502")
        return PollResult(status="succeeded", output_urls=["https://x/out.mp4"])


async def test_transient_errors_are_retried_until_success():
    provider = FlakyProvider(failures=2)
    result = await poll_until_terminal(provider, "job", interval_s=0.01, timeout_s=5)
    assert result.status == "succeeded"
    assert provider.calls == 3


async def test_persistent_transient_errors_eventually_raise():
    provider = FlakyProvider(failures=99)
    with pytest.raises(ProviderError):
        await poll_until_terminal(
            provider, "job", interval_s=0.01, timeout_s=5, max_transient_failures=3
        )
    assert provider.calls == 3
