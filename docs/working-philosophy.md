# Working philosophy

VideoFlow should help a person move from an idea to inspectable production artifacts, then to a video they deliberately accept. Its strongest foundation is the shared workspace: characters, assets, scenes, shots, and outputs remain available across guided and manual workflows.

## Product principles

### Make the next step obvious

A beginner should see what is required, what happens next, and what completion means. Start with one short scene. Present provider credentials and a verified model selection before paid generation. Reveal protocols, per-agent routing, references, and negative prompts when users need that control.

The current Create/Advanced navigation is a useful foundation. Missing readiness checks, delayed progress, and ambiguous narration controls undermine it. The handbook documents those gaps; the backlog defines the repairs.

### Keep work inspectable and recoverable

Each step should produce an artifact that can be examined, edited, and reused. Retry the failed stage without discarding good work. Persist operation progress and pin its project so refreshes, restarts, and project switches cannot silently change the production context.

Current services persist intermediate rows, but orchestration does not have resumable checkpoints. A future resume action needs explicit stage/input identity and idempotency, not merely another call to Create video.

### Make provider capabilities part of the contract

A model's duration, dimensions, reference modes, audio behavior, and output retrieval rules belong in its adapter and capability data. The UI should derive valid controls from those capabilities. Unknown models should be identified as unverified; a typed model ID should not imply that any adapter can serve it.

Stored character sheets are only effective visual constraints when the chosen model receives them in the intended reference mode. Text descriptions, first/last frames, and style references have different meanings. Do not silently substitute one for another.

### Spend deliberately

Review text before images, and images before video. Reuse suitable assets. Explain which action makes remote requests and whether retrying repeats paid generation. A failed local download should recover the existing remote result where possible.

The current app has no complete budget/usage summary or generation-wide cost estimate. That is a product gap, not a property provided by schema validation.

### Use AI for proposals and application code for execution

Agents produce validated data. Services own persistence, authorization boundaries, sequencing, and provider calls. Guided chat should show the intended action and entity before execution. Structural validation helps contain malformed replies; semantic correctness and visual quality need separate review.

### Be precise about local operation

SQLite and media live locally. Configured services receive prompts and selected references. The application currently targets one local user and has a server-wide active project. Public multi-user use needs authentication, project-bound operations, access checks, and deployment work.

## Engineering rules to apply next

1. Centralize provider/model/settings resolution across every generation path.
2. Preserve adapter contracts when adding a new model family; changing a default must not erase a supported workflow unnoticed.
3. Pin project IDs at operation creation and pass them through downstream work.
4. Persist progress and artifact IDs at meaningful stage boundaries.
5. Treat download, QA, captions, and generation as distinct recoverable stages.
6. Test provider contracts with realistic mocked responses and label paid live verification separately.
7. Keep user instructions synchronized with actual UI names and capability limits.
8. Keep uncertainty explicit: implemented, tested locally, live verified, partial, and planned describe different evidence.

## Definition of a dependable first-video workflow

A user on a fresh installation can configure a supported route, create an empty project, submit one short story, see truthful progress, retrieve a playable output, and export the work. Unsupported choices are rejected before paid generation. Refresh and failure recovery preserve the active operation. The same walkthrough is documented and repeatable.

That definition is the next delivery target. Current source, test failures, and unavailable live checks do not justify marking it achieved. See the [prioritized backlog](audits/2026-09-27-implementation.md).
