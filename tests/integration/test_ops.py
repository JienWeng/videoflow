"""Background ops runner: ?background=true on long generations + /ops endpoints.

Reuses the scene-pipeline ctx fixture (fake LLM/Atlas providers, monkeypatched
app.database.engine, TestClient with running lifespan so asyncio tasks work).
"""

from __future__ import annotations

import time

from tests.integration.test_scene_pipeline import (  # noqa: F401  (ctx fixture)
    FakeAtlas,
    FakeLLM,
    ctx,
)


def _wait_op(client, op_id: str, timeout: float = 10.0) -> dict:
    """Poll GET /ops/{id} until the op leaves 'running' (bounded)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/ops/{op_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"op {op_id} still running after {timeout}s")


# ── storyboard ────────────────────────────────────────────────────────────────

def test_storyboard_background_returns_202_and_succeeds(ctx, monkeypatch):
    client, fake = ctx
    events: list[dict] = []
    monkeypatch.setattr(
        "app.services.event_bus.publish", lambda e: events.append(e)
    )

    resp = client.post("/scenes/scene_1/storyboard?background=true")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    op_id = body["op_id"]
    assert op_id.startswith("op_")
    assert body["status"] == "running"

    op = _wait_op(client, op_id)
    assert op["status"] == "succeeded", op
    assert op["kind"] == "storyboard"
    assert op["scene_id"] == "scene_1"
    assert op["error"] is None
    # result_json carries the storyboard asset summary (ids/paths, not rows).
    assert op["result_json"]["asset_id"].startswith("asset_")
    assert op["result_json"]["file_path"]

    # The asset actually exists and is the scene's storyboard.
    asset = client.get(f"/assets/{op['result_json']['asset_id']}")
    if asset.status_code == 200:  # assets API exposes GET by id
        assert asset.json()["type"] == "storyboard"
    # And the work actually hit the image provider.
    assert fake.image_payloads

    # Events: a running publish at start and a terminal publish on completion.
    op_events = [e for e in events if e.get("op_id") == op_id]
    statuses = [e["status"] for e in op_events]
    assert "running" in statuses
    assert statuses[-1] == "succeeded"
    assert all(e["kind"] == "storyboard" for e in op_events)
    assert all(e["scene_id"] == "scene_1" for e in op_events)


def test_storyboard_sync_path_unchanged(ctx):
    client, fake = ctx
    resp = client.post("/scenes/scene_1/storyboard")
    assert resp.status_code == 200, resp.text
    assert resp.json()["type"] == "storyboard"


def test_storyboard_background_failure_sets_failed(ctx, monkeypatch):
    client, fake = ctx

    async def boom(session, scene_id, **kw):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        "app.services.storyboard_service.generate_storyboard_for_scene", boom
    )
    resp = client.post("/scenes/scene_1/storyboard?background=true")
    assert resp.status_code == 202, resp.text  # never a 500
    op = _wait_op(client, resp.json()["op_id"])
    assert op["status"] == "failed"
    assert "provider exploded" in op["error"]
    assert op["result_json"] == {}


# ── scene asset generation ────────────────────────────────────────────────────

def test_assets_generate_background(ctx):
    client, fake = ctx
    resp = client.post(
        "/scenes/scene_1/assets/generate?background=true",
        json={"instruction": "need a red cup"},
    )
    assert resp.status_code == 202, resp.text
    op = _wait_op(client, resp.json()["op_id"])
    assert op["status"] == "succeeded", op
    assert op["kind"] == "assets"
    assert op["scene_id"] == "scene_1"
    assert set(op["result_json"]["names"]) == {"Red Cup", "Picnic Blanket"}
    assert len(op["result_json"]["asset_ids"]) == 2
    # Assets really linked to the scene.
    scene = client.get("/scenes/scene_1").json()
    for aid in op["result_json"]["asset_ids"]:
        assert aid in scene["asset_ids_json"]


# ── captions ──────────────────────────────────────────────────────────────────

def test_caption_background(ctx, monkeypatch):
    client, fake = ctx

    class FakeOutput:
        id = "out_1"
        captioned_path = "/tmp/out_1.captioned.mp4"

    async def fake_caption(session, output_id, *, style="kids", language="zh", model=None):
        assert output_id == "out_1"
        assert style == "bold"
        assert language == "en"
        return FakeOutput()

    monkeypatch.setattr("app.services.caption_service.caption_output", fake_caption)
    resp = client.post(
        "/outputs/out_1/caption?background=true",
        json={"style": "bold", "language": "en"},
    )
    assert resp.status_code == 202, resp.text
    op = _wait_op(client, resp.json()["op_id"])
    assert op["status"] == "succeeded", op
    assert op["kind"] == "caption"
    assert op["output_id"] == "out_1"
    assert op["result_json"] == {
        "output_id": "out_1",
        "captioned_path": "/tmp/out_1.captioned.mp4",
    }


# ── style ingest ──────────────────────────────────────────────────────────────

def test_style_ingest_background(ctx, monkeypatch):
    client, fake = ctx

    class FakeStyle:
        id = "style_abc"
        name = "Project style"
        style_prompt = "3D cartoon"

    async def fake_ingest(session):
        return FakeStyle()

    monkeypatch.setattr("app.services.style_service.ingest_style", fake_ingest)
    resp = client.post("/style/ingest?background=true")
    assert resp.status_code == 202, resp.text
    op = _wait_op(client, resp.json()["op_id"])
    assert op["status"] == "succeeded", op
    assert op["kind"] == "style_ingest"
    assert op["result_json"] == {"style_guide_id": "style_abc", "name": "Project style"}


# ── /ops listing + 404 ────────────────────────────────────────────────────────

def test_ops_list_and_missing_404(ctx):
    client, fake = ctx
    assert client.get("/ops/op_does_not_exist").status_code == 404

    r1 = client.post("/scenes/scene_1/storyboard?background=true")
    assert r1.status_code == 202
    _wait_op(client, r1.json()["op_id"])

    listed = client.get("/ops").json()
    assert any(o["id"] == r1.json()["op_id"] for o in listed)


def test_reconcile_stuck_ops(ctx):
    """Ops left running by a dead process are failed on startup reconciliation."""
    from sqlmodel import Session

    import app.database as _db
    from app.models import Op
    from app.services import op_service

    with Session(_db.engine) as s:
        s.add(Op(id="op_stuck", kind="storyboard", status="running"))
        s.commit()

    assert op_service.reconcile_stuck_ops() == 1
    with Session(_db.engine) as s:
        op = s.get(Op, "op_stuck")
        assert op.status == "failed"
        assert "restarted" in op.error
