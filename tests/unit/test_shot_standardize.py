"""Standardize shots to short, snappy beats that fit Kling's 3-15s clip limit."""

from __future__ import annotations

from app.config import Settings
from app.schemas import ShotSpec
from app.services.scene_service import standardize_shots


def _s(**kw) -> Settings:
    return Settings(_env_file=None, MINIMAX_API_KEY="mk", ATLASCLOUD_API_KEY="ak", **kw)


def _shots(durations: list[int]) -> list[ShotSpec]:
    return [
        ShotSpec(shot_id=f"sh{i}", duration=d, prompt=f"beat {i} 「hi」",
                 camera="mid", movement="static")
        for i, d in enumerate(durations)
    ]


def test_clamps_each_shot_to_2_4_seconds():
    out = standardize_shots(_shots([1, 5, 3, 8]), _s())
    assert [s.duration for s in out] == [2, 4, 3, 4]  # clamped into [2,4]


def test_caps_shot_count_and_total_under_15():
    # 10 shots of 4s = 40s -> trimmed to <=5 shots AND <=15s total.
    out = standardize_shots(_shots([4] * 10), _s())
    assert len(out) <= 5
    assert sum(s.duration for s in out) <= 15
    assert sum(s.duration for s in out) >= 3  # still rendarable (Kling min)


def test_keeps_a_short_valid_scene_unchanged():
    out = standardize_shots(_shots([3, 3, 4]), _s())
    assert [s.duration for s in out] == [3, 3, 4]


def test_bumps_a_too_short_single_shot_to_min_renderable():
    out = standardize_shots(_shots([2]), _s())
    assert sum(s.duration for s in out) >= 3  # one 2s shot would be < Kling min
