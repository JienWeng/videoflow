"""Vision reviser — sees the flawed render's frames + the references and emits a
TARGETED RenderSpecPatch (fix the offending shot / reference), replacing the old
blind prompt-suffix retry."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas.render_patch_schema import RenderSpecPatch


async def revise_spec(
    *,
    spec,
    qa_result: dict,
    frames: list[str] | None = None,
    reference_images: list[str] | None = None,
    target: str | None = None,
    client=None,
) -> RenderSpecPatch:
    frames = frames or []
    reference_images = reference_images or []
    prompt = "\n\n".join(
        [
            as_block("Current render spec", spec.model_dump(mode="json")),
            as_block("QA issues", qa_result.get("issues") or []),
            as_block("Weakest dimension to fix", target or "overall"),
            as_block(
                "Attached images",
                f"The first {len(reference_images)} are the REFERENCE images the "
                f"render had to follow; the remaining {len(frames)} are FRAMES from "
                "the flawed render in order.",
            ),
            "Emit the SMALLEST RenderSpecPatch that fixes the weakest dimension: "
            "rewrite only the offending shot(s) by 1-based index; to fix a "
            "character that drifted, 'swap'/'strengthen' that character's EXISTING "
            "@name reference (NEVER add a new name — it clones); keep 「」 dialogue. "
            "Leave good shots untouched.",
        ]
    )
    return await run_agent(
        agent="spec_reviser",
        response_model=RenderSpecPatch,
        user_prompt=prompt,
        images=[*reference_images, *frames] or None,
        client=client,
    )
