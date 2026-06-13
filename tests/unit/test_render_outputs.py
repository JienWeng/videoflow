"""Unit tests for the 'finished video out' helpers: download filename/path
slugging, provider-error humanizing, and resolver-backed render defaults."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.errors import NotFoundError, ValidationFailedError
from app.models import RenderJob, RenderOutput, RenderStatus, Scene
from app.providers.polling import humanize_provider_error
from app.services import render_service


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Provider error humanizing
# ---------------------------------------------------------------------------
class TestHumanizeProviderError:
    def test_ret_1201_maps_to_reference_image_guidance(self):
        out = humanize_provider_error(
            "AtlasCloud /model/generateVideo failed: ret:1201 max number is 7"
        )
        assert "reference image" in out["message"].lower()
        assert "7" in out["action"]
        assert out["code"] == "ret:1201"
        assert out["raw"].startswith("AtlasCloud")

    def test_timeout_maps_to_retry(self):
        out = humanize_provider_error("generation timed out after 600.0s")
        assert "time" in out["message"].lower()
        assert "retry" in out["action"].lower()

    def test_sensitive_content_flagged(self):
        out = humanize_provider_error("ret:1004 sensitive content detected")
        assert "sensitive" in out["message"].lower()
        assert out["code"] == "ret:1004"

    def test_unknown_error_falls_back_to_raw_with_generic_action(self):
        out = humanize_provider_error("something weird happened")
        assert out["message"] == "something weird happened"
        assert out["action"]
        assert out["code"] is None

    def test_empty_error(self):
        out = humanize_provider_error("")
        assert out["message"]
        assert out["action"]
        assert out["code"] is None
        assert humanize_provider_error(None)["message"]


# ---------------------------------------------------------------------------
# Download filename + path
# ---------------------------------------------------------------------------
def _seed_output(session, *, title="", video=None, captioned=None) -> RenderOutput:
    scene = Scene(title=title, summary="s")
    session.add(scene)
    session.commit()
    job = RenderJob(scene_id=scene.id, status=RenderStatus.succeeded)
    session.add(job)
    session.commit()
    output = RenderOutput(
        render_job_id=job.id,
        video_path=str(video) if video else None,
        captioned_path=str(captioned) if captioned else None,
    )
    session.add(output)
    session.commit()
    session.refresh(output)
    return output


class TestDownloadFilename:
    def test_uses_slugified_scene_title_and_output_id(self, session):
        out = _seed_output(session, title="乐乐的冒险 Big Day!")
        name = render_service.download_filename(session, out, "raw")
        assert name.endswith(".mp4")
        assert out.id in name
        assert "乐乐的冒险-Big-Day" in name

    def test_captioned_variant_has_suffix(self, session):
        out = _seed_output(session, title="Scene One")
        name = render_service.download_filename(session, out, "captioned")
        assert name.endswith("-captioned.mp4")
        assert "Scene-One" in name

    def test_falls_back_to_output_id_without_title(self, session):
        out = _seed_output(session, title="")
        name = render_service.download_filename(session, out, "raw")
        assert name == f"{out.id}.mp4"


class TestDownloadPath:
    def test_raw_path_returned_when_present(self, session, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        out = _seed_output(session, video=video)
        assert render_service.download_path(out, "raw") == video

    def test_captioned_missing_raises_not_found(self, session, tmp_path):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        out = _seed_output(session, video=video)  # never captioned
        with pytest.raises(NotFoundError):
            render_service.download_path(out, "captioned")

    def test_missing_file_on_disk_raises_not_found(self, session, tmp_path):
        out = _seed_output(session, video=tmp_path / "gone.mp4")
        with pytest.raises(NotFoundError):
            render_service.download_path(out, "raw")

    def test_unknown_variant_rejected(self, session, tmp_path):
        out = _seed_output(session, video=tmp_path / "v.mp4")
        with pytest.raises(ValidationFailedError):
            render_service.download_path(out, "bogus")


# ---------------------------------------------------------------------------
# Selected take
# ---------------------------------------------------------------------------
class TestSelectOutput:
    def test_selecting_one_deselects_siblings(self, session):
        scene = Scene(title="t", summary="s")
        session.add(scene)
        session.commit()
        job = RenderJob(scene_id=scene.id, status=RenderStatus.succeeded)
        session.add(job)
        session.commit()
        a = RenderOutput(render_job_id=job.id, video_path="/a.mp4", selected=True)
        b = RenderOutput(render_job_id=job.id, video_path="/b.mp4")
        session.add(a)
        session.add(b)
        session.commit()
        session.refresh(a)
        session.refresh(b)

        render_service.select_output(session, b.id, True)
        session.refresh(a)
        session.refresh(b)
        assert b.selected is True
        assert a.selected is False

    def test_can_clear_selection(self, session):
        scene = Scene(title="t", summary="s")
        session.add(scene)
        session.commit()
        job = RenderJob(scene_id=scene.id, status=RenderStatus.succeeded)
        session.add(job)
        session.commit()
        a = RenderOutput(render_job_id=job.id, video_path="/a.mp4", selected=True)
        session.add(a)
        session.commit()
        session.refresh(a)
        render_service.select_output(session, a.id, False)
        session.refresh(a)
        assert a.selected is False

    def test_unknown_output_raises(self, session):
        with pytest.raises(NotFoundError):
            render_service.select_output(session, "out_nope", True)


# ---------------------------------------------------------------------------
# Resolver-backed render defaults
# ---------------------------------------------------------------------------
class TestResolveRenderDefaults:
    def test_dialogue_language_defaults_to_config(self, session):
        # No app_settings rows + no project -> config default (dialogue_language=zh),
        # humanized to its English name for the prompt ("zh" -> "Chinese").
        assert render_service.resolve_dialogue_language(session) == "Chinese"

    def test_dialogue_language_honours_global_override(self, session):
        from app.services import settings_service

        settings_service.set_app_setting(session, "dialogue_language", "French")
        assert render_service.resolve_dialogue_language(session) == "French"

    def test_negatives_default_to_prompt_agent_constants(self, session):
        from app.agents.prompt_agent import NO_CLONE_NEGATIVE, NO_TEXT_NEGATIVE

        no_text, no_clone, extras = render_service.resolve_render_negatives(session)
        assert no_text == NO_TEXT_NEGATIVE
        assert no_clone == NO_CLONE_NEGATIVE
        assert extras == []

    def test_extra_negatives_from_render_negatives_setting(self, session):
        from app.services import settings_service

        settings_service.set_app_setting(
            session, "render_negatives", ["no blur", "no motion smear"]
        )
        _, _, extras = render_service.resolve_render_negatives(session)
        assert extras == ["no blur", "no motion smear"]
