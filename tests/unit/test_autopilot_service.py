"""Phase 3-4: the autonomous director loop — deterministic core.

The LLM director is stubbed (so the loop uses the default action each step) and
the heavy stage functions are stubbed to mutate a real minimal DB, so the REAL
state-detection drives progression. Renders are resolved by calling
on_render_terminal directly (no background tasks)."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.config import Settings
from app.models import (
    Asset, RenderJob, RenderOutput, RenderStatus, Scene, Script, Shot, WorkflowStep,
)
from app.models.workflow_run import TERMINAL_STATUSES
from app.services import autopilot_service, cost_service


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    # The loop opens its own sessions off the module-level engine — point it here
    # via monkeypatch so it's restored after the test (no global leak).
    monkeypatch.setattr("app.database.engine", engine, raising=False)
    monkeypatch.setattr(autopilot_service, "engine", engine, raising=False)
    with Session(engine) as s:
        yield s


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, MINIMAX_API_KEY="mk", ATLASCLOUD_API_KEY="ak", **kw)


def _install_stubs(monkeypatch, *, qa_json):
    """Stub director (-> default actions) and stage fns (-> mutate the DB)."""
    from app.services import (
        caption_service, render_service, scene_service, storyboard_service,
    )

    async def fake_director(state):
        return None  # force the deterministic default action

    monkeypatch.setattr(autopilot_service, "_call_director", fake_director)
    # No background tasks in tests — drive the loop manually.
    monkeypatch.setattr(autopilot_service, "_spawn", lambda *a, **k: None)
    monkeypatch.setattr(autopilot_service, "_spawn_coro", lambda *a, **k: None)

    async def fake_create_script(session, *, idea, target_duration=None, scene_count=1):
        script = Script(title="t", summary="s")
        session.add(script)
        session.commit()
        session.refresh(script)
        scene = Scene(script_id=script.id, title="t", summary="s", duration=5)
        session.add(scene)
        session.commit()
        return script, None

    async def fake_expand(session, scene_id, character_ids=None):
        scene = session.get(Scene, scene_id)
        scene.scene_json = {"expanded": True}
        session.add(scene)
        session.commit()
        return scene

    async def fake_shots(session, scene_id, auto_assets=True):
        shot = Shot(scene_id=scene_id, shot_order=1, prompt="A says 「hi」", duration=5)
        session.add(shot)
        session.commit()
        return [shot]

    async def fake_storyboard(session, scene_id, **kw):
        a = Asset(type="storyboard", name="sb", file_path="/x.png",
                  metadata_json={"scene_id": scene_id})
        session.add(a)
        session.commit()
        return a

    def fake_latest_sb(session, scene_id):
        for a in session.exec(select(Asset).where(Asset.type == "storyboard")).all():
            if (a.metadata_json or {}).get("scene_id") == scene_id:
                return a
        return None

    async def fake_render_scene(session, scene_id):
        job = RenderJob(scene_id=scene_id, status=RenderStatus.pending)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    async def fake_retry(session, output_id):
        out = session.get(RenderOutput, output_id)
        job = RenderJob(scene_id=session.get(RenderJob, out.render_job_id).scene_id,
                        status=RenderStatus.pending)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    async def fake_caption(session, output_id, **kw):
        out = session.get(RenderOutput, output_id)
        out.captioned_path = "/c.mp4"
        session.add(out)
        session.commit()
        return out

    monkeypatch.setattr(scene_service, "create_script", fake_create_script)
    monkeypatch.setattr(scene_service, "expand_scene", fake_expand)
    monkeypatch.setattr(scene_service, "create_shots", fake_shots)
    monkeypatch.setattr(storyboard_service, "generate_storyboard_for_scene", fake_storyboard)
    monkeypatch.setattr(storyboard_service, "latest_storyboard_for_scene", fake_latest_sb)
    monkeypatch.setattr(render_service, "render_scene", fake_render_scene)
    monkeypatch.setattr(render_service, "retry_output", fake_retry)
    monkeypatch.setattr(caption_service, "caption_output", fake_caption)
    return qa_json


async def _drive(session, run_id, qa_json, *, max_steps=40):
    """Run the loop manually, injecting render completions when it parks."""
    from app.models.workflow_run import WorkflowRun
    for _ in range(max_steps):
        cont = await autopilot_service._advance_one(run_id)
        run = session.get(WorkflowRun, run_id)
        if run is not None:
            session.refresh(run)
        if run.status in TERMINAL_STATUSES:
            return run
        if run.status == "awaiting_render":
            job = session.get(RenderJob, run.current_job_id)
            out = RenderOutput(
                render_job_id=job.id, video_path="/v.mp4",
                score=qa_json["score"], qa_json=qa_json,
            )
            session.add(out)
            job.status = RenderStatus.succeeded
            session.add(job)
            session.commit()
            await autopilot_service.on_render_terminal(job.id)
        elif not cont:
            return run
    raise AssertionError("loop did not terminate")


ACCEPT_QA = {"score": 8, "passed": True, "issues": [], "recommendation": "accept",
             "dimensions": [], "worst_dimension": None}
BAD_QA = {"score": 3, "passed": False, "issues": ["bad"], "recommendation": "regenerate",
          "dimensions": [], "worst_dimension": None}


async def test_full_run_reaches_done_and_captions(session, monkeypatch):
    _install_stubs(monkeypatch, qa_json=ACCEPT_QA)
    run = autopilot_service.create_run(session, idea="a cat learns to fly", settings=_settings())
    run = await _drive(session, run.id, ACCEPT_QA)

    assert run.status == "done"
    out = session.get(RenderOutput, run.current_output_id)
    assert out.captioned_path and out.selected
    actions = [s.action for s in autopilot_service.list_steps(session, run.id)]
    for expected in ("generate_script", "expand_scene", "generate_shots",
                     "generate_storyboard", "render_scene", "qa", "caption", "finish"):
        assert expected in actions, f"{expected} missing from {actions}"
    assert run.attempt == 1  # accepted on the first render


async def test_budget_exhaustion_stops_after_one_render(session, monkeypatch):
    _install_stubs(monkeypatch, qa_json=BAD_QA)
    # Budget covers one video (~150) + the cheap steps, but not a second video.
    run = autopilot_service.create_run(
        session, idea="x", config={"budget": 180}, settings=_settings()
    )
    run = await _drive(session, run.id, BAD_QA)

    assert run.status == "done"          # wound down gracefully, kept best
    assert run.attempt == 1              # never paid for a second render
    actions = [s.action for s in autopilot_service.list_steps(session, run.id)]
    assert "finish" in actions
    # The escalate verdict (budget) is what stopped it.
    assert run.last_verdict_json.get("decision") == "escalate"


def test_default_action_progression():
    da = autopilot_service._default_action
    base = dict(has_script=False, scene_expanded=False, has_shots=False,
                has_storyboard=False, attempt=0, current_output_id=None,
                captioned=False, verdict=None)
    assert da(base) == "generate_script"
    assert da({**base, "has_script": True}) == "expand_scene"
    assert da({**base, "has_script": True, "scene_expanded": True}) == "generate_shots"
    s = {**base, "has_script": True, "scene_expanded": True, "has_shots": True}
    assert da(s) == "generate_storyboard"
    assert da({**s, "has_storyboard": True}) == "render_scene"
    post = {**s, "has_storyboard": True, "attempt": 1, "current_output_id": "o1"}
    assert da({**post, "verdict": {"decision": "revise"}}) == "revise_render"
    assert da({**post, "verdict": {"decision": "regenerate"}}) == "regenerate_render"
    assert da({**post, "verdict": {"decision": "accept"}}) == "caption"
    assert da({**post, "verdict": {"decision": "accept"}, "captioned": True}) == "finish"


def test_is_valid_gates():
    iv = autopilot_service._is_valid
    base = dict(has_script=False, scene_expanded=False, has_shots=False,
                attempt=0, current_output_id=None)
    assert iv(base, "generate_script") is True
    assert iv(base, "render_scene") is False        # no shots
    assert iv(base, "caption") is False             # no output
    assert iv({**base, "has_shots": True}, "render_scene") is True
    assert iv({**base, "attempt": 1}, "revise_render") is True
