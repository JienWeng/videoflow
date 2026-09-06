"""Structured conversation planner for controlled scene conversion."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import ConversationBrief, ConversationPlan


async def plan_conversation(
    *,
    scene: dict,
    shots: list[dict],
    characters: list[dict],
    brief: ConversationBrief,
    style: dict | None = None,
    story: dict | None = None,
    client=None,
) -> ConversationPlan:
    """Produce one constrained dialogue turn for every existing shot."""

    parts = [
        as_block("Current scene", scene),
        as_block("Existing shots (fixed order; do not add or remove shots)", shots),
        as_block("Allowed cast (use only these exact speaker names)", characters),
        as_block("Conversation brief", brief),
    ]
    if style:
        parts.append(as_block("Project style guide", style))
    if story:
        parts.append(as_block("Overall story and sibling scenes", story))
    parts.append(
        "Create a ConversationPlan, not prose. Return exactly one turn for every "
        "existing shot, using shot_index 0..N-1 in order. Do not add characters, "
        "events, locations, props, or camera directions. Keep each shot's visual "
        "intent in visual_action. Each line must be a direct response to the prior "
        "turn when a prior turn exists, and must fit the requested word limit. "
        "Use only an allowed cast name as speaker; use Narrator only when the brief "
        "explicitly allows narration. Do not put quotation marks around line. "
        "Do not include stage directions in line. Keep the scene_summary faithful "
        "to the current plot while making the interaction conversational."
    )
    return await run_agent(
        agent="conversation_agent",
        response_model=ConversationPlan,
        user_prompt="\n\n".join(parts),
        client=client,
    )
