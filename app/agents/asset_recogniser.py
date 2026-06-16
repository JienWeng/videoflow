"""Asset recogniser agent.

Foundation phase: structures an uploader-supplied description into AssetMetadata.
(True vision — feeding the image bytes to a vision model — is a flagged follow-up.)
"""

from __future__ import annotations

from app.agents.base import as_block, gated_block, run_agent
from app.schemas import AssetMetadata


async def recognise_asset(
    *,
    asset_id: str,
    filename: str,
    description: str,
    known_character_ids: list[str] | None = None,
    client=None,
) -> AssetMetadata:
    prompt = "\n\n".join(
        [
            as_block("Asset id", asset_id),
            as_block("Filename", filename),
            as_block("Uploader description", description),
            *gated_block(
                "asset_recogniser",
                "known_character_ids",
                "Known character ids",
                known_character_ids,
            ),
            "Produce AssetMetadata. Set asset_id to the given id. Only set "
            "character_id if the description clearly references one of the known "
            "character ids.",
        ]
    )
    return await run_agent(
        agent="asset_recogniser",
        response_model=AssetMetadata,
        user_prompt=prompt,
        client=client,
    )
