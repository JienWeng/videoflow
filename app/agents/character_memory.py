"""Character memory agent — builds a CharacterBible."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import CharacterBible


async def build_character_bible(
    *,
    character_id: str,
    name: str,
    notes: str,
    reference_asset_descriptions: list[str] | None = None,
    reference_asset_ids: list[str] | None = None,
    client=None,
) -> CharacterBible:
    prompt = "\n\n".join(
        [
            as_block("Character id", character_id),
            as_block("Name", name),
            as_block("Creator notes", notes),
            as_block(
                "Reference asset descriptions", reference_asset_descriptions or []
            ),
            as_block("Reference asset ids", reference_asset_ids or []),
            "Produce a CharacterBible. Set character_id and reference_asset_ids "
            "from the given values. Make visual_rules concrete and reproducible.",
        ]
    )
    return await run_agent(
        agent="character_memory",
        response_model=CharacterBible,
        user_prompt=prompt,
        client=client,
    )
