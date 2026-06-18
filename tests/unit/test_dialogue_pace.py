"""Dialogue pacing: size each spoken line to fill its shot at ~170-200 WPM."""

from __future__ import annotations

from app.config import Settings
from app.services.dialogue import line_inside_quotes, pace_bounds, pace_check, spoken_units


def _s(**kw) -> Settings:
    return Settings(_env_file=None, MINIMAX_API_KEY="mk", ATLASCLOUD_API_KEY="ak", **kw)


def test_spoken_units_english_counts_words():
    assert spoken_units("hello there my friend") == ("en", 4)


def test_spoken_units_chinese_counts_characters():
    # Punctuation/spaces don't count; only CJK characters.
    assert spoken_units("你好，世界！") == ("zh", 4)


def test_line_inside_quotes():
    assert line_inside_quotes("@Grace says, 「Watch your dog!」") == "Watch your dog!"
    assert line_inside_quotes("no dialogue here") is None


def test_pace_bounds_english_scales_with_duration():
    s = _s()
    # 170-200 wpm -> floor(min) .. ceil(max)
    assert pace_bounds(3, "en", s) == (8, 10)   # floor(8.5)..ceil(10)
    assert pace_bounds(6, "en", s) == (17, 20)


def test_pace_bounds_chinese_uses_chars_per_second():
    s = _s()
    assert pace_bounds(3, "zh", s) == (13, 17)  # floor(4.5*3)..ceil(5.5*3)


def test_pace_check_flags_too_short():
    s = _s()
    v = pace_check("「Hi!」", 5, s)
    assert v["kind"] == "en" and v["verdict"] == "too_short"
    assert v["lo"] <= 14 <= v["hi"] + 5  # sanity: target ~14-17 words for 5s


def test_pace_check_ok_when_filling():
    s = _s()
    line = "「" + " ".join(["word"] * 17) + "」"  # ~17 words for a 6s shot
    v = pace_check(line, 6, s)
    assert v["verdict"] == "ok"


def test_pace_check_flags_too_long():
    s = _s()
    line = "「" + " ".join(["word"] * 40) + "」"
    v = pace_check(line, 5, s)
    assert v["verdict"] == "too_long"


def test_pace_check_no_dialogue_returns_none_verdict():
    s = _s()
    assert pace_check("no quotes", 5, s)["verdict"] == "none"


# ---------------------------------------------------- enforcement pass
import pytest  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.models  # noqa: E402,F401
from app.models import Scene, Shot  # noqa: E402
from app.schemas import ShotRefinement  # noqa: E402
from app.services import scene_service  # noqa: E402


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


async def test_enforce_pace_rewrites_too_short_line(session, monkeypatch):
    scene = Scene(title="t", summary="a sunny meadow lesson", duration=6)
    session.add(scene)
    session.commit()
    shot = Shot(scene_id=scene.id, shot_order=1, prompt="@A says 「Hi!」",
                duration=6, camera="", movement="")
    session.add(shot)
    session.commit()

    paced = "@A says 「" + " ".join(["word"] * 18) + "」"  # fills a 6s shot

    async def fake_refine(*, shot, scene_summary, instruction, **kw):
        assert "too short" in instruction  # got the right correction
        return ShotRefinement(prompt=paced)

    monkeypatch.setattr(scene_service.refine_agent, "refine_shot", fake_refine)
    await scene_service._enforce_dialogue_pace(session, scene, [shot])
    session.refresh(shot)
    assert shot.prompt == paced


async def test_enforce_pace_leaves_ok_line_untouched(session, monkeypatch):
    scene = Scene(title="t", summary="s", duration=6)
    session.add(scene)
    session.commit()
    ok_line = "@A says 「" + " ".join(["word"] * 18) + "」"
    shot = Shot(scene_id=scene.id, shot_order=1, prompt=ok_line,
                duration=6, camera="", movement="")
    session.add(shot)
    session.commit()

    called = {"n": 0}

    async def fake_refine(**kw):
        called["n"] += 1
        return ShotRefinement(prompt="changed")

    monkeypatch.setattr(scene_service.refine_agent, "refine_shot", fake_refine)
    await scene_service._enforce_dialogue_pace(session, scene, [shot])
    session.refresh(shot)
    assert called["n"] == 0 and shot.prompt == ok_line  # in-pace, no refine call
