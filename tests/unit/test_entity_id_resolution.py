"""Unit tests: resolve_entity_ids maps LLM-invented ids onto real DB rows.

The scene/shot agents sometimes hallucinate name-like ids ("asset_教室",
"char_Grace") instead of using real ids from the context. resolve_entity_ids
treats unknown ids as names — strips a leading asset_/char_/character_ prefix
and matches against Asset.name / Character.name (whitespace-normalized,
casefolded) — so the persisted lists only ever contain REAL row ids.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401  (register tables)
from app.models import Asset, Character
from app.services.scene_service import resolve_entity_ids


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Asset(id="asset_real1", type="background", name="教室"))
        s.add(Asset(id="asset_real2", type="prop", name="Red  Cup"))
        s.add(Character(id="char_real1", name="Grace"))
        s.add(Character(id="char_real2", name="乐乐"))
        s.commit()
        yield s


def test_real_ids_pass_through(session):
    assert resolve_entity_ids(session, ["asset_real1"], kind="asset") == ["asset_real1"]
    assert resolve_entity_ids(session, ["char_real1"], kind="character") == ["char_real1"]


def test_hallucinated_asset_id_resolved_by_name(session):
    assert resolve_entity_ids(session, ["asset_教室"], kind="asset") == ["asset_real1"]


def test_hallucinated_character_id_resolved_by_name(session):
    assert resolve_entity_ids(session, ["char_Grace"], kind="character") == ["char_real1"]
    assert resolve_entity_ids(session, ["character_乐乐"], kind="character") == ["char_real2"]


def test_bare_name_without_prefix_resolved(session):
    assert resolve_entity_ids(session, ["教室"], kind="asset") == ["asset_real1"]


def test_name_match_is_casefolded_and_whitespace_normalized(session):
    assert resolve_entity_ids(session, ["asset_red cup"], kind="asset") == ["asset_real2"]
    assert resolve_entity_ids(session, ["RED  CUP"], kind="asset") == ["asset_real2"]


def test_unresolvable_ids_dropped(session):
    assert resolve_entity_ids(session, ["asset_nonexistent"], kind="asset") == []
    assert resolve_entity_ids(session, ["char_nobody"], kind="character") == []


def test_order_preserved_and_deduped(session):
    out = resolve_entity_ids(
        session,
        ["asset_real2", "asset_教室", "asset_real1", "asset_bogus", "asset_real2"],
        kind="asset",
    )
    assert out == ["asset_real2", "asset_real1"]


def test_empty_and_none_inputs(session):
    assert resolve_entity_ids(session, [], kind="asset") == []
