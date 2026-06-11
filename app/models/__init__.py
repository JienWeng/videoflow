"""SQLModel table definitions. Importing this package registers all tables."""

from app.models.asset import Asset
from app.models.character import Character
from app.models.op import Op
from app.models.render_job import RenderJob, RenderStatus
from app.models.render_output import RenderOutput
from app.models.scene import Scene
from app.models.script import Script
from app.models.shot import Shot
from app.models.style_guide import StyleGuide

__all__ = [
    "Asset",
    "Character",
    "Op",
    "RenderJob",
    "RenderStatus",
    "RenderOutput",
    "Scene",
    "Script",
    "Shot",
    "StyleGuide",
]
