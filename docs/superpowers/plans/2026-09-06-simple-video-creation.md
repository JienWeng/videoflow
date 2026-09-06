# Simple Video Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a low-friction Create video flow that orchestrates the existing VideoFlow pipeline behind one guided action.

**Architecture:** Add a small video-generation service that sequences existing scene, conversation, storyboard, and render services inside the existing background operation runner. Add a focused Svelte Create route and make it the primary navigation entry while leaving advanced pages intact.

**Tech Stack:** FastAPI, SQLModel, existing asyncio operation runner, SvelteKit 5, TypeScript, Tailwind/shadcn-svelte.

**Spec:** `docs/superpowers/specs/2026-09-06-simple-video-creation-design.md`

## Global Constraints

- Reuse existing services and provider boundaries; do not duplicate provider calls in the orchestration layer.
- Preserve the active-project model and existing advanced routes.
- Use the existing `Op` table and `/ops/{op_id}` polling/SSE behavior.
- Default to controlled short dialogue with no narrator turns.
- Keep intermediate scenes, shots, assets, and jobs inspectable.
- Do not claim completion without fresh frontend and backend verification.

---

### Task 1: Add the generation request contract and orchestration service

**Files:**
- Create: `app/services/video_generation_service.py`
- Modify: `app/api/videos.py`
- Modify: `app/api/__init__.py`
- Test: `tests/integration/test_video_generation.py`

**Interfaces:**
- `VideoGenerateRequest`: `idea`, `target_duration`, `scene_count`, `style`, `aspect_ratio`, `language`, `conversation_mode`, `instruction`.
- `video_generation_service.generate_video(session, request) -> dict`.
- `POST /videos/generate?background=true` returns `{op_id, status}`; synchronous mode returns the pipeline summary.

- [ ] **Step 1: Write tests for the request defaults and route response.**

```python
def test_generate_video_starts_background_operation(client, monkeypatch):
    response = client.post(
        "/videos/generate?background=true",
        json={"idea": "A child learns why the moon is round."},
    )
    assert response.status_code == 202
    assert response.json()["op_id"]
```

- [ ] **Step 2: Implement the request model and router registration.**

Use a `VideoGenerateRequest` Pydantic model with `idea: str = Field(min_length=1)`, defaults `style="2d-picture-book"`, `aspect_ratio="9:16"`, `conversation_mode="dialogue"`, `language="English"`, and optional duration/count/instruction fields. Follow the existing `op_service.start_op` and `_op_response` patterns.

- [ ] **Step 3: Implement the service pipeline.**

Call existing services in this order:

```python
script, draft = await scene_service.create_script(...)
for scene in scene_service.list_scenes(session):
    await scene_service.expand_scene(session, scene.id)
    await scene_service.create_shots(session, scene.id, auto_assets=True)
await refine_service.convert_scenes_to_conversational(...)
for scene in scene_service.list_scenes(session):
    await storyboard_service.generate_storyboard_for_scene(session, scene.id)
    await render_service.render_scene(session, scene.id)
```

Only run the conversation stage when `conversation_mode == "dialogue"`. Apply the requested language and style through the existing project settings/style services before scene generation. Return IDs and per-stage summaries, not SQLModel rows.

- [ ] **Step 4: Add stage-safe failure reporting.**

Wrap each stage in a named progress update in the operation result. If a stage fails, raise an error containing the stage name and preserve prior rows. Do not catch provider failures as success.

- [ ] **Step 5: Run the focused integration test.**

Run: `uv run pytest tests/integration/test_video_generation.py -q`

Expected: the route test passes and service tests verify the call order with mocked existing services.

- [ ] **Step 6: Commit.**

```bash
git add app/api/videos.py app/api/__init__.py app/services/video_generation_service.py tests/integration/test_video_generation.py
git commit -m "feat: add automated video generation pipeline"
```

### Task 2: Build the Create video screen

**Files:**
- Create: `frontend/src/routes/create/+page.svelte`
- Create: `frontend/src/lib/create/GenerationProgress.svelte`
- Modify: `frontend/src/lib/api.ts` only if a typed helper is needed
- Test: `frontend` type checking via `npm run check`

**Interfaces:**
- The page submits `POST /videos/generate?background=true` and receives an operation ID.
- `GenerationProgress` consumes `{opId, status, result, error}` and uses the existing activity/SSE path or `/ops/{op_id}` polling.

- [ ] **Step 1: Add the compact form.**

Use one required story textarea and compact selects for style, aspect ratio, duration, language, and conversation mode. Put references and advanced fields in a closed `<details>` block. Primary button text is `Create video`.

- [ ] **Step 2: Submit to the background endpoint.**

Disable duplicate submission, show the progress state immediately, and route successful completion to `/render`. Convert API errors into one actionable toast/card.

- [ ] **Step 3: Add progress stages.**

Show `Story`, `Scenes`, `Dialogue`, `Visuals`, and `Render` with pending/running/done/failed states. Keep the screen usable during the render worker phase and link to advanced workspace only on failure or inspection.

- [ ] **Step 4: Run frontend verification.**

Run: `npm run check`

Expected: 0 errors and 0 warnings.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/routes/create frontend/src/lib/create
git commit -m "feat: add guided create video screen"
```

### Task 3: Make the simple flow primary and advanced tools secondary

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/routes/+page.svelte`
- Modify: `frontend/src/lib/shell/Onboarding.svelte`
- Test: `npm run check`

- [ ] **Step 1: Add Create video to the primary navigation.**

Use `/create` as the main Create entry. Keep Studio and Scenes under an `Advanced` group, and leave Render, Characters, Assets, Projects, and Settings accessible without removing routes.

- [ ] **Step 2: Make the Studio empty state point to Create video.**

Replace the multi-step onboarding card with one primary link to `/create` and one secondary link to the advanced workspace.

- [ ] **Step 3: Update onboarding copy.**

Describe the simple path: “Describe a story → VideoFlow builds the scenes and render.” Do not list every internal stage.

- [ ] **Step 4: Run frontend verification.**

Run: `npm run check`

Expected: 0 errors and 0 warnings.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/routes/+layout.svelte frontend/src/routes/+page.svelte frontend/src/lib/shell/Onboarding.svelte
git commit -m "feat: make guided video creation the primary flow"
```

### Task 4: Document and verify the shipped workflow

**Files:**
- Modify: `README.md`
- Test: `tests/integration/test_video_generation.py`
- Test: `frontend` checks and production build

- [ ] **Step 1: Document the Create video path.**

Add the exact startup commands, the `/create` workflow, the supported defaults, and the advanced-workspace fallback.

- [ ] **Step 2: Run backend verification.**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Run frontend verification.**

Run: `npm run check && npm run build`

Expected: both commands exit 0.

- [ ] **Step 4: Run repository hygiene checks.**

Run: `git diff --check && python3 -m compileall -q app`

Expected: both commands exit 0.

- [ ] **Step 5: Commit and push.**

```bash
git add README.md
git commit -m "docs: describe guided video creation"
git push origin main
```
