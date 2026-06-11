"""Idea agent: context blocks, prompt content, and deterministic enforcement."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.agents.idea_agent import develop_idea
from app.errors import ValidationFailedError
from app.schemas import IdeaOption, IdeaOptions


def _make_options(n: int, recommended_index: int = 0) -> IdeaOptions:
    return IdeaOptions(
        options=[
            IdeaOption(
                title=f"Concept {i}",
                premise=f"Premise {i}.",
                hook=f"Hook {i}",
                why_it_works=f"Why {i}",
            )
            for i in range(1, n + 1)
        ],
        recommended_index=recommended_index,
        reasoning="the first concept lands the hook fastest",
    )


class FakeLLM:
    def __init__(self, result: IdeaOptions):
        self.result = result
        self.calls: list[dict] = []

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.calls.append({"agent": agent, "user_prompt": user_prompt})
        assert response_model is IdeaOptions
        return self.result


# ---------------------------------------------------------------- agent blocks


@pytest.mark.asyncio
async def test_raw_idea_block_and_agent_name():
    fake = FakeLLM(_make_options(2))
    await develop_idea(idea="a cat learns to skateboard", client=fake)
    call = fake.calls[0]
    assert call["agent"] == "idea_agent"
    assert "Raw idea" in call["user_prompt"]
    assert "a cat learns to skateboard" in call["user_prompt"]


@pytest.mark.asyncio
async def test_characters_block_in_prompt():
    fake = FakeLLM(_make_options(2))
    await develop_idea(
        idea="a meadow story",
        characters=[{"name": "Grace", "appearance": "girl in pink dress"}],
        client=fake,
    )
    prompt = fake.calls[0]["user_prompt"]
    assert "Existing characters (cast them by their EXACT names)" in prompt
    assert "Grace" in prompt
    assert "girl in pink dress" in prompt


@pytest.mark.asyncio
async def test_style_block_in_prompt():
    fake = FakeLLM(_make_options(2))
    await develop_idea(
        idea="a meadow story",
        style={"audience": "kids 4-7", "tone": "warm"},
        client=fake,
    )
    prompt = fake.calls[0]["user_prompt"]
    assert "Project style guide" in prompt
    assert "kids 4-7" in prompt


@pytest.mark.asyncio
async def test_optional_blocks_omitted_when_none():
    fake = FakeLLM(_make_options(2))
    await develop_idea(idea="a meadow story", client=fake)
    prompt = fake.calls[0]["user_prompt"]
    assert "Existing characters" not in prompt
    assert "Project style guide" not in prompt


# ------------------------------------------------------------- prompt content


def test_idea_agent_prompt_demands_two_and_recommendation():
    from app.llm.prompts import PROMPTS

    prompt = PROMPTS["idea_agent"]
    assert "EXACTLY TWO" in prompt
    assert "RECOMMEND" in prompt
    assert "「」" in prompt


def test_idea_agent_skill_registered():
    from app.llm.skills import get_skill

    skill = get_skill("idea_agent")
    assert skill is not None
    assert skill.temperature == 0.8


# ------------------------------------------------- deterministic enforcement


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.mark.asyncio
async def test_service_truncates_to_two_options(session, monkeypatch):
    from app.services import scene_service

    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM(_make_options(3)))
    result = await scene_service.develop_script_idea(session, idea="a cat story")
    assert len(result.options) == 2
    assert result.options[0].title == "Concept 1"
    assert result.options[1].title == "Concept 2"


@pytest.mark.asyncio
async def test_service_rejects_zero_options(session, monkeypatch):
    from app.services import scene_service

    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM(_make_options(0)))
    with pytest.raises(ValidationFailedError):
        await scene_service.develop_script_idea(session, idea="a cat story")


@pytest.mark.asyncio
async def test_service_clamps_recommended_index_for_single_option(session, monkeypatch):
    from app.services import scene_service

    monkeypatch.setattr(
        "app.agents.base.get_llm_client",
        lambda: FakeLLM(_make_options(1, recommended_index=1)),
    )
    result = await scene_service.develop_script_idea(session, idea="a cat story")
    assert len(result.options) == 1
    assert result.recommended_index == 0


@pytest.mark.asyncio
async def test_service_passes_characters_and_style(session, monkeypatch):
    from app.models import Character
    from app.services import scene_service

    session.add(Character(id="char_g", name="Grace", appearance="girl in pink dress"))
    session.commit()

    fake = FakeLLM(_make_options(2))
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: fake)
    await scene_service.develop_script_idea(session, idea="a meadow story")
    prompt = fake.calls[0]["user_prompt"]
    assert "Grace" in prompt
