"""Pydantic wire/agent schemas — the structured outputs the AI must produce.

These are deliberately separate from the SQLModel tables in `app.models`:
agent output shape must not be coupled to DB shape (the `*_json` columns).
"""

from app.schemas.asset_plan import AssetPlan, PlannedAsset
from app.schemas.asset_schema import AssetMetadata
from app.schemas.character_schema import CharacterBible
from app.schemas.intent import Intent, IntentAction
from app.schemas.qa_schema import QAResult
from app.schemas.refine import SceneRefinement, ShotRefinement
from app.schemas.render_schema import ReferenceImage, RenderSpec, StoryboardShot
from app.schemas.scene_schema import SceneSpec, ScriptDraft, ScriptScene, ShotSpec
from app.schemas.shot_schema import ShotList
from app.schemas.style import StyleSpec

__all__ = [
    "AssetMetadata",
    "AssetPlan",
    "PlannedAsset",
    "CharacterBible",
    "Intent",
    "IntentAction",
    "QAResult",
    "ReferenceImage",
    "RenderSpec",
    "StoryboardShot",
    "SceneRefinement",
    "SceneSpec",
    "ShotRefinement",
    "ScriptDraft",
    "ScriptScene",
    "ShotSpec",
    "ShotList",
    "StyleSpec",
]
