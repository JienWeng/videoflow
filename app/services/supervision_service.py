"""Supervision policy — the critic that ACTS on a QA verdict.

Today QA runs and is ignored; this maps a `QAResult` to a concrete decision:

- accept     — good enough; select it and finish.
- revise     — one fixable dimension is weak; apply a TARGETED patch (cheap-ish).
- regenerate — broadly wrong; rebuild the spec from scratch.
- escalate   — STOP spending: keep the best output and surface to the user.

The escalate gates (attempt cap, budget, non-improvement) override any decision
that would cost another render. This is what makes the full-auto loop terminate.
The pure `decide()` is deterministic and unit-tested; `decide_for_output()` wraps
it with the DB lookups (QA result, budget, previous score).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session

from app.config import Settings, get_settings
from app.models import RenderOutput
from app.schemas.qa_schema import DimensionName, QAResult

Decision = Literal["accept", "revise", "regenerate", "escalate"]


@dataclass(frozen=True)
class Thresholds:
    accept_score: int
    min_dimension: int
    revise_floor: int
    max_attempts: int
    min_improvement: int


@dataclass(frozen=True)
class SupervisionVerdict:
    decision: Decision
    reason: str
    target_dimension: DimensionName | None = None


_KEYS = (
    "qa_accept_score",
    "qa_min_dimension",
    "qa_revise_floor",
    "qa_max_attempts",
    "qa_min_improvement",
)


def thresholds(
    session: Session,
    *,
    project_id: str | None = None,
    settings: Settings | None = None,
) -> Thresholds:
    from app.services import settings_service

    settings = settings or get_settings()
    vals = {
        k: int(
            settings_service.resolve(
                session, k, default=getattr(settings, k),
                project_id=project_id, settings=settings,
            )
        )
        for k in _KEYS
    }
    return Thresholds(
        accept_score=vals["qa_accept_score"],
        min_dimension=vals["qa_min_dimension"],
        revise_floor=vals["qa_revise_floor"],
        max_attempts=vals["qa_max_attempts"],
        min_improvement=vals["qa_min_improvement"],
    )


def _classify(qa: QAResult, th: Thresholds) -> tuple[Decision, DimensionName | None]:
    """Base decision from the QA scores alone (before the stop gates)."""
    below = [d for d in qa.dimensions if d.score < th.min_dimension]
    all_dims_ok = not below  # no reported dimension is weak (or none reported)
    target = qa.worst_dimension or (below[0].name if below else None)

    if qa.score >= th.accept_score and all_dims_ok:
        return "accept", None
    if qa.recommendation == "regenerate" or qa.score < th.revise_floor or len(below) >= 2:
        return "regenerate", target
    return "revise", target


def decide(
    qa: QAResult,
    *,
    attempt: int,
    prev_score: int | None,
    can_afford_video: bool,
    th: Thresholds,
) -> SupervisionVerdict:
    """Pure policy. `attempt` is the 1-based count of renders produced so far
    (the one being judged included). The escalate gates only block decisions that
    would cost ANOTHER render — a good result still accepts at the cap."""
    base, target = _classify(qa, th)
    if base == "accept":
        return SupervisionVerdict("accept", "meets quality bar", None)

    # base is revise/regenerate -> would cost another render. Apply stop gates.
    if attempt >= th.max_attempts:
        return SupervisionVerdict(
            "escalate", f"attempt cap reached ({attempt}/{th.max_attempts})", target
        )
    if not can_afford_video:
        return SupervisionVerdict("escalate", "budget exhausted", target)
    if prev_score is not None and (qa.score - prev_score) < th.min_improvement:
        return SupervisionVerdict(
            "escalate",
            f"no improvement (score {prev_score}->{qa.score})",
            target,
        )
    return SupervisionVerdict(base, f"{base}: weakest = {target or 'overall'}", target)


def decide_for_output(
    session: Session,
    output: RenderOutput,
    *,
    attempt: int,
    prev_score: int | None = None,
    can_afford_video: bool = True,
    project_id: str | None = None,
    settings: Settings | None = None,
) -> SupervisionVerdict:
    """Wrapper: read the QA result off the output and apply the policy. When no QA
    is available (it runs best-effort), accept rather than burn money guessing."""
    if not output.qa_json:
        return SupervisionVerdict("accept", "no QA available", None)
    qa = QAResult.model_validate(output.qa_json)
    th = thresholds(session, project_id=project_id, settings=settings)
    return decide(
        qa,
        attempt=attempt,
        prev_score=prev_score,
        can_afford_video=can_afford_video,
        th=th,
    )
