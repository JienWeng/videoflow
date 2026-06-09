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


# Default routing: everything on MiniMax. Override `provider`/`model` per agent to
# route a specific task to OpenAI / Anthropic / Gemini.
_P = "gemini"  # text-agent provider; flip to "minimax"/"openai"/"anthropic" anytime
_M = "gemini-2.5-flash"  # model with available quota on this key

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
    "scene_agent": AgentSkill("scene_agent", PROMPTS["scene_agent"], provider=_P, model=_M, temperature=0.6),
    "shot_agent": AgentSkill("shot_agent", PROMPTS["shot_agent"], provider=_P, model=_M, temperature=0.5),
    "prompt_agent": AgentSkill("prompt_agent", PROMPTS["prompt_agent"], provider=_P, model=_M, temperature=0.6),
    "qa_agent": AgentSkill("qa_agent", PROMPTS["qa_agent"], provider=_P, model=_M, temperature=0.2),
}


def get_skill(agent: str) -> AgentSkill | None:
    return SKILLS.get(agent)
