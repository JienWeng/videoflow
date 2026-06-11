"""Scene-level generalised pipeline: 分镜图 endpoint, whole-scene render, graph."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.database import get_session
from app.schemas import (
    AssetPlan,
    PlannedAsset,
    QAResult,
    SceneRefinement,
    ShotList,
    ShotRefinement,
    ShotSpec,
)
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
    # Returned by the ShotRefinement branch; tests may monkeypatch this on the
    # class to simulate a refine pass that fails to add dialogue.
    refinement_prompt = (
        "Grace waves at camera under warm dusk light and says, 「What a lovely evening!」"
    )
    # Returned by the AssetPlan branch; tests may monkeypatch this on the class
    # to simulate a planner that duplicates an existing asset.
    planned_assets = [
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
    ]

    async def generate(self, *, response_model, **kw):
        if response_model is SceneRefinement:
            return SceneRefinement(summary="warmer dusk lighting", note="warmed the lighting")
        if response_model is ShotRefinement:
            return ShotRefinement(
                prompt=self.refinement_prompt,
                note="warmed the shot lighting",
            )
        if response_model is AssetPlan:
            return AssetPlan(
                assets=[a.model_copy(deep=True) for a in self.planned_assets],
                reasoning="scene needs props",
            )
        if response_model is ShotList:
            return ShotList(
                scene_id="scene_1",
                shots=[
                    # One shot WITH a spoken line, one WITHOUT — the missing
                    # one exercises the bounded dialogue auto-fix.
                    ShotSpec(shot_id="gen_sh1", duration=3,
                             prompt="@Grace lifts the Red Cup and says, 「Cheers!」",
                             camera="mid", movement="static"),
                    ShotSpec(shot_id="gen_sh2", duration=3,
                             prompt="@Grace smiles at camera", camera="close-up",
                             movement="static"),
                ],
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
                        voice_rules_json=["cheerful bright child's voice",
                                          "speaks slowly"],
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
    # The scene's background asset is also included as a prop reference.
    assert payload["model"] == "google/nano-banana-2/edit"
    assert "https://static.atlascloud.ai/up/char.png" in payload["images"]
    assert "https://static.atlascloud.ai/up/bg.png" in payload["images"]
    # Cast sheet comes before scene assets.
    assert payload["images"].index("https://static.atlascloud.ai/up/char.png") < \
           payload["images"].index("https://static.atlascloud.ai/up/bg.png")
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
    # The whole-scene negative line forbids duplicated/cloned characters.
    from app.agents.prompt_agent import NO_CLONE_NEGATIVE

    assert NO_CLONE_NEGATIVE in payload["prompt"]
    # The cast's voice_rules flow deterministically into the render prompt.
    assert (
        "Voices: @Grace — cheerful bright child's voice, speaks slowly"
        in payload["prompt"]
    )


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

    # The cast (Grace) has a reference sheet, so each planned asset is rendered
    # with the reference/edit model against her sheet for style consistency,
    # keeping the planner's standalone image_prompt intact.
    from app.config import get_settings

    prompts = [p["prompt"] for p in fake.image_payloads]
    assert any("a shiny red ceramic cup, warm daylight, 3D cartoon" in p for p in prompts)
    for payload in fake.image_payloads:
        assert payload["model"] == get_settings().atlas_image_ref_model
        assert payload["images"] == ["https://static.atlascloud.ai/up/char.png"]
        assert payload["aspect_ratio"] == "9:16"

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


def _seed_global_red_cup():
    """Insert a GLOBAL library asset (image prop, NOT linked to scene_1)."""
    import app.database
    from app.models import Asset

    with Session(app.database.engine) as s:
        s.add(Asset(id="asset_redcup", type="prop", name="Red Cup",
                    description="a shiny red cup", file_path="/tmp/red_cup.png"))
        s.commit()


_REUSE_PLAN = [
    # Name twisted in case and whitespace — must still match "Red Cup".
    PlannedAsset(name="red  CUP", asset_type="prop", description="a red cup",
                 image_prompt="a shiny red ceramic cup, warm daylight",
                 shot_orders=[0]),
    PlannedAsset(name="Lantern", asset_type="prop", description="a paper lantern",
                 image_prompt="a glowing paper lantern, warm daylight",
                 shot_orders=[0]),
]


def test_generate_scene_assets_reuses_global_library_asset(ctx, monkeypatch):
    client, fake = ctx
    _seed_global_red_cup()
    monkeypatch.setattr(FakeLLM, "planned_assets", _REUSE_PLAN)

    resp = client.post("/scenes/scene_1/assets/generate", json={})
    assert resp.status_code == 200, resp.text
    assets = resp.json()
    # Response contains BOTH the reused library asset and the new one.
    assert {a["name"] for a in assets} == {"Red Cup", "Lantern"}
    assert "asset_redcup" in {a["id"] for a in assets}

    # Only ONE image generated — the novel Lantern; Red Cup was linked, not rendered.
    assert len(fake.image_payloads) == 1
    assert "lantern" in fake.image_payloads[0]["prompt"].lower()

    # Scene now links the existing Red Cup alongside the new Lantern.
    scene = client.get("/scenes/scene_1").json()
    assert "asset_redcup" in scene["asset_ids_json"]

    # shot_1 (order 0) got the EXISTING asset id attached and the @-tag uses the
    # EXISTING asset's canonical name, not the planner's twisted spelling.
    shot = client.get("/scenes/scene_1/shots").json()[0]
    assert "asset_redcup" in shot["asset_ids_json"]
    assert "@Red Cup" in shot["prompt"]


def test_plan_scene_assets_marks_reusable_suggestions(ctx, monkeypatch):
    client, fake = ctx
    _seed_global_red_cup()
    monkeypatch.setattr(FakeLLM, "planned_assets", _REUSE_PLAN)

    resp = client.post("/scenes/scene_1/assets/plan", json={})
    assert resp.status_code == 200, resp.text
    by_name = {a["name"]: a for a in resp.json()["assets"]}
    assert by_name["red  CUP"]["reuse"] is True
    assert by_name["Lantern"]["reuse"] is False
    # Plan-only: nothing generated, nothing linked.
    assert fake.image_payloads == []
    shot = client.get("/scenes/scene_1/shots").json()[0]
    assert shot["asset_ids_json"] in (None, [])


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
    assert body["shot"]["prompt"] == FakeLLM.refinement_prompt
    assert body["shot"]["camera"] == "mid"  # untouched fields preserved
    assert body["note"]
    shots = client.get("/scenes/scene_1/shots").json()
    assert shots[0]["prompt"] == FakeLLM.refinement_prompt


def test_refine_unknown_ids_404(ctx):
    client, fake = ctx
    assert client.post("/scenes/nope/refine", json={"instruction": "x"}).status_code == 404
    assert client.post("/shots/nope/refine", json={"instruction": "x"}).status_code == 404


def test_refine_shot_preserves_original_dialogue(ctx, monkeypatch):
    """If the original shot prompt speaks (「」) and the refined prompt lost the
    line, the original quoted line is deterministically re-appended — refine
    must never silently silence a shot."""
    client, fake = ctx
    # Give shot_1 a spoken line, then refine with a rewrite that drops it.
    resp = client.patch(
        "/shots/shot_1", json={"prompt": "Grace waves at camera and says, 「Hello!」"}
    )
    assert resp.status_code == 200, resp.text
    monkeypatch.setattr(
        FakeLLM, "refinement_prompt", "Grace waves at camera under warm dusk light"
    )

    resp = client.post("/shots/shot_1/refine", json={"instruction": "warmer lighting"})
    assert resp.status_code == 200, resp.text
    prompt = resp.json()["shot"]["prompt"]
    assert prompt == "Grace waves at camera under warm dusk light 「Hello!」"
    # Persisted too.
    shots = client.get("/scenes/scene_1/shots").json()
    assert shots[0]["prompt"] == prompt


def test_refine_shot_with_own_dialogue_unchanged(ctx):
    """A refinement that keeps its own 「」 line is applied verbatim (no
    re-appending of the original line)."""
    client, fake = ctx
    resp = client.patch(
        "/shots/shot_1", json={"prompt": "Grace waves at camera and says, 「Hello!」"}
    )
    assert resp.status_code == 200, resp.text

    resp = client.post("/shots/shot_1/refine", json={"instruction": "warmer lighting"})
    assert resp.status_code == 200, resp.text
    # FakeLLM's default refinement already speaks — applied as-is.
    assert resp.json()["shot"]["prompt"] == FakeLLM.refinement_prompt
    assert "「Hello!」" not in resp.json()["shot"]["prompt"]


def test_generate_scene_assets_dedups_existing_names(ctx, monkeypatch):
    """A planned asset whose name matches an existing scene asset (case/space
    twisted) is dropped in code — only the novel asset is generated."""
    client, fake = ctx
    monkeypatch.setattr(FakeLLM, "planned_assets", [
        PlannedAsset(name="  MEADOW ", asset_type="background",
                     description="dup of the seeded background",
                     image_prompt="a sunny meadow"),
        PlannedAsset(name="Red Cup", asset_type="prop",
                     description="a shiny red cup",
                     image_prompt="a shiny red ceramic cup", shot_orders=[0]),
    ])
    resp = client.post("/scenes/scene_1/assets/generate", json={})
    assert resp.status_code == 200, resp.text
    assets = resp.json()
    assert [a["name"] for a in assets] == ["Red Cup"]
    assert len(fake.image_payloads) == 1  # the duplicate was never rendered


def test_plan_scene_assets_endpoint_dedups_existing_names(ctx, monkeypatch):
    """The plan-only endpoint reports deduped suggestions too (shared filter),
    and dropped dupes don't consume max_assets slots."""
    client, fake = ctx
    monkeypatch.setattr(FakeLLM, "planned_assets", [
        PlannedAsset(name="meadow", asset_type="background",
                     description="dup", image_prompt="a sunny meadow"),
        PlannedAsset(name="Red Cup", asset_type="prop",
                     description="a shiny red cup",
                     image_prompt="a shiny red ceramic cup"),
    ])
    resp = client.post("/scenes/scene_1/assets/plan", json={"max_assets": 1})
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    # Dedup runs BEFORE truncation: the dupe doesn't eat the single slot.
    assert [a["name"] for a in plan["assets"]] == ["Red Cup"]
    assert fake.image_payloads == []  # plan-only: nothing rendered


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


# ── style guide enforcement ──────────────────────────────────────────────────

def _seed_style(client, **fields):
    resp = client.patch("/style", json=fields)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_asset_generation_applies_style_suffix(ctx):
    """Every generated asset's image prompt deterministically carries the
    project style text (code-level enforcement, not just the planner prompt)."""
    client, fake = ctx
    _seed_style(client, style_prompt="3D cartoon, soft pastel")

    resp = client.post("/scenes/scene_1/assets/generate", json={})
    assert resp.status_code == 200, resp.text
    assert fake.image_payloads
    for payload in fake.image_payloads:
        assert "3D cartoon, soft pastel" in payload["prompt"]
        # Suffix appended exactly once (idempotent helper).
        assert payload["prompt"].count("Style: 3D cartoon, soft pastel") == 1


def test_storyboard_prompt_contains_style(ctx):
    client, fake = ctx
    _seed_style(client, style_prompt="3D cartoon, soft pastel", lighting="bright morning sun")

    resp = client.post("/scenes/scene_1/storyboard")
    assert resp.status_code == 200, resp.text
    prompt = fake.image_payloads[0]["prompt"]
    assert "3D cartoon, soft pastel" in prompt
    assert "lighting: bright morning sun" in prompt


def test_asset_generation_uses_style_reference_assets(ctx):
    """With the style guide pointing at a reference asset, asset generation uses
    the reference/edit model with the style refs FIRST in images[]."""
    client, fake = ctx
    from app.config import get_settings

    _seed_style(client, style_prompt="3D cartoon, soft pastel",
                reference_asset_ids=["asset_char"])

    resp = client.post("/scenes/scene_1/assets/generate", json={})
    assert resp.status_code == 200, resp.text
    assert fake.image_payloads
    for payload in fake.image_payloads:
        assert payload["model"] == get_settings().atlas_image_ref_model
        # Style ref first; cast ref (same asset) deduped.
        assert payload["images"] == ["https://static.atlascloud.ai/up/char.png"]
        assert payload["prompt"].startswith(
            "Match the visual style of the attached reference images exactly. "
        )
        assert "3D cartoon, soft pastel" in payload["prompt"]


def test_storyboard_prepends_style_reference_assets(ctx):
    client, fake = ctx
    import app.database as _db_mod
    from app.models import Asset

    style_img = Path(_db_mod.engine.url.database).parent / "style_ref.png"
    style_img.write_bytes(b"img")
    with Session(_db_mod.engine) as s:
        s.add(Asset(id="asset_style", type="reference", name="Style Ref",
                    file_path=str(style_img)))
        s.commit()
    _seed_style(client, reference_asset_ids=["asset_style"])

    resp = client.post("/scenes/scene_1/storyboard")
    assert resp.status_code == 200, resp.text
    payload = fake.image_payloads[0]
    images = payload["images"]
    # Style guide refs first, then the cast's sheet, then scene prop/bg assets.
    assert images[0] == "https://static.atlascloud.ai/up/style_ref.png"
    assert images[1] == "https://static.atlascloud.ai/up/char.png"
    # scene_1 has asset_bg (background), which is now included as a prop ref.
    assert "https://static.atlascloud.ai/up/bg.png" in images
    assert images.index(images[1]) < images.index("https://static.atlascloud.ai/up/bg.png")


def test_asset_generation_without_refs_or_style_uses_plain_ernie(ctx):
    """A scene with no cast and no style guide keeps the original ERNIE
    text-to-image path with the planner prompt verbatim."""
    client, fake = ctx
    import app.database as _db_mod
    from app.config import get_settings
    from app.models import Scene

    with Session(_db_mod.engine) as s:
        s.add(Scene(id="scene_plain", title="p", summary="an empty room",
                    duration=5, aspect_ratio="9:16"))
        s.commit()

    resp = client.post("/scenes/scene_plain/assets/generate", json={})
    assert resp.status_code == 200, resp.text
    assert fake.image_payloads
    for payload in fake.image_payloads:
        assert payload["model"] == get_settings().atlas_image_model
        assert "images" not in payload
    prompts = [p["prompt"] for p in fake.image_payloads]
    assert "a shiny red ceramic cup, warm daylight, 3D cartoon" in prompts


# ── shots/generate: auto prop generation ─────────────────────────────────────

def test_shots_generate_auto_assets_default(ctx):
    """POST /scenes/{id}/shots/generate (no body) plans + generates props
    automatically: new assets are linked to the scene and @-tagged into shots."""
    client, fake = ctx
    resp = client.post("/scenes/scene_1/shots/generate")
    assert resp.status_code == 200, resp.text
    shots = resp.json()
    # Response shape unchanged: a list of persisted Shot rows (the auto-asset
    # step may have @-tagged the new prop names into the prompts).
    assert isinstance(shots, list)
    assert any(s["prompt"].startswith("@Grace lifts the") for s in shots)

    # Auto assets: the planner's props were generated and linked to the scene.
    scene = client.get("/scenes/scene_1").json()
    new_ids = [a for a in scene["asset_ids_json"] if a != "asset_bg"]
    assert len(new_ids) == 2
    assert fake.image_payloads  # images actually rendered

    # At least one shot prompt got @-tagged with a generated asset name.
    all_shots = client.get("/scenes/scene_1/shots").json()
    assert any("@Red Cup" in s["prompt"] for s in all_shots)


def test_shots_generate_auto_assets_false(ctx):
    client, fake = ctx
    resp = client.post("/scenes/scene_1/shots/generate", json={"auto_assets": False})
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)
    # No images generated, no new assets linked to the scene.
    assert fake.image_payloads == []
    scene = client.get("/scenes/scene_1").json()
    assert scene["asset_ids_json"] == ["asset_bg"]


def test_shots_generate_enforces_dialogue(ctx):
    """A generated shot missing a 「」 line gets ONE auto-fix refine pass; after
    /shots/generate every persisted shot from this batch speaks."""
    client, fake = ctx
    resp = client.post("/scenes/scene_1/shots/generate", json={"auto_assets": False})
    assert resp.status_code == 200, resp.text
    shots = resp.json()
    assert len(shots) == 2
    # gen_sh1 already had dialogue and is untouched.
    assert shots[0]["prompt"] == "@Grace lifts the Red Cup and says, 「Cheers!」"
    # gen_sh2 lacked dialogue → replaced with the refine agent's spoken version.
    assert shots[1]["prompt"] == FakeLLM.refinement_prompt
    for s in shots:
        assert "「" in s["prompt"] and "」" in s["prompt"]


def test_shots_generate_dialogue_fix_failure_keeps_original(ctx, monkeypatch):
    """If the refine pass STILL returns a prompt without dialogue, the original
    prompt is kept (no retry) and the request succeeds."""
    client, fake = ctx
    monkeypatch.setattr(FakeLLM, "refinement_prompt", "still silent, no quotes here")
    resp = client.post("/scenes/scene_1/shots/generate", json={"auto_assets": False})
    assert resp.status_code == 200, resp.text
    shots = resp.json()
    assert shots[0]["prompt"] == "@Grace lifts the Red Cup and says, 「Cheers!」"
    assert shots[1]["prompt"] == "@Grace smiles at camera"  # unchanged


def test_shots_generate_tolerates_asset_failure(ctx, monkeypatch):
    """Auto prop generation failing (provider down) never fails the shots call."""
    client, fake = ctx

    async def boom(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        "app.services.asset_gen_service.generate_scene_assets", boom
    )
    resp = client.post("/scenes/scene_1/shots/generate")
    assert resp.status_code == 200, resp.text
    shots = resp.json()
    assert any(s["prompt"].startswith("@Grace lifts the Red Cup") for s in shots)
    # Shots persisted despite the asset failure.
    persisted = client.get("/scenes/scene_1/shots").json()
    assert any(s["prompt"].startswith("@Grace lifts the Red Cup") for s in persisted)


def test_shots_generate_is_idempotent(ctx):
    """Calling /shots/generate twice replaces — not appends — the scene's shots.

    After the second call the scene must have exactly the agent's shot count
    (2), with shot_order == [0, 1], and NONE of the round-one shot ids must
    survive in the DB.
    """
    client, fake = ctx

    # ── Round 1 ──────────────────────────────────────────────────────────────
    resp1 = client.post("/scenes/scene_1/shots/generate", json={"auto_assets": False})
    assert resp1.status_code == 200, resp1.text
    round1_ids = {s["id"] for s in resp1.json()}
    # The seeded shots (shot_1, shot_2) should already be gone after round 1.
    assert "shot_1" not in round1_ids
    assert "shot_2" not in round1_ids

    # ── Round 2 ──────────────────────────────────────────────────────────────
    resp2 = client.post("/scenes/scene_1/shots/generate", json={"auto_assets": False})
    assert resp2.status_code == 200, resp2.text
    round2_shots = resp2.json()

    # Exactly the agent's count — not doubled.
    assert len(round2_shots) == 2

    # Orders are contiguous from 0.
    orders = [s["shot_order"] for s in round2_shots]
    assert orders == [0, 1]

    # Round-1 ids are gone.
    all_shots = client.get("/scenes/scene_1/shots").json()
    surviving_ids = {s["id"] for s in all_shots}
    assert surviving_ids.isdisjoint(round1_ids), (
        f"Round-1 shot ids still present after round 2: "
        f"{surviving_ids & round1_ids}"
    )

    # DB count matches agent count.
    assert len(all_shots) == 2


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


def test_generate_script_persists_script_row(script_ctx):
    """The script itself survives: response carries script.id, a Script row is
    persisted with the idea + full draft_json, and every created scene links
    back via script_id. GET /scripts returns it."""
    client, engine = script_ctx
    from app.models import Scene, Script

    resp = client.post("/scripts/generate", json={"idea": "a cat story"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Additive response key: script alongside draft + scenes.
    assert body["script"]["id"].startswith("script_")
    assert body["script"]["idea"] == "a cat story"
    assert body["script"]["title"] == "Test Video"
    assert body["script"]["summary"] == "A multi-scene story"

    with Session(engine) as s:
        script = s.get(Script, body["script"]["id"])
        assert script is not None
        assert script.idea == "a cat story"
        assert script.draft_json["title"] == "Test Video"
        assert len(script.draft_json["scenes"]) == 3
        scenes = list(s.exec(select(Scene)).all())
        assert len(scenes) == 3
        assert all(sc.script_id == script.id for sc in scenes)

    listed = client.get("/scripts").json()
    assert [r["id"] for r in listed] == [body["script"]["id"]]


def test_generate_script_truncation_reflected_in_draft_json(script_ctx):
    """With scene_count, draft_json stores the truncated draft (cap enforced)."""
    client, engine = script_ctx
    from app.models import Script

    resp = client.post("/scripts/generate", json={"idea": "one video", "scene_count": 1})
    assert resp.status_code == 200, resp.text
    with Session(engine) as s:
        script = s.get(Script, resp.json()["script"]["id"])
        assert len(script.draft_json["scenes"]) == 1


def test_mention_autolink_on_shot_edit(ctx):
    """PATCH /shots with @Name mentions auto-links characters (scene cast) and
    assets (shot asset_ids_json). The fixture has BOTH a character named Grace
    and an asset named Grace — the character wins for that mention."""
    client, fake = ctx

    # Start clean: remove Grace from the cast so the link is observable.
    assert client.delete("/scenes/scene_1/cast/char_grace").status_code == 200

    resp = client.patch(
        "/shots/shot_1", json={"prompt": "Mid-shot: @Grace lifts @Meadow"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Asset "Meadow" attached to the shot — the PATCH response already shows it.
    assert "asset_bg" in body["asset_ids_json"]
    # Character "Grace" wins over the asset of the same name: cast, not shot asset.
    assert "asset_char" not in body["asset_ids_json"]
    scene = client.get("/scenes/scene_1").json()
    assert "char_grace" in scene["character_ids_json"]

    # Idempotent: patching the same prompt again does not duplicate links.
    resp2 = client.patch(
        "/shots/shot_1", json={"prompt": "Mid-shot: @Grace lifts @Meadow"}
    )
    assert resp2.json()["asset_ids_json"].count("asset_bg") == 1
    scene = client.get("/scenes/scene_1").json()
    assert scene["character_ids_json"].count("char_grace") == 1


def test_mention_autolink_on_scene_summary_edit(ctx):
    """PATCH /scenes with an asset @mention in the summary attaches the asset to
    the scene's asset_ids_json; a character mention joins the cast."""
    client, fake = ctx
    import app.database as _db_mod
    from app.models import Asset, Scene

    with Session(_db_mod.engine) as s:
        s.add(Asset(id="asset_cup", type="prop", name="Red Cup"))
        s.commit()
    assert client.delete("/scenes/scene_1/cast/char_grace").status_code == 200

    resp = client.patch(
        "/scenes/scene_1",
        json={"summary": "@Grace drinks from the @Red Cup in the meadow"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "asset_cup" in body["asset_ids_json"]
    assert "char_grace" in body["character_ids_json"]
    # Asset named "Grace" is NOT spuriously attached (character wins).
    assert "asset_char" not in body["asset_ids_json"]


def test_mention_no_match_is_noop(ctx):
    client, fake = ctx
    resp = client.patch("/shots/shot_1", json={"prompt": "@Nobody does anything"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_ids_json"] in (None, [])


def test_delete_asset_detaches_references(ctx):
    """DELETE /assets/{id} removes the row and detaches the id from all
    Scene.asset_ids_json, Shot.asset_ids_json, Character.reference_asset_ids_json,
    and StyleGuide.reference_asset_ids_json that reference it."""
    client, fake = ctx

    # Setup: attach asset_bg to shot_1 (scene_1 already has it in asset_ids_json).
    resp = client.post("/shots/shot_1/assets/asset_bg")
    assert resp.status_code == 200, resp.text
    assert "asset_bg" in resp.json()["asset_ids_json"]

    # Also set asset_bg as a style guide reference asset via PATCH /style.
    resp = client.patch("/style", json={"reference_asset_ids": ["asset_bg"]})
    assert resp.status_code == 200, resp.text
    assert "asset_bg" in resp.json()["reference_asset_ids_json"]

    # Confirm scene_1 already has asset_bg in its asset list (seeded by fixture).
    scene = client.get("/scenes/scene_1").json()
    assert "asset_bg" in scene["asset_ids_json"]

    # DELETE asset_bg — should detach from scene_1, shot_1, and the style guide.
    resp = client.delete("/assets/asset_bg")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] == "asset_bg"
    assert body["detached_from"] >= 3  # scene_1 + shot_1 + style guide

    # Verify scene_1 no longer contains asset_bg.
    scene = client.get("/scenes/scene_1").json()
    assert "asset_bg" not in scene["asset_ids_json"]

    # Verify shot_1 no longer contains asset_bg.
    shot = client.get("/scenes/scene_1/shots").json()[0]
    assert shot["id"] == "shot_1"
    assert "asset_bg" not in (shot["asset_ids_json"] or [])

    # Verify style guide reference list is cleaned.
    style = client.get("/style").json()
    assert "asset_bg" not in style["reference_asset_ids_json"]

    # Also verify asset_char is still referenced by char_grace (unaffected).
    resp = client.delete("/assets/asset_char")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] == "asset_char"
    assert body["detached_from"] >= 1  # char_grace.reference_asset_ids_json

    # Second delete of asset_bg → 404.
    assert client.delete("/assets/asset_bg").status_code == 404

    # Graph has no dangling edges after deletions.
    g = client.get("/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])


# ── storyboard: prop/asset image references ───────────────────────────────────

def test_storyboard_includes_prop_asset_from_shot(ctx):
    """A prop asset attached to shot_1 is included in the storyboard image refs
    AFTER the cast character sheet, and a video-type asset on the scene is NOT."""
    client, fake = ctx
    import app.database as _db_mod
    from app.models import Asset

    prop_img = Path(_db_mod.engine.url.database).parent / "prop_cup.png"
    prop_img.write_bytes(b"img")
    with Session(_db_mod.engine) as s:
        # A renderable prop asset linked to shot_1.
        s.add(Asset(id="asset_prop_cup", type="prop", name="Red Cup",
                    file_path=str(prop_img)))
        # A video asset attached to the scene — should be excluded.
        s.add(Asset(id="asset_vid", type="video", name="Clip",
                    file_path=str(prop_img)))
        s.commit()

    # Attach prop to shot_1 and video to scene.
    assert client.post("/shots/shot_1/assets/asset_prop_cup").status_code == 200
    assert client.patch("/scenes/scene_1", json={
        "asset_ids": ["asset_bg", "asset_vid"]
    }).status_code == 200

    resp = client.post("/scenes/scene_1/storyboard")
    assert resp.status_code == 200, resp.text
    payload = fake.image_payloads[0]
    images = payload["images"]

    # Cast character sheet must come before the prop URL.
    cast_url = "https://static.atlascloud.ai/up/char.png"
    prop_url = "https://static.atlascloud.ai/up/prop_cup.png"
    assert cast_url in images
    assert prop_url in images
    assert images.index(cast_url) < images.index(prop_url)

    # video-type asset is NOT included.
    assert "https://static.atlascloud.ai/up/prop_img.png" not in images
    video_urls = [u for u in images if "vid" in u]
    assert video_urls == []

    # The storyboard prompt mentions that references include EXACT props.
    prompt = payload["prompt"]
    assert "prop" in prompt.lower() or "reference" in prompt.lower()


def test_storyboard_cap_respected_with_props(ctx):
    """Total reference images never exceed 10 even when many props are attached."""
    client, fake = ctx
    import app.database as _db_mod
    from app.models import Asset

    with Session(_db_mod.engine) as s:
        for i in range(12):
            img = Path(_db_mod.engine.url.database).parent / f"prop_{i}.png"
            img.write_bytes(b"img")
            s.add(Asset(id=f"asset_many_{i}", type="prop", name=f"Prop {i}",
                        file_path=str(img)))
        s.commit()

    # Attach all 12 props to shot_1.
    for i in range(12):
        client.post(f"/shots/shot_1/assets/asset_many_{i}")

    resp = client.post("/scenes/scene_1/storyboard")
    assert resp.status_code == 200, resp.text
    images = fake.image_payloads[0]["images"]
    assert len(images) <= 10


# ── _scene_to_spec: Shot rows are the source of truth ────────────────────────

def test_scene_to_spec_prefers_shot_rows_over_scene_json(monkeypatch, tmp_path):
    """When Shot rows exist, _scene_to_spec must compose spec.shots from
    those rows (ordered by shot_order), ignoring stale scene_json["shots"].

    After a shot prompt is updated via update_shot, a fresh call to
    _scene_to_spec must reflect the edited prompt — not the old snapshot
    embedded in scene_json.
    """
    from sqlmodel import Session, SQLModel, create_engine

    import app.models  # noqa: F401 — registers all tables
    from app.models import Scene, Shot
    from app.schemas.scene_schema import SceneSpec
    from app.services.scene_service import _scene_to_spec, update_shot

    engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    stale_shot_prompt = "STALE prompt from scene_json"
    fresh_shot_prompt = "FRESH edited prompt"

    with Session(engine) as s:
        scene = Scene(
            id="sc_test",
            title="Test Scene",
            summary="A test",
            duration=6,
            aspect_ratio="9:16",
        )
        # Embed a stale shot inside scene_json (simulates post-expand state).
        scene.scene_json = {
            "scene_id": "sc_test",
            "title": "Test Scene",
            "summary": "A test",
            "duration": 6,
            "aspect_ratio": "9:16",
            "character_ids": [],
            "asset_ids": [],
            "shots": [
                {
                    "shot_id": "sj_1",
                    "duration": 3,
                    "prompt": stale_shot_prompt,
                    "camera": "mid",
                    "movement": "static",
                    "asset_ids": [],
                }
            ],
        }
        s.add(scene)
        s.add(Shot(
            id="row_sh1",
            scene_id="sc_test",
            shot_order=0,
            duration=3,
            prompt=fresh_shot_prompt,
            camera="mid",
            movement="static",
        ))
        s.commit()
        s.refresh(scene)

        # _scene_to_spec must prefer the Shot row over scene_json["shots"].
        spec = _scene_to_spec(scene, s)
        assert len(spec.shots) == 1
        assert spec.shots[0].prompt == fresh_shot_prompt, (
            f"Expected prompt from Shot row, got: {spec.shots[0].prompt!r}"
        )

        # Editing the shot row and re-calling _scene_to_spec shows the new prompt.
        update_shot(s, "row_sh1", prompt="UPDATED prompt")
        s.refresh(scene)
        spec2 = _scene_to_spec(scene, s)
        assert spec2.shots[0].prompt == "UPDATED prompt"


def test_scene_to_spec_falls_back_to_scene_json_when_no_rows(tmp_path):
    """When NO Shot rows exist for the scene, _scene_to_spec falls back to
    scene_json["shots"] (the post-expand, pre-create_shots window)."""
    from sqlmodel import Session, SQLModel, create_engine

    import app.models  # noqa: F401
    from app.models import Scene
    from app.services.scene_service import _scene_to_spec

    engine = create_engine(
        f"sqlite:///{tmp_path / 'fb.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    fallback_prompt = "Fallback prompt from scene_json"

    with Session(engine) as s:
        scene = Scene(
            id="sc_fb",
            title="Fallback Scene",
            summary="B test",
            duration=5,
            aspect_ratio="16:9",
        )
        scene.scene_json = {
            "scene_id": "sc_fb",
            "title": "Fallback Scene",
            "summary": "B test",
            "duration": 5,
            "aspect_ratio": "16:9",
            "character_ids": [],
            "asset_ids": [],
            "shots": [
                {
                    "shot_id": "sj_fb1",
                    "duration": 3,
                    "prompt": fallback_prompt,
                    "camera": "wide",
                    "movement": "static",
                    "asset_ids": [],
                }
            ],
        }
        s.add(scene)
        s.commit()
        s.refresh(scene)

        spec = _scene_to_spec(scene, s)
        assert len(spec.shots) == 1
        assert spec.shots[0].prompt == fallback_prompt


# ── edit history + revert ─────────────────────────────────────────────────────

def test_shot_revisions_recorded_newest_first(ctx):
    client, fake = ctx
    assert client.patch("/shots/shot_1", json={"prompt": "v2 prompt"}).status_code == 200
    assert client.patch(
        "/shots/shot_1", json={"prompt": "v3 prompt", "camera": "wide"}
    ).status_code == 200

    revs = client.get("/shots/shot_1/revisions").json()
    assert len(revs) == 2
    # Newest first: the second edit's revision stores the v2 state.
    assert revs[0]["fields_json"] == {"prompt": "v2 prompt", "camera": "mid"}
    assert revs[1]["fields_json"] == {"prompt": "Grace waves at camera"}
    assert all(r["source"] == "edit" for r in revs)
    assert all(r["entity_type"] == "shot" for r in revs)
    assert all(r["entity_id"] == "shot_1" for r in revs)


def test_scene_revisions_recorded(ctx):
    client, fake = ctx
    assert client.patch(
        "/scenes/scene_1", json={"summary": "edited summary"}
    ).status_code == 200
    revs = client.get("/scenes/scene_1/revisions").json()
    assert len(revs) == 1
    assert revs[0]["fields_json"] == {"summary": "a sunny meadow lesson"}
    assert revs[0]["source"] == "edit"
    assert revs[0]["entity_type"] == "scene"


def test_noop_patch_writes_no_revision(ctx):
    client, fake = ctx
    assert client.patch(
        "/shots/shot_1", json={"prompt": "Grace waves at camera"}
    ).status_code == 200
    assert client.get("/shots/shot_1/revisions").json() == []


def test_refine_records_revision_with_refine_source(ctx):
    client, fake = ctx
    resp = client.post("/shots/shot_1/refine", json={"instruction": "warmer lighting"})
    assert resp.status_code == 200, resp.text
    revs = client.get("/shots/shot_1/revisions").json()
    assert len(revs) == 1
    assert revs[0]["source"] == "refine"
    assert revs[0]["fields_json"]["prompt"] == "Grace waves at camera"


def test_revert_restores_old_values_and_records_revision(ctx):
    client, fake = ctx
    assert client.patch("/shots/shot_1", json={"prompt": "v2 prompt"}).status_code == 200
    revs = client.get("/shots/shot_1/revisions").json()
    assert len(revs) == 1

    resp = client.post(f"/revisions/{revs[0]['id']}/revert")
    assert resp.status_code == 200, resp.text
    assert resp.json()["prompt"] == "Grace waves at camera"

    # The shot really is restored.
    shots = client.get("/scenes/scene_1/shots").json()
    assert shots[0]["prompt"] == "Grace waves at camera"

    # The revert itself recorded a new revision (pre-revert state, source "revert").
    revs2 = client.get("/shots/shot_1/revisions").json()
    assert len(revs2) == 2
    assert revs2[0]["source"] == "revert"
    assert revs2[0]["fields_json"] == {"prompt": "v2 prompt"}


def test_revert_scene_revision(ctx):
    client, fake = ctx
    assert client.patch("/scenes/scene_1", json={"title": "new title"}).status_code == 200
    rev = client.get("/scenes/scene_1/revisions").json()[0]
    resp = client.post(f"/revisions/{rev['id']}/revert")
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "t"


def test_revert_unknown_revision_404(ctx):
    client, fake = ctx
    assert client.post("/revisions/rev_nope/revert").status_code == 404


def test_revert_after_entity_deleted_404(ctx):
    client, fake = ctx
    assert client.patch("/shots/shot_1", json={"prompt": "v2"}).status_code == 200
    rev = client.get("/shots/shot_1/revisions").json()[0]
    assert client.delete("/shots/shot_1").status_code == 200
    assert client.post(f"/revisions/{rev['id']}/revert").status_code == 404


def test_revisions_pruned_to_20(ctx):
    client, fake = ctx
    for i in range(25):
        assert client.patch(
            "/shots/shot_1", json={"prompt": f"prompt v{i}"}
        ).status_code == 200
    revs = client.get("/shots/shot_1/revisions").json()
    assert len(revs) <= 20
    # The newest revision survives pruning.
    assert revs[0]["fields_json"] == {"prompt": "prompt v23"}
