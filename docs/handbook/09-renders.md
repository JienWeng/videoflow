# 9. Render jobs and outputs

[Handbook](README.md) · Previous: [Studio](08-studio.md) · Next: [Captions and editor](10-captions-editor.md)

Open **My videos** to monitor scene jobs, compare outputs, and download media. A job is an attempt; an output is a local result from a successful attempt.

## Understand completion

| State or stage | Meaning |
|---|---|
| Create operation succeeded | Planning and submission finished; video jobs may still be running |
| Pending/running | The provider request is queued or generating |
| Downloading | VideoFlow is retrieving the provider output |
| QA | The app is attempting a visual review |
| Succeeded | Output handling finished and QA was attempted |
| Failed | Read the error to identify submission, polling, or download failure |

Succeeded does not guarantee that QA passed. QA is best effort and can be absent when its model, FFmpeg, or frame extraction is unavailable.

## Review a take

1. Select the scene group in My videos.
2. Play the output and inspect identity, action, visual artifacts, timing, and speech.
3. Review available QA issues and score.
4. Select the take you want to keep where offered. Selection is scoped to a job's outputs, not a project-wide final edit.
5. Download the **original** video, or the captioned variant after generating captions.

## Retry deliberately

A failed-job **resubmit** reconstructs the saved render spec and sends another provider request. A corrective output retry adds QA feedback. Either can create a new charge. A download failure can happen after the provider already generated and billed a video; inspect that job before paying for another generation.

The current provider migration also changes how saved specs map to payloads. A stored Kling-shaped request does not guarantee that resubmission sends the historical Kling payload. This is an audit blocker for reliable replay.

## What is currently missing

There is no complete whole-project movie assembly/export flow. Render outputs are per scene or shot. There is no end-to-end cancellation/resume contract for every orchestration stage. Restart reconciliation can re-enqueue video polling, while interrupted non-render operations are marked failed.

For OpenRouter, the worker retrieves video through the authenticated content endpoint. The contract is covered by mocked tests, but a live generation and download has not been run. A provider may complete and bill a job even if later local processing fails; inspect the job before resubmitting.
