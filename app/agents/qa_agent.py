"""QA agent — judge a rendered output against its requirements."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.schemas import QAResult


async def review_output(
    *,
    requirements: str,
    output_description: str,
    frames_available: int,
    client=None,
) -> QAResult:
    prompt = "\n\n".join(
        [
            as_block("Scene/shot requirements", requirements),
            as_block("Description of the rendered output", output_description),
            as_block("Sample frames available for review", frames_available),
            "Judge the output against the requirements and return a QAResult. If "
            "frames are unavailable, judge prompt/spec compliance conservatively "
            "and note the limitation in issues.",
        ]
    )
    return await run_agent(
        agent="qa_agent",
        response_model=QAResult,
        user_prompt=prompt,
        client=client,
    )
