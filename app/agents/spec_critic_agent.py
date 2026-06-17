"""Cheap pre-render critic — a text-only check of a RenderSpec before paying for
Kling. May rewrite the prompt / per-shot prompts; never the references."""

from __future__ import annotations

from app.agents.base import as_block, gated_block, run_agent
from app.schemas.spec_critic_schema import SpecCritique


async def critique_spec(
    *, spec, style: dict | None = None, story: dict | None = None, client=None
) -> SpecCritique:
    parts = [as_block("Render spec to check", spec.model_dump(mode="json"))]
    parts += gated_block("spec_critic", "style", "Project style guide", style)
    parts += gated_block("spec_critic", "story", "Overall story", story)
    parts.append(
        "If the spec is renderable and on-contract, return ok=true with no "
        "revisions. Otherwise ok=false, list issues, and return a corrected "
        "revised_prompt and/or revised_multi_prompt (SAME shot count and "
        "durations). Never touch references."
    )
    return await run_agent(
        agent="spec_critic",
        response_model=SpecCritique,
        user_prompt="\n\n".join(parts),
        client=client,
    )
