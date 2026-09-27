# Implementation audit — 27 September 2026

[Handbook](../handbook/README.md) · [OpenRouter](2026-09-27-openrouter.md) · [UI](2026-09-27-ui.md) · [Verification](2026-09-27-verification.md) · [Philosophy](../working-philosophy.md)

## Scope and conclusion

Reviewed the current working tree on top of `011641f`, including pre-existing uncommitted OpenRouter, H3/GPT Image, settings, and continuity changes. This is a documentation and readiness audit. The implementation snapshot is preserved for review; the findings below are not marked fixed by publishing this report.

**The workspace and authoring foundation are substantial. The new media-provider migration is incomplete, and the full guided workflow is not yet release-ready.** OpenRouter-only operation cannot currently be claimed. Local verification found **582 passing backend tests and 23 failures**; frontend check/build passed. No paid live model call or graphical walkthrough was performed.

“Implemented” below means code and relevant entry points exist. It does not mean all models, operating systems, or end-to-end cases were verified.

## What is completed, partial, and missing

| Area | State | Evidence and practical boundary |
|---|---|---|
| Local API, SQLite, storage initialization | Implemented; empty-database smoke passed | [main](../../app/main.py), [database](../../app/database.py); local health and empty lists returned 200 |
| Projects, activation, rename, export/import | Implemented | [project API](../../app/api/projects.py), [service](../../app/services/project_service.py); active selection is server-wide |
| Asset upload, metadata, reuse and links | Implemented | [asset service](../../app/services/asset_service.py), [asset generation](../../app/services/asset_gen_service.py) |
| True asset image/video/audio recognition | Missing | [recogniser](../../app/agents/asset_recogniser.py) only receives user description and filename |
| Character bibles and reference sheets | Implemented with provider limitation | [character service](../../app/services/character_service.py); sheets select AtlasCloud directly |
| Script, scene, shot generation and refinement | Implemented | [scene service](../../app/services/scene_service.py), [refine service](../../app/services/refine_service.py); external quality not verified |
| Project style and reference-guided storyboards | Implemented with routing gaps | [style service](../../app/services/style_service.py), [storyboards](../../app/services/storyboard_service.py) |
| Guided Create video pipeline | Partial | [orchestrator](../../app/services/video_generation_service.py); stores artifacts and submits scene jobs, but progress/recovery/narration are incomplete |
| Guided chat and relationship canvas | Implemented | [chat service](../../app/services/chat_service.py), [Studio](../../frontend/src/routes/+page.svelte); browser interaction unverified |
| LLM connections, overrides, schema validation | Implemented; model-dependent | [connections](../../app/llm/connections.py), [structured client](../../app/llm/structured_client.py); tests are not live provider certification |
| AtlasCloud video adapter migration | Partial/regressed | [adapter](../../app/providers/atlascloud_video.py) now emits H3 payloads; older reference/multi-shot contracts no longer hold |
| OpenRouter media support | Partial/blocking gaps | Dedicated adapters exist; see [compatibility matrix](2026-09-27-openrouter.md) |
| Render queue, polling and downloads | Implemented with provider gap | [worker](../../app/jobs/worker.py), [poll service](../../app/services/poll_service.py); OpenRouter content authentication missing |
| QA and corrective retry | Implemented, best effort | [QA agent](../../app/agents/qa_agent.py); sampled images, not direct audio review; retries affected by adapter migration |
| Captions and output editor | Implemented; actual media run unverified here | [caption service](../../app/services/caption_service.py), [editor](../../frontend/src/routes/editor/[id]/+page.svelte) |
| Local continuity retrieval | Implemented | [continuity service](../../app/services/continuity_service.py) ranks lexical overlap; no persistent vector index |
| Remote embeddings and reranking | Scaffold only | [remote retrieval](../../app/services/remote_retrieval_service.py) has methods but no production call site found |
| Shot dependencies | Partial | Metadata is stored; forward edges crash and no generation scheduler consumes the layers |
| Best-of-k generation/selection | Missing integration | `select_best_candidate` exists as a helper; no production call site found |
| Whole-project assembled movie | Missing | Guided creation returns scene render IDs; no stitching stage |
| Resumable orchestration/cancellation | Missing complete contract | [ops](../../app/services/op_service.py) marks interrupted ops failed; render polling recovery is separate |
| Multi-user/public deployment | Outside current implementation | No application authentication; one server-wide active project |
| Beginner documentation | Added in this audit | [12-part handbook](../handbook/README.md) and [working philosophy](../working-philosophy.md) |

## Highest-priority findings

### F01 — OpenRouter video output cannot follow the documented download flow (P1)

**Evidence:** `process_job` in [poll_service.py](../../app/services/poll_service.py) passes the provider URL to `media.download`. [media.py](../../app/services/media.py) makes an unauthenticated GET. OpenRouter's content URLs require its API credential; details and primary source are in the compatibility report.

**Impact:** generation can succeed remotely and be billed, then fail to produce a local output. Resubmitting may pay for another video.

**Acceptance:** authenticated download through the correct provider client; credential forwarding restricted to the intended origin; redirect handling tested; fallback content retrieval when appropriate; recovery downloads the existing job without regenerating it.

### F02 — OpenRouter-only creation still invokes AtlasCloud (P1)

**Evidence:** `start_render` and `generate_storyboard_for_scene` create `AtlasCloudUploadResolver`; character sheets and `generate_scene_assets` instantiate `AtlasCloudImageProvider` directly.

**Reproduction:** configure only OpenRouter, create a scene requiring generated props or local references, then execute that path. The selected OpenRouter media provider does not eliminate AtlasCloud calls.

**Acceptance:** use provider-aware reference transport and one image-provider resolution path for characters, props, and storyboards; a mocked full workflow must make zero AtlasCloud calls in OpenRouter-only mode.

### F03 — Provider/model settings disagree across paths (P1)

**Evidence:** `APP_SETTING_DEFAULTS['video_model']` maps to `atlas_video_model`. `resolve` uses configuration before its `default` argument. A local reproduction with `DEFAULT_VIDEO_PROVIDER=openrouter` returned `minimax/h3-developer/text-to-video`. The OpenRouter image adapter reads `openrouter_image_model` directly, ignoring the UI's `image_model` setting. Shot rendering also does not apply the same provider selection logic as whole-scene rendering.

**Acceptance:** resolve provider plus model as one typed configuration for all generation paths; test fresh environment-only setup, UI overrides, project overrides, and retries. Invalid combinations fail before submission.

### F04 — AtlasCloud migration drops existing visual contracts (P1)

**Evidence:** [AtlasCloud video adapter](../../app/providers/atlascloud_video.py) no longer sends images, video references, audio flags, or structured multi-shot fields. It emits `ratio`, resolution and one rewritten prompt regardless of an arbitrary saved model ID. Several existing scene/reference/retry tests fail.

**Impact:** stored character sheets, storyboards, and frame anchors can look active in the UI while having no image influence on H3. Legacy model IDs can receive H3-shaped payloads.

**Acceptance:** model-family-specific adapters or an explicitly narrowed supported-model list; truthful capabilities and UI; migration guidance; contract tests for each retained route. Do not simply weaken reference tests to make CI green.

### F05 — OpenRouter reference semantics and limits are guessed (P1)

**Evidence:** [video adapter](../../app/providers/openrouter_video.py) maps the first two ordinary image references to first/last frames. [capabilities](../../app/providers/capabilities.py) assumes up to two references, generic aspect ratios, and duration ranges based on substrings in the model ID. See the provider report for the API distinction.

**Acceptance:** distinct style/content references and frame anchors; model-derived supported durations/resolutions/aspect ratios/reference modes; validate before uploads and submission. Test unsupported audio/video references explicitly.

### F06 — Project switches can redirect background context (P1, code-path risk)

**Evidence:** the server has one active project; `start_op` starts a new session without pinning a project ID, and generation services repeatedly call `active_project_id`. The layout caches the project name only once.

**Impact:** switching projects while a long operation runs can associate later artifacts or configuration with another project. This has not been reproduced through concurrent browser sessions.

**Acceptance:** operation and every generated artifact are bound to the originating project; switching during mocked delayed generation must not change ownership. Refresh the displayed active project after navigation.

### F07 — Guided controls overstate behavior (P2)

**Evidence:** [video_generation_service.py](../../app/services/video_generation_service.py) implements only the `dialogue` branch; `narration` and `off` skip conversion. Existing style wins over selected style. Language/instruction do not consistently reach all stages. Stages are returned only after submission finishes, while the UI displays a progressing checklist.

**Acceptance:** implement or remove unsupported choices; show effective style/language; persist stage updates; distinguish job submission from completed videos; preserve operation tracking across refresh. See the [UI report](2026-09-27-ui.md).

### F08 — Forward shot dependencies raise KeyError (P2, reproduced)

**Evidence:** [visual_dependency_service.py](../../app/services/visual_dependency_service.py) checks parents against all IDs but looks up only previously calculated layers. Calling `build_shot_dependencies([{'id':'a','depends_on':['b']},{'id':'b'}])` raises `KeyError: 'b'`.

**Acceptance:** validate/topologically order dependencies or explicitly reject forward edges with an actionable error; cover cycles, duplicates, missing parents, and disconnected shots. Rendering must consume this metadata before it can be described as dependency-controlled generation.

### F09 — Media representation and lifecycle assumptions are incomplete (P2)

**Evidence:** OpenRouter image polling consumes only the first result, assumes PNG, and removes the response from its process-local cache. AtlasCloud text-to-image requests JPEG while services name downloads `.png`. HTTP clients are created without a consistent close lifecycle. OpenRouter `expired` normalizes to pending (reproduced).

**Acceptance:** persist the intended output(s), preserve media type/extension, define image job lifecycle, close clients, and map every terminal provider status. Cover malformed/error payloads and transport timeouts.

### F10 — Storage configuration can break previews (P2, code evidence)

**Evidence:** [frontend API helper](../../frontend/src/lib/api.ts) builds media URLs by searching for literal `storage/` in a stored path. A valid alternate storage root without that substring returns no URL.

**Acceptance:** backend supplies storage-relative public URLs independent of filesystem naming; cover default, custom absolute, and Windows-style paths.

## Repair sequence and completion gates

| Order | Work | Completion gate |
|---|---|---|
| 1 | F01–F05 provider contracts and routing | A selected route stays on that route, receives supported inputs, and retrieves outputs; regression tests pass |
| 2 | F06 project ownership and F08 dependencies | Switching/restarting cannot misattribute work; dependency errors are actionable |
| 3 | F07 guided flow and setup readiness | Empty-project journey tells the truth about prerequisites, progress, cost-bearing actions, and completion |
| 4 | F09–F10 lifecycle/media handling | Terminal states, files, clients, and previews behave consistently |
| 5 | UI simplification and recovery | Capability-filtered controls, persisted tracking, clear retry/download actions, responsive inspection |
| 6 | Remote retrieval, best-of-k, assembly | Add these only with a connected workflow and measurable acceptance criteria |

The guided flow does not explicitly create character records or reference sheets from a newly invented cast. Empty-project generation can therefore proceed with names in prompts but without durable character identities. Add a cast-review/creation stage if automatic persistent characters are part of the intended first-video promise. Automatic asset-generation errors are also logged and swallowed by `create_shots`, so users can receive shots without the expected props; expose that as a recoverable warning.

The 23 backend failures need triage into intentional default changes and behavioral regressions. Route-specific replacements must preserve promised behavior or clearly retire it. A release gate also needs a fresh-install run, a browser walkthrough, and a scoped paid provider smoke test. This audit branch is not a release approval.
