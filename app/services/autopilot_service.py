"""Autonomous director — the agentic loop that turns one idea into one finished,
captioned video, supervising quality and spend.

Design: an LLM director chooses the next action each turn (`director_agent`), but
deterministic guardrails wrap it — the director PROPOSES, the governor DISPOSES:
- every action is validated against the run state; an illegal choice falls back to
  the obvious next step;
- the budget governor (`cost_service`) and the supervision policy
  (`supervision_service`) can force the run to stop and keep the best output —
  autonomy never overrides the spend cap.

The loop is state-driven off the durable `WorkflowRun` row, so a restart resumes:
`run_autopilot` reads the row, runs one step, persists, repeats. It PARKS at
status='awaiting_render' while a Kling job is in flight; `poll_service` calls
`notify_render_terminal` on completion, which computes the QA verdict and
re-spawns the loop. Renders already resume via `worker.reconcile_pending`, so the
callback path is also the resume path.
"""

from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session, select

from app import database
from app.config import Settings, get_settings
from app.models import RenderJob, RenderOutput, RenderStatus, Scene
from app.models.base import utcnow
from app.models.workflow_run import TERMINAL_STATUSES, WorkflowRun
from app.models.workflow_step import WorkflowStep
from app.schemas.director_schema import DirectorDecision
from app.services import (
    cost_service,
    event_bus,
    supervision_service,
)

logger = logging.getLogger("videoflow.autopilot")

# Tracked background tasks (a strong ref so they aren't GC'd mid-flight).
_live_tasks: set[asyncio.Task] = set()

_RENDER_ACTIONS = {"render_scene", "revise_render", "regenerate_render"}

# Hard backstop on total director steps per run — guarantees termination even if
# a stage never advances state (e.g. shot generation keeps returning empty) so a
# cheap text-only loop can't spin forever. A normal run is ~8-12 steps.
MAX_AUTOPILOT_STEPS = 50


class BudgetError(Exception):
    """Raised when the next expensive step can't be afforded."""


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def create_run(
    session: Session,
    *,
    idea: str,
    config: dict | None = None,
    project_id: str | None = None,
    settings: Settings | None = None,
) -> WorkflowRun:
    """Create a run row + open its budget (does NOT spawn the loop)."""
    settings = settings or get_settings()
    config = config or {}
    run = WorkflowRun(idea=idea, project_id=project_id, config_json=config)
    session.add(run)
    session.commit()
    session.refresh(run)
    cost_service.open_run(
        session,
        project_id=project_id,
        workflow_run_id=run.id,
        limit_units=config.get("budget"),
        settings=settings,
    )
    _emit(run)
    return run


def start_run(
    session: Session,
    *,
    idea: str,
    config: dict | None = None,
    project_id: str | None = None,
) -> WorkflowRun:
    """Create a run and spawn the autonomous loop."""
    run = create_run(session, idea=idea, config=config, project_id=project_id)
    _spawn(run.id)
    return run


def cancel_run(session: Session, run_id: str) -> WorkflowRun:
    run = session.get(WorkflowRun, run_id)
    if run is None:
        from app.errors import NotFoundError

        raise NotFoundError(f"workflow run {run_id} not found")
    if run.status not in TERMINAL_STATUSES:
        _finalize(session, run, "cancelled", "cancelled by user")
    return run


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
async def run_autopilot(run_id: str) -> None:
    """Advance the run until it parks (awaiting_render) or reaches a terminal."""
    try:
        while await _advance_one(run_id):
            pass
    except Exception:
        logger.exception("autopilot loop crashed for run %s", run_id)


async def _advance_one(run_id: str) -> bool:
    """One director step in its own session. Returns True to keep looping."""
    with Session(database.engine) as session:
        run = session.get(WorkflowRun, run_id)
        if run is None or run.status in TERMINAL_STATUSES:
            return False
        if run.status in ("awaiting_render", "awaiting_approval", "judging"):
            return False  # parked / a render verdict is being computed

        # Hard backstop: too many steps means a stage isn't advancing — stop.
        if _step_count(session, run_id) >= MAX_AUTOPILOT_STEPS:
            await _wind_down(session, run, "step limit reached")
            return False

        # Hard guardrail: a 'escalate' verdict means stop spending — wind down.
        verdict = run.last_verdict_json or {}
        if verdict.get("decision") == "escalate":
            await _wind_down(session, run, verdict.get("reason", "stopped"))
            return False

        state = build_state(session, run)
        decision = await _choose_action(session, run, state)
        _charge(session, run, "text")  # the director's own decision call

        try:
            summary = await _dispatch(session, run, decision.action)
        except BudgetError as exc:
            _record_step(session, run, decision.action, decision.rationale, f"budget: {exc}")
            await _wind_down(session, run, "budget exhausted")
            return False
        except Exception as exc:  # noqa: BLE001 — one bad step shouldn't hang the run
            logger.exception("autopilot step %s failed for run %s", decision.action, run_id)
            _record_step(session, run, decision.action, decision.rationale, f"error: {exc}")
            _finalize(session, run, "failed", str(exc))
            return False

        _record_step(session, run, decision.action, decision.rationale, summary)
        if decision.action in _RENDER_ACTIONS:
            return False  # parked on the render (status set in _dispatch)
        if decision.action in ("finish", "abort"):
            return False  # finalized in _dispatch
        return True


async def _choose_action(
    session: Session, run: WorkflowRun, state: dict
) -> DirectorDecision:
    """Ask the director; validate against the state; fall back to the obvious
    next step on an illegal or failed choice (agentic where valid, safe otherwise)."""
    decision: DirectorDecision | None = None
    try:
        decision = await _call_director(state)
    except Exception:
        logger.exception("director agent failed for run %s; using default action", run.id)
    if decision is None or not _is_valid(state, decision.action):
        action = _default_action(state)
        why = "invalid director choice; " if decision else "director unavailable; "
        return DirectorDecision(rationale=f"(auto) {why}default: {action}", action=action)
    return decision


async def _call_director(state: dict) -> DirectorDecision:
    # Seam for tests to stub the LLM.
    from app.agents import director_agent

    return await director_agent.decide_next(state=state)


# --------------------------------------------------------------------------- #
# State + decision helpers (pure-ish)
# --------------------------------------------------------------------------- #
def build_state(session: Session, run: WorkflowRun) -> dict:
    from app.services import scene_service, storyboard_service

    scene = session.get(Scene, run.scene_id) if run.scene_id else None
    shots = scene_service.list_shots(session, run.scene_id) if run.scene_id else []
    storyboard = (
        storyboard_service.latest_storyboard_for_scene(session, run.scene_id)
        if run.scene_id
        else None
    )
    output = (
        session.get(RenderOutput, run.current_output_id)
        if run.current_output_id
        else None
    )
    budget = cost_service.budget_for_run(session, workflow_run_id=run.id)
    remaining = cost_service.remaining(session, budget.id) if budget else None
    th = supervision_service.thresholds(session, project_id=run.project_id)
    return {
        "idea": run.idea,
        "has_script": bool(run.script_id),
        "scene_id": run.scene_id,
        "scene_expanded": bool(scene and scene.scene_json),
        "has_shots": len(shots) > 0,
        "shot_count": len(shots),
        "has_storyboard": storyboard is not None,
        "attempt": run.attempt,
        "max_attempts": th.max_attempts,
        "current_output_id": run.current_output_id,
        "captioned": bool(output and output.captioned_path),
        "best_score": run.best_score,
        "verdict": run.last_verdict_json or None,
        "budget_remaining": remaining,
        "available_actions": _legal_actions(
            {  # minimal state for legality
                "has_script": bool(run.script_id),
                "scene_expanded": bool(scene and scene.scene_json),
                "has_shots": len(shots) > 0,
                "attempt": run.attempt,
                "current_output_id": run.current_output_id,
            }
        ),
    }


def _legal_actions(state: dict) -> list[str]:
    return [a for a in (
        "generate_script", "expand_scene", "generate_shots", "generate_storyboard",
        "render_scene", "revise_render", "regenerate_render", "caption", "finish",
        "abort",
    ) if _is_valid(state, a)]


def _is_valid(state: dict, action: str) -> bool:
    legal = {
        "generate_script": not state["has_script"],
        "expand_scene": state["has_script"] and not state["scene_expanded"],
        "generate_shots": state["scene_expanded"] and not state["has_shots"],
        "generate_storyboard": state["has_shots"],
        "render_scene": state["has_shots"],
        "revise_render": state["attempt"] > 0,
        "regenerate_render": state["attempt"] > 0,
        "caption": bool(state["current_output_id"]),
        "finish": True,
        "abort": True,
    }
    return bool(legal.get(action, False))


def _default_action(state: dict) -> str:
    if not state["has_script"]:
        return "generate_script"
    if not state["scene_expanded"]:
        return "expand_scene"
    if not state["has_shots"]:
        return "generate_shots"
    if not state["has_storyboard"]:
        return "generate_storyboard"
    if state["attempt"] == 0:
        return "render_scene"
    verdict = state.get("verdict") or {}
    decision = verdict.get("decision")
    if decision == "revise":
        return "revise_render"
    if decision == "regenerate":
        return "regenerate_render"
    if decision == "escalate":
        return "finish"
    # accept / unknown
    return "caption" if not state["captioned"] else "finish"


# --------------------------------------------------------------------------- #
# Action dispatch
# --------------------------------------------------------------------------- #
async def _dispatch(session: Session, run: WorkflowRun, action: str) -> str:
    from app.services import (
        caption_service,
        render_service,
        scene_service,
        storyboard_service,
    )

    cfg = run.config_json or {}
    aspect = cfg.get("aspect_ratio")
    language = cfg.get("dialogue_language")
    style_extra = cfg.get("style") or None

    if action == "generate_script":
        scene_count = cfg.get("scene_count", 1)
        script, _ = await scene_service.create_script(
            session, idea=run.idea, scene_count=scene_count
        )
        run.script_id = script.id
        first = session.exec(
            select(Scene).where(Scene.script_id == script.id).order_by(Scene.created_at)  # type: ignore[attr-defined]
        ).first()
        if first is None:
            raise RuntimeError("script produced no scenes")
        if aspect:  # per-run orientation
            first.aspect_ratio = aspect
            session.add(first)
        run.scene_id = first.id
        _charge(session, run, "text")
        _persist(session, run)
        return f"script {script.id}; scene {first.id}"

    if action == "expand_scene":
        await scene_service.expand_scene(session, run.scene_id, style_extra=style_extra)
        if aspect:  # re-assert orientation (the scene director may have changed it)
            scene = session.get(Scene, run.scene_id)
            scene.aspect_ratio = aspect
            session.add(scene)
            session.commit()
        _charge(session, run, "text")
        return f"expanded scene {run.scene_id}"

    if action == "generate_shots":
        shots = await scene_service.create_shots(
            session, run.scene_id, auto_assets=True,
            dialogue_language=language, style_extra=style_extra,
        )
        _charge(session, run, "text")
        return f"{len(shots)} shots"

    if action == "generate_storyboard":
        sb = await storyboard_service.generate_storyboard_for_scene(session, run.scene_id)
        _charge(session, run, "image")
        return f"storyboard {sb.id}"

    if action in ("render_scene", "regenerate_render"):
        _require_video_budget(session, run)
        _charge(session, run, "video")
        job = await render_service.render_scene(
            session, run.scene_id,
            dialogue_language=language, style_extra=style_extra,
        )
        _park_on_render(session, run, job.id)
        return f"submitted render {job.id} (attempt {run.attempt})"

    if action == "revise_render":
        _require_video_budget(session, run)
        if not run.current_output_id:
            raise RuntimeError("no output to revise")
        _charge(session, run, "video")
        job = await render_service.revise_output(session, run.current_output_id)
        _park_on_render(session, run, job.id)
        return f"submitted targeted re-render {job.id} (attempt {run.attempt})"

    if action == "caption":
        oid = run.current_output_id or run.best_output_id
        if not oid:
            raise RuntimeError("no output to caption")
        await caption_service.caption_output(session, oid)
        run.current_output_id = oid
        _charge(session, run, "text")
        _persist(session, run)
        return f"captioned {oid}"

    if action == "finish":
        await _wind_down(session, run, "director finished")
        return "finished"

    if action == "abort":
        _finalize(session, run, "failed", "director aborted")
        return "aborted"

    raise RuntimeError(f"unknown action '{action}'")


def _park_on_render(session: Session, run: WorkflowRun, job_id: str) -> None:
    run.current_job_id = job_id
    run.attempt += 1
    run.status = "awaiting_render"
    _persist(session, run)


def _require_video_budget(session: Session, run: WorkflowRun) -> None:
    budget = cost_service.budget_for_run(session, workflow_run_id=run.id)
    if budget is None:
        return
    est = cost_service.estimate_video(session, _scene_duration(session, run.scene_id))
    if not cost_service.can_afford(session, budget.id, est):
        raise BudgetError(f"cannot afford another render (~{est} units)")


# --------------------------------------------------------------------------- #
# Render-terminal callback (resume point)
# --------------------------------------------------------------------------- #
def notify_render_terminal(job_id: str) -> None:
    """Sync hook poll_service calls when a render reaches a terminal state.
    Schedules the async handler so the worker returns promptly."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop (e.g. a sync test) — reconcile_runs covers this on restart
    _spawn_coro(on_render_terminal(job_id))


async def on_render_terminal(job_id: str) -> None:
    """A render parked by this loop finished: record the QA verdict, update the
    best take, un-park, and re-spawn the loop so the director decides next."""
    with Session(database.engine) as session:
        run = session.exec(
            select(WorkflowRun).where(
                WorkflowRun.current_job_id == job_id,
                WorkflowRun.status == "awaiting_render",
            )
        ).first()
        if run is None:
            return
        # CLAIM the run atomically: flip out of 'awaiting_render' before any
        # await, so a concurrent/duplicate callback (or a startup reconcile
        # double-spawn) finds nothing to process and can't double-compute the
        # verdict. The select->set->commit has no await between, so within the
        # asyncio loop it's atomic. On error below we re-arm so it's retried.
        run.status = "judging"
        _persist(session, run)
        try:
            await _judge_render(session, run, job_id)
            run.status = "running"
            run.current_job_id = None
            _persist(session, run)
        except Exception:
            logger.exception("on_render_terminal failed for job %s", job_id)
            # Treat as a failed attempt (counts toward the cap) so the run keeps
            # moving and the governor can stop it — never leave it stuck.
            run.last_verdict_json = {
                "decision": "regenerate", "reason": "judge error", "score": 0,
            }
            run.status = "running"
            run.current_job_id = None
            _persist(session, run)
    _spawn(run_id=run.id)


async def _judge_render(session: Session, run: WorkflowRun, job_id: str) -> None:
    """Compute the QA verdict for a finished render and record it on the run.
    Does NOT change run.status / spawn — the on_render_terminal wrapper owns the
    claim/release so the verdict computation can't run twice for one job."""
    from app.services import render_service

    job = session.get(RenderJob, job_id)
    outputs = render_service.job_outputs(session, job_id)
    output = next((o for o in reversed(outputs) if o.video_path), None)

    if output is None or (job and job.status == RenderStatus.failed):
        run.last_verdict_json = {
            "decision": "regenerate", "reason": "render failed", "score": 0,
        }
        _record_step(session, run, "qa", "render failed", "no usable output")
        return
    run.current_output_id = output.id
    score = output.score or 0
    prev_best = run.best_score
    if run.best_score is None or score > run.best_score:
        run.best_score = score
        run.best_output_id = output.id
    budget = cost_service.budget_for_run(session, workflow_run_id=run.id)
    if budget is not None:
        cost_service.charge(session, budget.id, "vision")  # QA cost
    est = cost_service.estimate_video(session, _scene_duration(session, run.scene_id))
    can_afford = budget is not None and cost_service.can_afford(session, budget.id, est)
    verdict = supervision_service.decide_for_output(
        session,
        output,
        attempt=run.attempt,
        prev_score=prev_best if run.attempt > 1 else None,
        can_afford_video=can_afford,
        project_id=run.project_id,
    )
    run.last_verdict_json = {
        "decision": verdict.decision,
        "reason": verdict.reason,
        "target_dimension": verdict.target_dimension,
        "score": score,
    }
    _record_step(
        session, run, "qa", verdict.reason, f"score {score} -> {verdict.decision}"
    )


# --------------------------------------------------------------------------- #
# Finalisation
# --------------------------------------------------------------------------- #
async def _wind_down(session: Session, run: WorkflowRun, reason: str) -> None:
    """Stop: keep (and caption) the best output, then finish — or fail if none."""
    from app.services import caption_service, render_service

    oid = run.best_output_id or run.current_output_id
    if not oid:
        _finalize(session, run, "failed", reason or "no output produced")
        _record_step(session, run, "abort", reason, "no output produced")
        return
    output = session.get(RenderOutput, oid)
    if output and not output.captioned_path:
        try:
            await caption_service.caption_output(session, oid)
            _charge(session, run, "text")
        except Exception:
            logger.exception("wind-down captioning failed for output %s", oid)
    try:
        render_service.select_output(session, oid)
    except Exception:
        logger.exception("wind-down select_output failed for %s", oid)
    run.current_output_id = oid
    _finalize(session, run, "done", reason)
    _record_step(session, run, "finish", reason, f"accepted best output {oid}")


def _finalize(session: Session, run: WorkflowRun, status: str, reason: str) -> None:
    run.status = status
    run.stage = status
    if status in ("failed", "cancelled"):
        run.last_error = reason
    _persist(session, run)


# --------------------------------------------------------------------------- #
# Resume on restart
# --------------------------------------------------------------------------- #
def reconcile_runs() -> None:
    """Re-attach to runs left in flight by a prior process. Call AFTER
    worker.reconcile_pending() so in-flight renders are already re-enqueued."""
    with Session(database.engine) as session:
        ids = [
            r.id for r in session.exec(
                select(WorkflowRun).where(
                    WorkflowRun.status.in_(  # type: ignore[attr-defined]
                        ["running", "awaiting_render", "judging"]
                    )
                )
            ).all()
        ]
        for run_id in ids:
            run = session.get(WorkflowRun, run_id)  # fresh read, no stale cache
            if run is None:
                continue
            # A run interrupted mid-verdict ('judging') is re-armed so the
            # terminal callback below re-processes it.
            if run.status == "judging":
                run.status = "awaiting_render"
                _persist(session, run)
            if run.status == "awaiting_render" and run.current_job_id:
                job = session.get(RenderJob, run.current_job_id)
                if job and job.status in (RenderStatus.succeeded, RenderStatus.failed):
                    _spawn_coro(on_render_terminal(run.current_job_id))
                # else: still pending/running — reconcile_pending re-enqueued it,
                # the terminal callback will fire; leave parked.
            elif run.status == "running":
                _spawn(run.id)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _scene_duration(session: Session, scene_id: str | None) -> int:
    from app.services import scene_service

    if not scene_id:
        return 5
    shots = scene_service.list_shots(session, scene_id)
    return sum(max(1, s.duration) for s in shots) or 5


def _charge(session: Session, run: WorkflowRun, kind: str) -> None:
    budget = cost_service.budget_for_run(session, workflow_run_id=run.id)
    if budget is None:
        return
    if kind == "video":
        units = cost_service.estimate_video(session, _scene_duration(session, run.scene_id))
        cost_service.charge(session, budget.id, units=units)
    else:
        cost_service.charge(session, budget.id, kind)


def _step_count(session: Session, run_id: str) -> int:
    return len(
        session.exec(select(WorkflowStep).where(WorkflowStep.run_id == run_id)).all()
    )


def _next_seq(session: Session, run_id: str) -> int:
    return _step_count(session, run_id) + 1


def _record_step(
    session: Session, run: WorkflowRun, action: str, rationale: str, result: str
) -> None:
    step = WorkflowStep(
        run_id=run.id,
        seq=_next_seq(session, run.id),
        action=action,
        rationale=rationale[:1000],
        result_summary=result[:1000],
    )
    session.add(step)
    run.stage = action
    _persist(session, run)
    _emit(run, action=action)


def _persist(session: Session, run: WorkflowRun) -> None:
    run.updated_at = utcnow()
    session.add(run)
    session.commit()
    session.refresh(run)


def _emit(run: WorkflowRun, *, action: str | None = None) -> None:
    try:
        event_bus.publish(
            {
                "workflow_id": run.id,
                "status": run.status,
                "stage": run.stage,
                "action": action,
            }
        )
    except Exception:
        pass


def _spawn(run_id: str) -> None:
    _spawn_coro(run_autopilot(run_id))


def _spawn_coro(coro) -> None:
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # No running loop (sync context) — caller handles via reconcile on restart.
        coro.close()
        return
    _live_tasks.add(task)
    task.add_done_callback(_live_tasks.discard)


def get_run(session: Session, run_id: str) -> WorkflowRun:
    from app.errors import NotFoundError

    run = session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError(f"workflow run {run_id} not found")
    return run


def list_steps(session: Session, run_id: str) -> list[WorkflowStep]:
    return list(
        session.exec(
            select(WorkflowStep)
            .where(WorkflowStep.run_id == run_id)
            .order_by(WorkflowStep.seq)  # type: ignore[attr-defined]
        ).all()
    )
