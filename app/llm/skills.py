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


# Default routing. Text agents ride MiniMax (key live-verified 2026-06-10:
# MiniMax-Text-01 and the M-series both work on this plan); the QA agent rides
# an AtlasCloud-hosted vision model so it can actually SEE frames (the gemini
# key in .env is empty, so gemini routing would fail at runtime).
_P = "minimax"  # text-agent provider; flip to "openai"/"anthropic"/"gemini" anytime
_M = None  # None -> the provider's default model from settings

SKILLS: dict[str, AgentSkill] = {
    "asset_recogniser": AgentSkill(
        "asset_recogniser", PROMPTS["asset_recogniser"], provider=_P, model=_M, temperature=0.2
    ),
    "character_memory": AgentSkill(
        "character_memory", PROMPTS["character_memory"], provider=_P, model=_M, temperature=0.4
    ),
    "script_agent": AgentSkill(
        "script_agent", PROMPTS["script_agent"], provider=_P, model=_M, temperature=0.8
    ),
    "idea_agent": AgentSkill(
        "idea_agent", PROMPTS["idea_agent"], provider=_P, model=_M, temperature=0.8
    ),
    "scene_agent": AgentSkill("scene_agent", PROMPTS["scene_agent"], provider=_P, model=_M, temperature=0.6),
    "shot_agent": AgentSkill("shot_agent", PROMPTS["shot_agent"], provider=_P, model=_M, temperature=0.5),
    "prompt_agent": AgentSkill("prompt_agent", PROMPTS["prompt_agent"], provider=_P, model=_M, temperature=0.6),
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
    # Autonomous director — low temperature for steady, deterministic decisions.
    "director": AgentSkill(
        "director", PROMPTS["director"], provider=_P, model=_M, temperature=0.2
    ),
    # Cheap text pre-render critic (MiniMax) + vision-grounded reviser (AtlasCloud).
    "spec_critic": AgentSkill(
        "spec_critic", PROMPTS["spec_critic"], provider=_P, model=_M, temperature=0.3
    ),
    "spec_reviser": AgentSkill(
        "spec_reviser", PROMPTS["spec_reviser"], provider="atlas", model=None, temperature=0.2
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
    "director": "Autopilot director",
    "spec_critic": "Pre-render critic",
    "spec_reviser": "Render reviser (vision)",
}


def agent_label(agent: str) -> str:
    return AGENT_LABELS.get(agent, agent)


@dataclass(frozen=True)
class ContextSource:
    """One optional context block an agent can ingest. `required=True` sources are
    always sent (shown locked-on in the UI for transparency); optional ones can be
    switched off per agent, which drops the block from the assembled user prompt."""

    key: str
    label: str
    required: bool = False


# What each agent CAN see. Optional (required=False) keys are gated by
# `gated_block`; the key strings here MUST match the keys passed there in each
# agent module. Required keys are documentation/UI only (never gated).
AGENT_CONTEXT_SOURCES: dict[str, list[ContextSource]] = {
    "asset_recogniser": [
        ContextSource("filename", "Filename", required=True),
        ContextSource("description", "Uploader description", required=True),
        ContextSource("known_character_ids", "Known character ids"),
    ],
    "character_memory": [
        ContextSource("notes", "Creator notes", required=True),
        ContextSource("reference_assets", "Reference asset descriptions", required=True),
        ContextSource("style", "Project style guide"),
    ],
    "script_agent": [
        ContextSource("idea", "Story idea", required=True),
        ContextSource("style", "Project style guide"),
        ContextSource("characters", "Existing characters"),
    ],
    "idea_agent": [
        ContextSource("idea", "Raw idea", required=True),
        ContextSource("style", "Project style guide"),
        ContextSource("characters", "Existing characters"),
    ],
    "scene_agent": [
        ContextSource("character_bibles", "Character bibles", required=True),
        ContextSource("available_asset_ids", "Available asset ids", required=True),
        ContextSource("assets", "Linked assets"),
        ContextSource("available_characters", "Other available characters"),
        ContextSource("library", "Asset library"),
        ContextSource("style", "Project style guide"),
        ContextSource("story", "Overall story & sibling scenes"),
    ],
    "shot_agent": [
        ContextSource("scene", "Scene spec", required=True),
        ContextSource("characters", "Cast"),
        ContextSource("assets", "Linked assets"),
        ContextSource("style", "Project style guide"),
        ContextSource("story", "Overall story & sibling scenes"),
    ],
    "prompt_agent": [
        ContextSource("shot", "Shot", required=True),
        ContextSource("references", "Named reference images", required=True),
        ContextSource("dialogue_language", "Dialogue language", required=True),
        ContextSource("style", "Project style guide"),
        ContextSource("story", "Overall story & sibling scenes"),
        ContextSource("character_bibles", "Character bibles (voice & looks)"),
    ],
    "qa_agent": [
        ContextSource("requirements", "Scene/shot requirements", required=True),
        ContextSource("frames", "Sampled video frames", required=True),
        ContextSource("reference_images", "Reference images (sheets/storyboard)"),
    ],
    "intent_agent": [
        ContextSource("message", "User message", required=True),
        ContextSource("scenes", "Scenes catalog", required=True),
        ContextSource("characters", "Characters catalog", required=True),
        ContextSource("history", "Conversation so far"),
        ContextSource("outputs", "Render outputs catalog"),
        ContextSource("state", "Project state"),
    ],
    "asset_planner": [
        ContextSource("scene", "Scene summary & spec", required=True),
        ContextSource("existing_assets", "Existing assets", required=True),
        ContextSource("library", "Asset library"),
        ContextSource("characters", "Cast"),
        ContextSource("story", "Overall story & sibling scenes"),
        ContextSource("style", "Style guide"),
        ContextSource("shots", "Scene shots"),
    ],
    "style_agent": [
        ContextSource("scripts", "Scripts (overall story)"),
        ContextSource("scenes", "Scenes"),
        ContextSource("characters", "Characters"),
        ContextSource("assets", "Assets"),
    ],
    "refine_agent": [
        ContextSource("entity", "Current scene/shot", required=True),
        ContextSource("instruction", "User instruction", required=True),
        ContextSource("style", "Project style guide"),
        ContextSource("story", "Overall story & sibling scenes"),
    ],
    "director": [
        ContextSource("state", "Run state (artifacts, QA verdict, budget)", required=True),
    ],
    "spec_critic": [
        ContextSource("spec", "Render spec", required=True),
        ContextSource("style", "Project style guide"),
        ContextSource("story", "Overall story"),
    ],
    "spec_reviser": [
        ContextSource("spec", "Render spec", required=True),
        ContextSource("qa", "QA issues", required=True),
        ContextSource("frames", "Flawed render frames", required=True),
        ContextSource("references", "Reference images"),
    ],
}


def context_sources(agent: str) -> list[ContextSource]:
    return AGENT_CONTEXT_SOURCES.get(agent, [])


# In-process per-agent overrides, mirrored from the DB. Loaded at startup (see
# settings_service.load_overrides) and rebuilt whenever the user saves a change.
# Each value is a record with any of: provider, model, system_prompt,
# temperature, max_retries, context_excludes (list[str]). Empty by default =>
# behaviour identical to the skill defaults.
_OVERRIDES: dict[str, dict] = {}

_RECORD_FIELDS = (
    "provider",
    "model",
    "system_prompt",
    "temperature",
    "max_retries",
    "context_excludes",
)


def _record_is_empty(rec: dict) -> bool:
    for f in _RECORD_FIELDS:
        v = rec.get(f)
        # temperature/max_retries 0 are valid overrides, so test by identity.
        if f in ("temperature", "max_retries"):
            if v is not None:
                return False
        elif v:
            return False
    return True


def is_customized(agent: str) -> bool:
    """True when the agent has any in-process override (routing or studio)."""
    return agent in _OVERRIDES


def set_record(
    agent: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_retries: int | None = None,
    context_excludes: list[str] | None = None,
) -> None:
    """Store the FULL override record for one agent (replacing any prior record).
    A record with no effective fields is dropped (revert to skill default)."""
    rec = {
        "provider": provider,
        "model": model,
        "system_prompt": system_prompt,
        "temperature": temperature,
        "max_retries": max_retries,
        "context_excludes": list(context_excludes) if context_excludes else None,
    }
    if _record_is_empty(rec):
        _OVERRIDES.pop(agent, None)
    else:
        _OVERRIDES[agent] = rec


def set_override(agent: str, provider: str | None, model: str | None) -> None:
    """Back-compat shim: set only provider/model (drops other override fields).
    The service rebuilds the whole mirror from the DB via load_overrides after a
    write, so callers that need full fidelity go through set_record."""
    set_record(agent, provider=provider, model=model)


def clear_overrides() -> None:
    _OVERRIDES.clear()


def context_excludes(agent: str) -> set[str]:
    """The optional context keys switched OFF for this agent (empty if none)."""
    rec = _OVERRIDES.get(agent)
    if not rec:
        return set()
    return set(rec.get("context_excludes") or [])


def get_skill(agent: str) -> AgentSkill | None:
    return SKILLS.get(agent)


def get_effective_skill(agent: str) -> AgentSkill | None:
    """The skill an agent actually runs with: base skill merged with any
    in-process override (provider, model, system_prompt, temperature,
    max_retries). Returns None for unknown agents."""
    base = SKILLS.get(agent)
    if base is None:
        return None
    rec = _OVERRIDES.get(agent)
    if not rec:
        return base
    from dataclasses import replace

    return replace(
        base,
        provider=rec.get("provider") or base.provider,
        model=rec["model"] if rec.get("model") is not None else base.model,
        system_prompt=(
            rec["system_prompt"]
            if rec.get("system_prompt")
            else base.system_prompt
        ),
        temperature=(
            rec["temperature"]
            if rec.get("temperature") is not None
            else base.temperature
        ),
        max_retries=(
            rec["max_retries"]
            if rec.get("max_retries") is not None
            else base.max_retries
        ),
    )
