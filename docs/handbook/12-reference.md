# 12. Reference

[Handbook](README.md) · Previous: [Troubleshooting](11-troubleshooting.md)

## Vocabulary

| Term | Meaning |
|---|---|
| Provider | External service hosting a model |
| Connection | Saved LLM protocol, URL, credential source, and model defaults |
| Agent | A specific planning or review role with a schema-validated response |
| Engine | Image/video/vision model configuration exposed in Settings |
| Character bible | Stored appearance, personality, visual rules, and voice rules |
| Asset | Uploaded or generated file with metadata |
| Storyboard / 分镜图 | Contact sheet showing planned scene beats |
| RenderSpec | Structured request passed from application logic to a video adapter |
| Operation | Background planning/image/caption task tracked through `/ops` |
| Render job | Provider generation attempt, polled by the worker |
| Output | Downloaded video and associated thumbnail, QA, and caption data |

## Configuration map

| Variable | Role |
|---|---|
| `OPENCODE_GO_API_KEY` | Current default text-agent connection credential |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` | Built-in OpenRouter credential and endpoint |
| `OPENROUTER_MODEL` | OpenRouter text model default |
| `OPENROUTER_IMAGE_MODEL`, `OPENROUTER_VIDEO_MODEL` | OpenRouter media defaults; see resolution gaps in the audit |
| `ATLASCLOUD_API_KEY`, `ATLASCLOUD_BASE_URL` | AtlasCloud media credential/endpoint |
| `ATLAS_LLM_BASE_URL`, `ATLAS_VL_MODEL` | AtlasCloud vision/text route |
| `ATLAS_IMAGE_MODEL`, `ATLAS_IMAGE_REF_MODEL` | AtlasCloud text-to-image and reference-edit model IDs |
| `ATLAS_VIDEO_MODEL` | AtlasCloud video model ID; adapter currently emits H3 payloads |
| `DEFAULT_IMAGE_PROVIDER`, `DEFAULT_VIDEO_PROVIDER` | Media selection defaults; not honored uniformly across all services |
| `DATABASE_URL`, `STORAGE_ROOT` | Local database and media locations |
| `POLL_INTERVAL_S`, `POLL_TIMEOUT_S` | Render polling timing |
| `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES` | Text request timeout and validation retries |
| `WHISPER_MODEL` | Local transcription model default |
| `VITE_API_BASE` | Frontend API base override; configured for the frontend process/build |

[`.env.example`](../../.env.example) lists the primary configuration. [Settings source](../../app/config.py) is the complete environment reference. Saved database settings can override environment defaults.

## Navigation and API

| Screen | Route | Main API areas |
|---|---|---|
| Create video | `/create` | `/videos/generate`, `/ops` |
| My videos | `/render` | `/render-jobs`, `/outputs` |
| Studio | `/` | `/graph`, `/chat` |
| Projects | `/projects` | `/projects` |
| Characters | `/characters` | `/characters` |
| Assets and style | `/assets` | `/assets`, `/style` |
| Scenes | `/scenes` | `/scripts`, `/scenes`, `/shots` |
| Output editor | `/editor/{output-id}` | `/outputs/{id}/editor`, caption endpoints |
| Settings | `/settings` | `/settings/providers`, `/settings/agents`, `/settings/app` |

Use the running backend's [OpenAPI UI](http://localhost:8000/docs) for request schemas. Posting generation endpoints can incur provider usage. Health and model listing are not substitutes for an end-to-end generation check.

## Maintainer checks

From the repository root:

```sh
uv run pytest -q
```

From `frontend`:

```sh
npm run check
npm run build
```

The audit baseline has 23 failing backend tests. Consult [verification evidence](../audits/2026-09-27-verification.md); a successful frontend build does not establish media compatibility.
