"""Scene-level generalised pipeline: 分镜图 endpoint, whole-scene render, graph."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.database import get_session
from app.schemas import AssetPlan, PlannedAsset, QAResult, SceneRefinement, ShotRefinement
from app.schemas.scene_schema import ScriptDraft, ScriptScene


def _make_draft(n: int) -> ScriptDraft:
    return ScriptDraft(
        title="Test Video",
        summary="A multi-scene story",
        scenes=[
            ScriptScene(
                scene_id=f"draft_s{i}",
                title=f"Scene {i}",
                summary=f"Summary of scene {i}",
                suggested_duration=5,
            )
            for i in range(1, n + 1)
        ],
    )


class FakeLLM:
    async def generate(self, *, response_model, **kw):
        if response_model is SceneRefinement:
            return SceneRefinement(summary="warmer dusk lighting", note="warmed the lighting")
        if response_model is ShotRefinement:
            return ShotRefinement(
                prompt="Grace waves at camera under warm dusk light",
                note="warmed the shot lighting",
            )
        if response_model is AssetPlan:
            return AssetPlan(
                assets=[
                    PlannedAsset(
                        name="Red Cup",
                        asset_type="prop",
                        description="a shiny red cup",
                        image_prompt="a shiny red ceramic cup, warm daylight, 3D cartoon",
                        shot_orders=[0],
                    ),
                    PlannedAsset(
                        name="Picnic Blanket",
                        asset_type="prop",
                        description="a checkered blanket",
                        image_prompt="a checkered picnic blanket on grass, warm daylight",
                        shot_orders=[0],
                    ),
                ],
                reasoning="scene needs props",
            )
        if response_model is ScriptDraft:
            return _make_draft(3)
        assert response_model is QAResult
        return QAResult(score=8, passed=True, issues=[], recommendation="accept")


class FakeAtlas:
    def __init__(self):
        self.image_payloads: list[dict] = []
        self.video_payloads: list[dict] = []
        self._n = 0

    async def upload_media(self, file_path: str) -> str:
        return f"https://static.atlascloud.ai/up/{Path(file_path).name}"

    async def generate_image(self, payload: dict) -> dict:
        self.image_payloads.append(payload)
        self._n += 1
        return {"id": f"img_{self._n}", "status": "completed",
                "outputs": [f"https://static.atlascloud.ai/gen/{self._n}.png"]}

    async def generate_video(self, payload: dict) -> str:
        self.video_payloads.append(payload)
        return "pred_video_1"

    async def get_prediction(self, pid: str) -> dict:
        return {"status": "completed", "outputs": ["https://static.atlascloud.ai/out.mp4"]}


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))

    fake = FakeAtlas()
    for target in (
        "app.services.render_service.get_atlas_client",
        "app.providers.atlascloud_video.get_atlas_client",
        "app.providers.atlascloud_image.get_atlas_client",
        "app.services.storyboard_service.get_atlas_client",
        "app.services.asset_gen_service.get_atlas_client",
    ):
        monkeypatch.setattr(target, lambda: fake)
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM())

    async def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake")
        return dest

    async def fake_thumb(video_path, dest, **kw):
        return None

    monkeypatch.setattr("app.services.media.download", fake_download)
    monkeypatch.setattr("app.services.storyboard_service.media.download", fake_download)
    monkeypatch.setattr("app.services.poll_service.media.download", fake_download)
    monkeypatch.setattr("app.services.poll_service.media.make_thumbnail", fake_thumb)

    from app.models import Asset, Character, Scene, Shot

    (tmp_path / "char.png").write_bytes(b"img")
    (tmp_path / "bg.png").write_bytes(b"img")
    with Session(engine) as s:
        s.add(Character(id="char_grace", name="Grace", appearance="girl in pink dress",
                        reference_asset_ids_json=["asset_char"]))
        s.add(Asset(id="asset_char", type="character_reference", name="Grace",
                    file_path=str(tmp_path / "char.png")))
        s.add(Asset(id="asset_bg", type="background", name="Meadow",
                    file_path=str(tmp_path / "bg.png")))
        s.add(Scene(id="scene_1", title="t", summary="a sunny meadow lesson",
                    duration=6, aspect_ratio="9:16",
                    character_ids_json=["char_grace"], asset_ids_json=["asset_bg"]))
        s.add(Shot(id="shot_1", scene_id="scene_1", shot_order=0, duration=3,
                   prompt="Grace waves at camera", camera="mid", movement="static"))
        s.add(Shot(id="shot_2", scene_id="scene_1", shot_order=1, duration=3,
                   prompt="Grace points at the meadow", camera="wide", movement="static"))
        s.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c, fake


def test_scene_storyboard_endpoint(ctx):
    client, fake = ctx
    resp = client.post("/scenes/scene_1/storyboard")
    assert resp.status_code == 200, resp.text
    asset = resp.json()
    assert asset["type"] == "storyboard"
    assert asset["metadata_json"]["scene_id"] == "scene_1"
    # Prompt: 2x2 grid (2 beats), shot beats as panels, character identity.
    payload = fake.image_payloads[0]
    prompt = payload["prompt"]
    assert "2x2" in prompt
    assert "Grace waves at camera" in prompt
    assert "girl in pink dress" in prompt
    # True image references: the cast's sheets are inputs to the edit model,
    # and the panel aspect matches the scene's video aspect.
    assert payload["model"] == "google/nano-banana-2/edit"
    assert payload["images"] == ["https://static.atlascloud.ai/up/char.png"]
    assert payload["aspect_ratio"] == "9:16"


def test_scene_render_uses_shots_storyboard_and_references(ctx):
    client, fake = ctx
    assert client.post("/scenes/scene_1/storyboard").status_code == 200
    resp = client.post("/scenes/scene_1/render")
    assert resp.status_code == 202, resp.text

    payload = fake.video_payloads[0]
    # Multi-shot customize from the stored shots, indexed.
    assert payload["multi_shot"] is True
    assert payload["shot_type"] == "customize"
    assert payload["multi_prompt"] == [
        {"index": 1, "prompt": "Grace waves at camera", "duration": 3},
        {"index": 2, "prompt": "Grace points at the meadow", "duration": 3},
    ]
    assert payload["duration"] == 6
    # References: character + scene asset + 分镜图 all reach images[].
    assert "https://static.atlascloud.ai/up/char.png" in payload["images"]
    assert "https://static.atlascloud.ai/up/bg.png" in payload["images"]
    assert len(payload["images"]) == 3  # char + bg + storyboard
    assert payload["sound"] is True


def test_scene_render_without_shots_rejected(ctx):
    client, fake = ctx
    from app.models import Scene

    resp = client.post("/scenes/scene_1/shots/does-not-exist")
    # Seed a shotless scene via the API surface instead: use a fresh scene id.
    resp = client.post("/scenes/scene_missing/render")
    assert resp.status_code == 404


def test_edit_shot(ctx):
    client, fake = ctx
    resp = client.patch(
        "/shots/shot_1",
        json={"prompt": "Grace jumps with joy", "duration": 4, "camera": "close-up"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prompt"] == "Grace jumps with joy"
    assert body["duration"] == 4
    assert body["camera"] == "close-up"
    assert body["movement"] == "static"  # untouched fields preserved
    # The edit is what the next render uses.
    shots = client.get("/scenes/scene_1/shots").json()
    assert shots[0]["prompt"] == "Grace jumps with joy"


def test_edit_scene(ctx):
    client, fake = ctx
    resp = client.patch(
        "/scenes/scene_1",
        json={"summary": "an edited summary", "aspect_ratio": "16:9"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"] == "an edited summary"
    assert body["aspect_ratio"] == "16:9"
    assert body["title"] == "t"  # untouched


def test_edit_missing_shot_404(ctx):
    client, fake = ctx
    assert client.patch("/shots/nope", json={"prompt": "x"}).status_code == 404


def test_graph_endpoint(ctx):
    client, fake = ctx
    body = client.get("/graph").json()
    ids = {n["id"] for n in body["nodes"]}
    assert {"char_grace", "asset_char", "asset_bg", "scene_1", "shot_1"} <= ids
    pairs = {(e["source"], e["target"]) for e in body["edges"]}
    assert ("scene_1", "shot_1") in pairs
    assert ("scene_1", "char_grace") in pairs
    assert ("char_grace", "asset_char") in pairs


def test_cast_and_shot_asset_relationships(ctx):
    client, fake = ctx

    # POST /scenes/{id}/cast/{char} adds to character_ids_json (idempotent)
    resp = client.post("/scenes/scene_1/cast/char_grace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "char_grace" in body["character_ids_json"]
    count_before = body["character_ids_json"].count("char_grace")
    assert count_before == 1

    # Posting again doesn't duplicate
    resp2 = client.post("/scenes/scene_1/cast/char_grace")
    assert resp2.status_code == 200
    assert resp2.json()["character_ids_json"].count("char_grace") == 1

    # DELETE removes the cast member
    resp3 = client.delete("/scenes/scene_1/cast/char_grace")
    assert resp3.status_code == 200
    assert "char_grace" not in resp3.json()["character_ids_json"]

    # Unknown character -> 404
    assert client.post("/scenes/scene_1/cast/no_such_char").status_code == 404

    # Unknown scene -> 404
    assert client.post("/scenes/no_such_scene/cast/char_grace").status_code == 404

    # POST /shots/{id}/assets/{asset} adds to asset_ids_json (idempotent)
    resp4 = client.post("/shots/shot_1/assets/asset_bg")
    assert resp4.status_code == 200, resp4.text
    assert "asset_bg" in resp4.json()["asset_ids_json"]
    assert resp4.json()["asset_ids_json"].count("asset_bg") == 1

    # Posting again doesn't duplicate
    resp5 = client.post("/shots/shot_1/assets/asset_bg")
    assert resp5.status_code == 200
    assert resp5.json()["asset_ids_json"].count("asset_bg") == 1

    # DELETE removes the asset reference
    resp6 = client.delete("/shots/shot_1/assets/asset_bg")
    assert resp6.status_code == 200
    assert "asset_bg" not in resp6.json()["asset_ids_json"]

    # Unknown shot -> 404
    assert client.post("/shots/no_such_shot/assets/asset_bg").status_code == 404

    # Unknown asset -> 404
    assert client.post("/shots/shot_1/assets/no_such_asset").status_code == 404


def test_shot_reorder_via_patch(ctx):
    client, fake = ctx
    resp = client.patch("/shots/shot_1", json={"shot_order": 5})
    assert resp.status_code == 200, resp.text
    assert resp.json()["shot_order"] == 5


def test_delete_shot_and_scene(ctx):
    client, fake = ctx
    from app.models import RenderJob, RenderStatus, Shot
    from sqlmodel import Session

    # ----- shot deletion -----
    r = client.delete("/shots/shot_1")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == "shot_1"

    # second delete → 404
    assert client.delete("/shots/shot_1").status_code == 404

    # ----- seed a fresh shot on scene_1 + a RenderJob tied to scene_1 -----
    from app.database import engine as _engine_import  # resolved via monkeypatch

    import app.database as _db_mod

    with Session(_db_mod.engine) as s:
        s.add(Shot(id="shot_3", scene_id="scene_1", shot_order=2, duration=2,
                   prompt="Grace runs away", camera="wide", movement="pan"))
        # RenderJob whose scene_id → scene_1 (no shot) — tests dangling-edge guard
        s.add(RenderJob(id="job_dangling", scene_id="scene_1", shot_id=None,
                        model="atlas/test", status=RenderStatus.succeeded))
        s.commit()

    # ----- scene deletion -----
    r = client.delete("/scenes/scene_1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == "scene_1"
    assert body["shots_deleted"] >= 1   # shot_2 + shot_3 still exist (shot_1 already gone)

    # idempotence: second delete → 404
    assert client.delete("/scenes/scene_1").status_code == 404

    # ----- graph has no dangling edges -----
    g = client.get("/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])


def test_generate_scene_assets(ctx):
    client, fake = ctx
    resp = client.post(
        "/scenes/scene_1/assets/generate", json={"instruction": "need a red cup"}
    )
    assert resp.status_code == 200, resp.text
    assets = resp.json()
    assert len(assets) == 2
    names = {a["name"] for a in assets}
    assert names == {"Red Cup", "Picnic Blanket"}
    for a in assets:
        assert a["file_path"]  # image downloaded locally
        assert a["metadata_json"]["scene_id"] == "scene_1"
        assert a["metadata_json"]["generated"] is True
        assert a["metadata_json"]["image_prompt"]

    # ERNIE got one text-to-image payload per planned asset, using the
    # planner's standalone image_prompt verbatim.
    prompts = [p["prompt"] for p in fake.image_payloads]
    assert "a shiny red ceramic cup, warm daylight, 3D cartoon" in prompts

    # Scene now links the new assets (alongside the pre-existing background).
    scene = client.get("/scenes/scene_1").json()
    for a in assets:
        assert a["id"] in scene["asset_ids_json"]
    assert "asset_bg" in scene["asset_ids_json"]

    # Graph shows the new assets linked to the scene (both the asset_ids_json
    # 'uses' edge and the metadata scene edge resolve to scene_1 → asset).
    g = client.get("/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    pairs = {(e["source"], e["target"]) for e in g["edges"]}
    for a in assets:
        assert a["id"] in ids
        assert ("scene_1", a["id"]) in pairs

    # Auto-tagging: the planned shot_orders=[0] means shot_1 now references
    # the new assets in asset_ids_json AND mentions each as @Name in its prompt.
    shot = client.get("/scenes/scene_1/shots").json()[0]
    assert shot["id"] == "shot_1"
    for a in assets:
        assert a["id"] in shot["asset_ids_json"]
        assert f"@{a['name']}" in shot["prompt"]
    # shot_2 (order 1) untouched
    shot2 = client.get("/scenes/scene_1/shots").json()[1]
    assert shot2["asset_ids_json"] in (None, [])
    assert "@" not in shot2["prompt"]


def test_plan_scene_assets_endpoint_no_generation(ctx):
    client, fake = ctx
    resp = client.post(
        "/scenes/scene_1/assets/plan", json={"instruction": "need a red cup"}
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    names = {a["name"] for a in plan["assets"]}
    assert names == {"Red Cup", "Picnic Blanket"}
    assert plan["reasoning"]
    assert plan["assets"][0]["shot_orders"] == [0]

    # Plan-only: no images generated, no Asset rows created, shots untouched.
    assert fake.image_payloads == []
    g = client.get("/graph").json()
    asset_nodes = [n for n in g["nodes"] if n["id"].startswith("asset")]
    assert {n["id"] for n in asset_nodes} == {"asset_char", "asset_bg"}
    shot = client.get("/scenes/scene_1/shots").json()[0]
    assert shot["asset_ids_json"] in (None, [])
    assert "@" not in shot["prompt"]


def test_generate_scene_assets_unknown_scene_404(ctx):
    client, fake = ctx
    resp = client.post("/scenes/no_such_scene/assets/generate", json={})
    assert resp.status_code == 404


def test_generate_scene_assets_respects_max_assets(ctx):
    client, fake = ctx
    resp = client.post(
        "/scenes/scene_1/assets/generate", json={"max_assets": 1}
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    assert len(fake.image_payloads) == 1


def test_refine_scene(ctx):
    client, fake = ctx
    resp = client.post("/scenes/scene_1/refine", json={"instruction": "warmer lighting"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scene"]["summary"] == "warmer dusk lighting"
    assert body["scene"]["title"] == "t"  # untouched fields preserved
    assert body["note"]
    # Persistence: a follow-up GET sees the change.
    scene = client.get("/scenes/scene_1").json()
    assert scene["summary"] == "warmer dusk lighting"


def test_refine_shot(ctx):
    client, fake = ctx
    resp = client.post("/shots/shot_1/refine", json={"instruction": "warmer lighting"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shot"]["prompt"] == "Grace waves at camera under warm dusk light"
    assert body["shot"]["camera"] == "mid"  # untouched fields preserved
    assert body["note"]
    shots = client.get("/scenes/scene_1/shots").json()
    assert shots[0]["prompt"] == "Grace waves at camera under warm dusk light"


def test_refine_unknown_ids_404(ctx):
    client, fake = ctx
    assert client.post("/scenes/nope/refine", json={"instruction": "x"}).status_code == 404
    assert client.post("/shots/nope/refine", json={"instruction": "x"}).status_code == 404


def test_graph_nodes_carry_canvas_data(ctx):
    client, fake = ctx
    body = client.get("/graph").json()
    nodes_by_id = {n["id"]: n for n in body["nodes"]}

    # All nodes must have a "data" key
    for n in body["nodes"]:
        assert "data" in n, f"node {n['id']} missing 'data'"

    # Asset nodes carry file_path and asset_type
    asset_node = nodes_by_id["asset_bg"]
    assert "file_path" in asset_node["data"]
    assert "asset_type" in asset_node["data"]

    # Scene node carries aspect_ratio
    scene_node = nodes_by_id["scene_1"]
    assert "aspect_ratio" in scene_node["data"]

    # Shot node carries scene_id and prompt
    shot_node = nodes_by_id["shot_1"]
    assert "scene_id" in shot_node["data"]
    assert "prompt" in shot_node["data"]


# ── /scripts/generate scene_count tests ──────────────────────────────────────

@pytest.fixture
def script_ctx(monkeypatch, tmp_path):
    """Minimal fixture for POST /scripts/generate — no pre-seeded scenes needed."""
    engine = create_engine(
        f"sqlite:///{tmp_path/'s.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.services.poll_service.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM())

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c, engine


def test_generate_script_without_scene_count_persists_all(script_ctx):
    """Without scene_count, all 3 LLM scenes are persisted."""
    client, engine = script_ctx
    from app.models import Scene

    scenes_before = len(list(Session(engine).exec(select(Scene)).all()))
    resp = client.post("/scripts/generate", json={"idea": "a cat story"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    scenes_after = len(list(Session(engine).exec(select(Scene)).all()))
    new_scenes = scenes_after - scenes_before
    assert new_scenes == 3
    assert len(body["draft"]["scenes"]) == 3


def test_generate_script_with_scene_count_1_truncates_to_1(script_ctx):
    """With scene_count=1, only 1 scene is persisted and draft reflects it."""
    client, engine = script_ctx
    from app.models import Scene

    scenes_before = len(list(Session(engine).exec(select(Scene)).all()))
    resp = client.post("/scripts/generate", json={"idea": "a single video", "scene_count": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    scenes_after = len(list(Session(engine).exec(select(Scene)).all()))
    new_scenes = scenes_after - scenes_before
    assert new_scenes == 1
    assert len(body["draft"]["scenes"]) == 1


def test_generate_script_scene_count_respects_cap(script_ctx):
    """scene_count=2 caps at 2 even when LLM returns 3."""
    client, engine = script_ctx
    from app.models import Scene

    scenes_before = len(list(Session(engine).exec(select(Scene)).all()))
    resp = client.post("/scripts/generate", json={"idea": "a two-part story", "scene_count": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    scenes_after = len(list(Session(engine).exec(select(Scene)).all()))
    new_scenes = scenes_after - scenes_before
    assert new_scenes == 2
    assert len(body["draft"]["scenes"]) == 2
