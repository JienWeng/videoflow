"""Library product-grade behaviour: canonical asset taxonomy and character edit.

Pure-service tests (no LLM, no network) covering the taxonomy reconciliation and
the new character PATCH path. The single canonical vocabulary lives in
app.schemas.common.ASSET_TYPES and is the only source the upload dropdown, the
recogniser enum, and the type filter agree on.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.errors import ValidationFailedError
from app.schemas.common import ASSET_TYPES
from app.services import asset_service, character_service


@pytest.fixture
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_canonical_vocabulary_is_the_expected_set():
    assert set(ASSET_TYPES) == {
        "prop",
        "background",
        "character_reference",
        "storyboard",
        "video",
        "effect",
        "tool",
        "other",
    }


@pytest.mark.parametrize("known", list(ASSET_TYPES))
def test_canonical_type_passes_known_values_through(known):
    assert asset_service.canonical_type(known) == known


@pytest.mark.parametrize("unknown", ["location", "video_reference", "frame", "", None])
def test_canonical_type_collapses_unknown_to_other(unknown):
    assert asset_service.canonical_type(unknown) == "other"


def test_update_character_partial_and_lists(session):
    char = character_service.create_character(
        session, name="Lele", description="kid"
    )
    out = character_service.update_character(
        session,
        char.id,
        appearance="round face, red hoodie",
        visual_rules=["always red hoodie", "short black hair"],
    )
    assert out.appearance == "round face, red hoodie"
    assert out.visual_rules_json == ["always red hoodie", "short black hair"]
    # untouched fields preserved
    assert out.name == "Lele"
    assert out.description == "kid"


def test_update_character_rejects_blank_name(session):
    char = character_service.create_character(session, name="Lele")
    with pytest.raises(ValidationFailedError):
        character_service.update_character(session, char.id, name="   ")


def test_update_character_unknown_id_raises(session):
    from app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        character_service.update_character(session, "char_missing", name="x")
