"""QA agent — judge a rendered output against its requirements.

Vision-first: extracted video frames plus the reference images that drove the
render (character sheets, 分镜图) are attached to the prompt so the model judges
what was actually generated, not a textual description of it.
"""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import QAResult


async def review_output(
    *,
    requirements: str,
    output_description: str,
    frames: list[str] | None = None,
    reference_images: list[str] | None = None,
    client=None,
) -> QAResult:
    frames = frames or []
    reference_images = reference_images or []
    prompt = "\n\n".join(
        [
            as_block("Scene/shot requirements", requirements),
            as_block("Description of the rendered output", output_description),
            as_block(
                "Attached images",
                f"The first {len(reference_images)} image(s) are the REFERENCES "
                f"(character sheets / storyboard) the render had to follow; the "
                f"remaining {len(frames)} are FRAMES sampled from the rendered "
                "video in chronological order."
                if reference_images or frames
                else "none — no frames could be extracted",
            ),
            "Compare the frames against the references and requirements: same "
            "characters (faces, outfits, proportions), continuous scene, "
            "consistent lighting, camera/shot structure as scripted, and no "
            "artifacts or on-screen text. Return a QAResult. If no images are "
            "attached, judge prompt/spec compliance conservatively and note the "
            "limitation in issues.",
        ]
    )
    return await run_agent(
        agent="qa_agent",
        response_model=QAResult,
        user_prompt=prompt,
        images=[*reference_images, *frames] or None,
        client=client,
    )
