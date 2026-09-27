# 11. Troubleshooting

[Handbook](README.md) · Previous: [Captions](10-captions-editor.md) · Next: [Reference](12-reference.md)

Start by identifying the stage that failed. Keep the project, scene, operation, and job IDs when reporting a problem. Remove API keys from shared logs.

| Symptom | Check and next action |
|---|---|
| `uv`, `node`, or `npm` not found | Install the prerequisite, reopen the terminal, and check its version |
| Cannot import `app` | Run the backend from the repository root containing `pyproject.toml`; run `uv sync --frozen --extra dev --python 3.12` |
| Frontend loads but requests fail | Check API `/health`, port 8000, and the backend terminal; use frontend port 5173 or 4173 |
| Page on a remote machine cannot reach API | The default client calls port 8000 on the browser's host; remote deployment/CORS is not configured by this local guide |
| Model/key error | Check the exact agent assignment, provider key, account access, and model ID; test the selected model |
| Saved key seems impossible to clear | A saved override may fall back to `.env`; clear that source and restart if disconnection is intended |
| JSON/schema validation fails | Try an output mode supported by the model and inspect its response; a successful key check is not a schema check |
| OpenRouter fails despite a working text test | Text, image, and video use separate requests; review the compatibility audit and built-in media credentials |
| OpenRouter-only story asks for AtlasCloud | Check Engines and agent routes; media provider and LLM provider settings are separate |
| Video generated remotely but download fails | Check the OpenRouter render job and local disk/storage errors before resubmitting; retrieval uses the authenticated content endpoint |
| Too many references or invalid duration | Check the selected model's actual limits and reduce inputs; current capability rules are incomplete |
| Story progress appears stuck | Stage updates are currently saved at completion; inspect backend errors and Activity before restarting |
| Refreshed Create page looks empty | Its operation tracking is in memory; inspect Scenes/My videos/Activity before creating a duplicate |
| Chosen style did not apply | An existing project style guide takes precedence; inspect it under Assets |
| Narrated mode has no narration | A narration-specific stage is not implemented; write and review narration manually |
| Wrong project label/data | Refresh after switching; do not switch while background work runs or mix projects across tabs |
| Missing thumbnail or QA | Install FFmpeg and configure a vision-capable QA model; successful render does not guarantee successful QA |
| Captions fail | Confirm speech exists, FFmpeg has libass, Whisper download completed, and timings are valid |
| Chinese captions show boxes | Install the Noto CJK font in `storage/fonts/` |
| Custom storage path has broken previews | The frontend currently assumes `storage/` in paths; use the default until URL mapping is fixed |
| Backend restart interrupted creation | Inspect saved intermediate work; orchestration operations do not resume automatically |

## Avoid unnecessary regeneration

If text is wrong, edit the scene or shot. If a storyboard is wrong, regenerate that storyboard after fixing its source. If video generation failed, inspect the job and provider before resubmission. Starting again from Create repeats earlier stages and can create duplicate work.

## Report a reproducible issue

Include the app commit, route, expected behavior, actual behavior, selected provider/model, relevant IDs, and a sanitized error. State whether it happens in an empty project. For UI problems, include viewport size and a screenshot if possible. For provider failures, distinguish submission, polling, and download.

See the [known issues and repair priorities](../audits/2026-09-27-implementation.md) before reporting a duplicate.
