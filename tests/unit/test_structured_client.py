"""Unit tests for the structured-output engine error handling.

These mock the instructor layer so they run without network or API keys.
"""

from __future__ import annotations

import asyncio
import types

import instructor
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm.exceptions import LLMTimeout, LLMValidationError
from app.llm.providers import Backend
from app.llm.structured_client import StructuredLLMClient


class Sample(BaseModel):
    name: str
    value: int


def _client() -> StructuredLLMClient:
    return StructuredLLMClient(Settings(MINIMAX_API_KEY="k", ATLASCLOUD_API_KEY="k"))


def _fake_backend(create_fn) -> Backend:
    """A Backend whose instructor client's chat.completions.create = create_fn."""
    completions = types.SimpleNamespace(create=create_fn)
    chat = types.SimpleNamespace(completions=completions)
    fake_client = types.SimpleNamespace(chat=chat)
    return Backend(client=fake_client, kind="openai", default_model="m", mode=instructor.Mode.JSON)


async def test_success_returns_validated_model(monkeypatch):
    client = _client()

    async def create(**kwargs):
        assert kwargs["response_model"] is Sample
        return Sample(name="ava", value=7)

    monkeypatch.setattr(client, "_backend", lambda provider, model, timeout_s: _fake_backend(create))
    out = await client.generate(response_model=Sample, user_prompt="hi")
    assert out == Sample(name="ava", value=7)


async def test_timeout_maps_to_llm_timeout(monkeypatch):
    client = _client()

    async def create(**kwargs):
        await asyncio.sleep(1)
        return Sample(name="x", value=1)

    monkeypatch.setattr(client, "_backend", lambda provider, model, timeout_s: _fake_backend(create))
    with pytest.raises(LLMTimeout):
        await client.generate(response_model=Sample, user_prompt="hi", timeout_s=0.05)


async def test_retry_exhaustion_maps_to_validation_error(monkeypatch):
    client = _client()

    class FakeCompletion:
        choices = [
            types.SimpleNamespace(
                message=types.SimpleNamespace(content='{"name": "ava"}')
            )
        ]

    class InstructorRetryException(Exception):
        def __init__(self):
            super().__init__("retries exhausted")
            self.last_completion = FakeCompletion()

    async def create(**kwargs):
        raise InstructorRetryException()

    monkeypatch.setattr(client, "_backend", lambda provider, model, timeout_s: _fake_backend(create))
    with pytest.raises(LLMValidationError) as ei:
        await client.generate(response_model=Sample, user_prompt="hi", max_retries=2)
    # The raw completion is captured for debugging.
    assert ei.value.extra.get("raw") == '{"name": "ava"}'


async def test_skill_routes_to_its_provider(monkeypatch):
    """A skill's provider/model selection reaches the backend factory."""
    from app.llm import skills

    client = _client()
    captured = {}

    async def create(**kwargs):
        return Sample(name="ok", value=1)

    def fake_backend(provider, model, timeout_s):
        captured["provider"] = provider
        captured["model"] = model
        return _fake_backend(create)

    # Route the script_agent skill to Anthropic for this test.
    monkeypatch.setitem(
        skills.SKILLS,
        "script_agent",
        skills.AgentSkill("script_agent", "sys", provider="anthropic", model="claude-x"),
    )
    monkeypatch.setattr(client, "_backend", fake_backend)

    await client.generate(response_model=Sample, user_prompt="hi", agent="script_agent")
    assert captured == {"provider": "anthropic", "model": "claude-x"}
