"""Shared agent helper.

Each agent is a thin async function: build a user prompt from typed inputs, then
delegate to the structured-output engine with the right response_model. Agents
never touch HTTP or the DB — services own persistence.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel

from app.llm import skills
from app.llm.structured_client import StructuredLLMClient, get_llm_client

T = TypeVar("T", bound=BaseModel)


async def run_agent(
    *,
    agent: str,
    response_model: type[T],
    user_prompt: str,
    context: dict | None = None,
    images: list[str] | None = None,
    client: StructuredLLMClient | None = None,
) -> T:
    client = client or get_llm_client()
    return await client.generate(
        agent=agent,
        response_model=response_model,
        user_prompt=user_prompt,
        context=context,
        images=images,
    )


def as_block(label: str, value: object) -> str:
    """Render a labelled context block for inclusion in a user prompt."""
    if isinstance(value, BaseModel):
        body = value.model_dump_json(indent=2)
    elif isinstance(value, (dict, list)):
        body = json.dumps(value, indent=2, ensure_ascii=False)
    else:
        body = str(value)
    return f"### {label}\n{body}"


def gated_block(agent: str, key: str, label: str, value: object) -> list[str]:
    """A context block the user can switch off per agent. Returns
    `[as_block(label, value)]`, or `[]` when the value is empty OR the user has
    disabled this context `key` for `agent` (see skills.context_excludes). Splat
    the result into the prompt's block list: `parts += gated_block(...)`."""
    if value is None or value == "" or value == [] or value == {}:
        return []
    if key in skills.context_excludes(agent):
        return []
    return [as_block(label, value)]
