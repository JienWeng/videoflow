"""Agent skill registry.

Each agent is a declarative skill: its system prompt plus which LLM it routes to
(provider + model) and how it's tuned (temperature, retries). Change an agent's
brain by editing one line here — e.g. point `script_agent` at Anthropic and leave
`asset_recogniser` on a cheap MiniMax model. The structured-output engine reads
these to dispatch to the right backend while enforcing the same Pydantic schema.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.prompts import PROMPTS
from app.llm.providers import ProviderName


@dataclass(frozen=True)
class AgentSkill:
    name: str
    system_prompt: str
    provider: ProviderName = "minimax"
    model: str | None = None  # None -> provider default model
    temperature: float = 0.4
    max_retries: int = 3


# Default routing. The named connection remains overridable per agent in the
# Settings UI, but the story/scene/shot chain starts on the configured
# OpenCode Go JSON-capable endpoint for more reliable continuity.
_P = "opencode-go"
_M = "deepseek-v4-flash"

SKILLS: dict[str, AgentSkill] = {
    "asset_recogniser": AgentSkill(
        "asset_recogniser", PROMPTS["asset_recogniser"], provider=_P, model=_M, temperature=0.2
    ),
    "character_memory": AgentSkill(
        "character_memory", PROMPTS["character_memory"], provider=_P, model=_M, temperature=0.4
    ),
    "script_agent": AgentSkill(
        "script_agent", PROMPTS["script_agent"], provider=_P, model=_M, temperature=0.3
    ),
    "idea_agent": AgentSkill(
        "idea_agent", PROMPTS["idea_agent"], provider=_P, model=_M, temperature=0.5
    ),
    "scene_agent": AgentSkill("scene_agent", PROMPTS["scene_agent"], provider=_P, model=_M, temperature=0.3),
    "shot_agent": AgentSkill("shot_agent", PROMPTS["shot_agent"], provider=_P, model=_M, temperature=0.2),
    "prompt_agent": AgentSkill("prompt_agent", PROMPTS["prompt_agent"], provider=_P, model=_M, temperature=0.2),
    # Vision QA: AtlasCloud OpenAI-compatible endpoint, qwen3-vl by default.
    "qa_agent": AgentSkill("qa_agent", PROMPTS["qa_agent"], provider="atlas", model=None, temperature=0.2),
    "intent_agent": AgentSkill(
        "intent_agent", PROMPTS["intent_agent"], provider=_P, model=_M, temperature=0.0
    ),
    "asset_planner": AgentSkill(
        "asset_planner", PROMPTS["asset_planner"], provider=_P, model=_M, temperature=0.4
    ),
    "style_agent": AgentSkill(
        "style_agent", PROMPTS["style_agent"], provider=_P, model=_M, temperature=0.3
    ),
    "refine_agent": AgentSkill(
        "refine_agent", PROMPTS["refine_agent"], provider=_P, model=_M, temperature=0.4
    ),
}


# Friendly labels for the Settings UI (every agent in SKILLS must appear here).
AGENT_LABELS: dict[str, str] = {
    "script_agent": "Script writer",
    "scene_agent": "Scene director",
    "shot_agent": "Shot planner",
    "prompt_agent": "Prompt engineer",
    "qa_agent": "Vision QA",
    "idea_agent": "Idea developer",
    "asset_planner": "Asset planner",
    "refine_agent": "Editor (refine)",
    "intent_agent": "Intent classifier",
    "asset_recogniser": "Asset recogniser",
    "character_memory": "Character bible",
    "style_agent": "Style designer",
}


def agent_label(agent: str) -> str:
    return AGENT_LABELS.get(agent, agent)


# In-process per-agent routing overrides, mirrored from the DB. Loaded at startup
# (see settings_service.load_overrides) and updated whenever the user saves a
# change. Empty by default => behaviour identical to the skill defaults.
_OVERRIDES: dict[str, tuple[str | None, str | None]] = {}


def set_override(agent: str, provider: str | None, model: str | None) -> None:
    """Update (or clear) the in-process override for one agent."""
    if provider is None and model is None:
        _OVERRIDES.pop(agent, None)
    else:
        _OVERRIDES[agent] = (provider, model)


def clear_overrides() -> None:
    _OVERRIDES.clear()


def get_skill(agent: str) -> AgentSkill | None:
    return SKILLS.get(agent)


def get_effective_skill(agent: str) -> AgentSkill | None:
    """The skill an agent actually runs with: base skill merged with any
    in-process override (provider and/or model). Returns None for unknown agents.
    """
    base = SKILLS.get(agent)
    if base is None:
        return None
    override = _OVERRIDES.get(agent)
    if override is None:
        return base
    provider, model = override
    from dataclasses import replace

    return replace(
        base,
        provider=provider or base.provider,
        model=model if model is not None else base.model,
    )
