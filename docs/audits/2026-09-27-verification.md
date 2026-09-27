# Verification evidence — 27 September 2026

[Audit overview](2026-09-27-implementation.md)

## Scope

The baseline was the current working tree on top of `011641f`, before this session's documentation edits. Runtime source and tests were not modified by the documentation audit. Pre-existing changes are included in review-branch commit `846705b` as an implementation snapshot.

## Executed checks

| Check | Result |
|---|---|
| `uv sync --frozen --extra dev --python 3.12` | Passed against the existing environment (75 packages checked); not a clean OS install |
| `uv run pytest -q` | **582 passed, 23 failed**, one Starlette/httpx deprecation warning |
| `npm run check` in frontend | **0 errors, 0 warnings** |
| `npm run build` in frontend | **Passed**, static build written; plugin timing warning, no build failure |
| `git diff --check` | Passed, including the documentation changes |
| Documentation link/fence check | 20 Markdown files checked; no missing relative targets or unbalanced code fences |
| API start with new temporary SQLite DB/storage | Passed |
| Fresh `/health`, `/projects/active`, `/assets`, `/characters`, `/scenes`, `/render-jobs`, `/graph`, `/settings/app`, `/openapi.json` | All HTTP 200; asset/character/scene/job lists empty |
| Environment-only OpenRouter selection | Reproduced wrong model: provider `openrouter`, resolved model `minimax/h3-developer/text-to-video` |
| Forward shot dependency | Reproduced `KeyError: 'b'` |
| `normalise_status('expired')` | Returned `pending` |
| Browser entry point | Unavailable: tool returned “No browser is available” |
| FFmpeg availability | Executable not found; media/caption execution not verified |

Environment: Python 3.12 via uv, uv 0.12.1, Node 22.22.1, npm 9.2.0, Linux. Fresh API data used `/tmp/videoflow-handbook-audit.sqlite` and `/tmp/videoflow-handbook-storage`; the user's project database and media were not used for smoke data.

The backend suite was run twice while collecting complete output; the retained run above is the report baseline. No tests were rewritten to accept the changed provider contracts.

## Failed tests

| File | Failing tests / reason |
|---|---|
| `tests/integration/test_from_shot_pipeline.py` | `test_from_shot_sends_characters_and_assets_with_multishot_voice`: missing `images` |
| `tests/integration/test_render_pipeline.py` | `test_qa_retry_corrective_rerender`: missing `multi_prompt`; `test_resubmit_failed_job_replays_stored_spec`: rewritten prompt |
| `tests/integration/test_scene_pipeline.py` | Eight failures listed below: missing structured multi-shot/reference payloads |
| `tests/integration/test_settings_api.py` | `test_list_agents_covers_all_skills`, `test_put_override_then_get_reflects_it`: changed default provider/model |
| `tests/unit/test_idea_agent.py` | `test_idea_agent_skill_registered`: temperature changed from 0.8 to 0.5 |
| `tests/unit/test_provider_metadata.py` | Nine failures listed below: duration, reference and image parameter contracts changed |

Scene pipeline failures:

- `test_scene_render_uses_shots_storyboard_and_references`
- `test_scene_render_anchors_previous_scenes_final_frame`
- `test_scene_render_anchor_is_idempotent`
- `test_scene_render_anchor_relinks_on_newer_source_render`
- `test_scene_render_without_previous_render_has_no_anchor`
- `test_scene_render_caps_references_at_live_kling_limit`
- `test_scene_render_prompt_omits_storyboard_token_when_capped_out`
- `test_render_scene_skips_unknown_asset_ids_instead_of_404`

The scene pipeline contains **eight** failures. Provider metadata contains **nine**: one declared minimum, three parameterized clamps, three max-reference cases, and two image payload cases. Totals: 1 + 2 + 8 + 2 + 1 + 9 = 23.

Provider metadata failures:

- `test_video_declares_duration_clamp_metadata`
- `test_duration_is_clamped_to_metadata_range[1-3]`
- `test_duration_is_clamped_to_metadata_range[2-3]`
- `test_duration_is_clamped_to_metadata_range[3-3]`
- `test_video_max_refs_default_unchanged`
- `test_video_max_refs_tunable_via_resolver`
- `test_video_falls_back_to_config_without_session`
- `test_image_payload_defaults_unchanged_without_session`
- `test_image_params_tunable_via_resolver`

## Limits of this evidence

Most tests mock provider calls. Passing unit/integration tests does not establish account access, generation quality, model-specific compatibility, or successful paid media retrieval. The failed default-value assertions may need migration updates, while missing reference/multi-shot behavior needs a product/adapter decision. Neither category should be dismissed without tracing the contract.

No paid live generation, external account setup, native Windows/macOS installation, real caption burn, screenshot review, responsive interaction, or browser accessibility check was completed. These remain explicit release gates.
