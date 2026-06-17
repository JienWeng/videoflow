"""Phase 2: supervision decision policy — maps a QAResult to accept/revise/
regenerate/escalate, with the hard stop gates (attempts, budget, non-improvement)
overriding any further spend."""

from __future__ import annotations

from app.schemas.qa_schema import DimensionScore, QAResult
from app.services.supervision_service import Thresholds, decide

TH = Thresholds(
    accept_score=7, min_dimension=3, revise_floor=4, max_attempts=2, min_improvement=1
)


def qa(score, rec="accept", dims=None, worst=None):
    return QAResult(
        score=score,
        passed=score >= 7,
        issues=[],
        recommendation=rec,
        dimensions=dims or [],
        worst_dimension=worst,
    )


def test_accept_when_score_high_and_dims_ok():
    v = decide(qa(8, dims=[DimensionScore(name="continuity", score=4)]),
               attempt=1, prev_score=None, can_afford_video=True, th=TH)
    assert v.decision == "accept"


def test_regenerate_when_score_below_floor():
    v = decide(qa(3, rec="regenerate"), attempt=1, prev_score=None,
               can_afford_video=True, th=TH)
    assert v.decision == "regenerate"


def test_revise_single_fixable_dimension():
    dims = [
        DimensionScore(name="character_consistency", score=2, evidence=["frame 3"]),
        DimensionScore(name="continuity", score=4),
    ]
    v = decide(qa(6, dims=dims, worst="character_consistency"),
               attempt=1, prev_score=None, can_afford_video=True, th=TH)
    assert v.decision == "revise"
    assert v.target_dimension == "character_consistency"


def test_regenerate_when_two_dimensions_fail():
    dims = [
        DimensionScore(name="character_consistency", score=2),
        DimensionScore(name="scene_match", score=2),
    ]
    v = decide(qa(5, dims=dims), attempt=1, prev_score=None, can_afford_video=True, th=TH)
    assert v.decision == "regenerate"


def test_accept_blocked_when_a_dimension_is_low_even_if_score_high():
    dims = [DimensionScore(name="character_consistency", score=2)]
    v = decide(qa(8, dims=dims, worst="character_consistency"),
               attempt=1, prev_score=None, can_afford_video=True, th=TH)
    assert v.decision == "revise"  # not accept


def test_escalate_when_attempts_exhausted():
    # A would-be regenerate at the attempt cap must stop instead.
    v = decide(qa(3, rec="regenerate"), attempt=2, prev_score=None,
               can_afford_video=True, th=TH)
    assert v.decision == "escalate"
    assert "attempt" in v.reason.lower()


def test_escalate_when_budget_exhausted():
    v = decide(qa(3, rec="regenerate"), attempt=1, prev_score=None,
               can_afford_video=False, th=TH)
    assert v.decision == "escalate"
    assert "budget" in v.reason.lower()


def test_escalate_on_non_improvement():
    # Under the attempt cap (3) but the score didn't improve over the previous
    # attempt -> stop early instead of spending another render.
    th3 = Thresholds(accept_score=7, min_dimension=3, revise_floor=4,
                     max_attempts=3, min_improvement=1)
    v = decide(qa(6, dims=[DimensionScore(name="continuity", score=2)]),
               attempt=2, prev_score=6, can_afford_video=True, th=th3)
    assert v.decision == "escalate"
    assert "improve" in v.reason.lower()


def test_accept_is_allowed_even_at_attempt_cap():
    # Stops only block FURTHER spend; a good result still accepts.
    v = decide(qa(9), attempt=2, prev_score=5, can_afford_video=False, th=TH)
    assert v.decision == "accept"
