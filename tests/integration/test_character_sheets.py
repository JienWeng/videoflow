"""Character reference-sheet generation honors the project style guide.

Sheets are the dominant style anchor (they feed the storyboard, asset gen and
Kling reference-to-video), so the style guide must reach their ERNIE prompts —
and when style reference assets are pinned, the edit (reference) model must be
used so sheets match the look exactly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.config import get_settings
from app.database import get_session
from app.schemas import CharacterBible


class FakeLLM:
    def __init__(self):
        self.prompts: list[str] = []

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.prompts.append(user_prompt)
        assert response_model is CharacterBible
        return CharacterBible(
            character_id="char_grace",
            name="Grace",
            appearance="girl in pink dress",
            personality="curious and kind",
        )


class FakeAtlas:
    def __init__(self):
        self.image_payloads: list[dict] = []
        self.uploads: list[str] = []
        self._n = 0

    async def upload_media(self, file_path: str) -> str:
        self.uploads.append(file_path)
        return f"https://static.atlascloud.ai/up/{self._n}.png"

    async def generate_image(self, payload: dict) -> dict:
        self.image_payloads.append(payload)
        self._n += 1
        return {"id": f"img_{self._n}", "status": "completed",
                "outputs": [f"https://static.atlascloud.ai/gen/{self._n}.png"]}

    async def get_prediction(self, pid: str) -> dict:
        return {"status": "completed", "outputs": []}


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
    monkeypatch.setattr("app.services.character_service.get_atlas_client", lambda: fake)
    monkeypatch.setattr("app.providers.atlascloud_image.get_atlas_client", lambda: fake)
    fake_llm = FakeLLM()
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: fake_llm)

    async def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake")
        return dest

    monkeypatch.setattr("app.services.media.download", fake_download)

    from app.models import Asset, Character

    (tmp_path / "styleref.png").write_bytes(b"img")
    with Session(engine) as s:
        s.add(Character(id="char_grace", name="Grace",
                        appearance="girl in pink dress",
                        visual_rules_json=["always wears a pink dress"]))
        s.add(Asset(id="asset_styleref", type="style_reference", name="Look",
                    file_path=str(tmp_path / "styleref.png")))
        s.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c, fake, fake_llm, engine


def _seed_style(engine, **kw):
    from app.models import StyleGuide

    with Session(engine) as s:
        s.add(StyleGuide(**kw))
        s.commit()


def test_sheets_without_style_use_plain_ernie(ctx):
    client, fake, _, _ = ctx
    resp = client.post("/characters/char_grace/reference-sheets", json={})
    assert resp.status_code == 200, resp.text
    assert len(fake.image_payloads) == 4  # default angles
    settings = get_settings()
    for payload in fake.image_payloads:
        assert payload["model"] == settings.atlas_image_model
        assert "Style:" not in payload["prompt"]
        assert "images" not in payload


def test_sheets_apply_style_text(ctx):
    client, fake, _, engine = ctx
    _seed_style(engine, style_prompt="3D cartoon, soft pastel")
    resp = client.post("/characters/char_grace/reference-sheets",
                       json={"angles": ["front view", "side view"]})
    assert resp.status_code == 200, resp.text
    assert len(fake.image_payloads) == 2
    settings = get_settings()
    for payload in fake.image_payloads:
        # No pinned style refs -> plain ERNIE model, styled prompt.
        assert payload["model"] == settings.atlas_image_model
        assert "3D cartoon, soft pastel" in payload["prompt"]
        assert "Grace" in payload["prompt"]


def test_sheets_use_reference_model_when_style_refs_pinned(ctx):
    client, fake, _, engine = ctx
    _seed_style(
        engine,
        style_prompt="3D cartoon, soft pastel",
        reference_asset_ids_json=["asset_styleref"],
    )
    resp = client.post("/characters/char_grace/reference-sheets",
                       json={"angles": ["front view"]})
    assert resp.status_code == 200, resp.text
    settings = get_settings()
    payload = fake.image_payloads[0]
    assert payload["model"] == settings.atlas_image_ref_model
    assert payload["images"]  # the uploaded style ref URL
    assert payload["images"][0].startswith("https://static.atlascloud.ai/up/")
    assert payload["prompt"].startswith(
        "Match the visual style of the attached reference images exactly. "
    )
    assert "3D cartoon, soft pastel" in payload["prompt"]
    # The local style ref was uploaded once.
    assert fake.uploads and fake.uploads[0].endswith("styleref.png")


def test_bible_agent_receives_style_block(ctx):
    client, _, fake_llm, engine = ctx
    _seed_style(engine, style_prompt="3D cartoon", audience="children 2-6", tone="playful")
    resp = client.post("/characters/char_grace/bible", json={"notes": "a curious girl"})
    assert resp.status_code == 200, resp.text
    prompt = fake_llm.prompts[0]
    assert "Project style guide" in prompt
    assert "children 2-6" in prompt
