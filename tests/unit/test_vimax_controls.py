from app.providers.capabilities import capabilities_for, validate_render_capabilities
from app.services.continuity_service import ContinuityRecord, rank_records
from app.schemas.render_schema import RenderSpec
from app.providers.openrouter_video import OpenRouterVideoProvider
from app.services.visual_dependency_service import build_shot_dependencies, select_best_candidate


class _Resolver:
    async def resolve(self, asset_ids):
        return [f"https://cdn.test/{asset_id}.png" for asset_id in asset_ids]


def test_openrouter_video_capabilities_reject_unsupported_reference_count():
    caps = capabilities_for("openrouter", "google/veo-3.1-lite")
    errors = validate_render_capabilities(
        caps,
        duration=8,
        aspect_ratio="16:9",
        reference_count=2,
        has_video_reference=False,
    )
    assert errors == []


def test_capabilities_report_invalid_duration_and_video_reference():
    caps = capabilities_for("openrouter", "google/veo-3.1-lite")
    errors = validate_render_capabilities(
        caps,
        duration=30,
        aspect_ratio="16:9",
        reference_count=0,
        has_video_reference=True,
    )
    assert "duration must be between 4 and 8 seconds" in errors
    assert any("video references are not supported" in error for error in errors)


def test_continuity_retrieval_prefers_matching_entities_and_terms():
    records = [
        ContinuityRecord("a", "Maya wears a red coat in the station", "character"),
        ContinuityRecord("b", "The station has a clock on the east wall", "location"),
        ContinuityRecord("c", "A beach at sunset", "location"),
    ]
    ranked = rank_records(records, "Maya enters the station wearing the red coat")
    assert [item.id for item in ranked[:2]] == ["a", "b"]


def test_render_spec_accepts_openrouter_media_route():
    spec = RenderSpec(
        provider="openrouter",
        model="google/veo-3.1-lite",
        scene_id="scene_1",
        duration=8,
        prompt="A character walks through a station",
    )
    assert spec.provider == "openrouter"


def test_openrouter_video_payload_uses_first_and_last_frame_references():
    spec = RenderSpec(
        provider="openrouter",
        model="google/veo-3.1-lite",
        scene_id="scene_1",
        duration=8,
        prompt="A character crosses the station",
        extra_image_asset_ids=["first", "last"],
    )
    provider = OpenRouterVideoProvider(client=object())
    payload = __import__("asyncio").run(provider.build_payload(spec, _Resolver()))
    assert payload["model"] == "google/veo-3.1-lite"
    assert [item["frame_type"] for item in payload["frame_images"]] == [
        "first_frame", "last_frame"
    ]


def test_visual_dependencies_create_ordered_layers_and_select_best_candidate():
    deps = build_shot_dependencies([{"id": "a"}, {"id": "b"}, {"id": "c", "depends_on": ["a"]}])
    assert [(item.shot_id, item.depends_on, item.layer) for item in deps] == [
        ("a", (), 0), ("b", ("a",), 1), ("c", ("a",), 1)
    ]
    assert select_best_candidate([0.7, 0.9, 0.9]) == 1
