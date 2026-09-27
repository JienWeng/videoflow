# OpenRouter compatibility audit — 27 September 2026

[Audit overview](2026-09-27-implementation.md) · [Provider setup](../handbook/03-providers.md)

## Verdict

**Partially integrated; not fully compatible and not ready for an OpenRouter-only end-to-end claim.** This is based on code paths, local deterministic checks, existing tests, and current official API documentation. No paid OpenRouter request was made. Account/model availability and generated quality remain unverified.

## Compatibility matrix

| Capability | Present implementation | Assessment |
|---|---|---|
| Built-in text connection | OpenAI-compatible Chat Completions preset and credential resolution | Implemented; live model behavior unverified |
| Named connections | Independent key/URL/model/protocol and output mode | Implemented for LLM routing; not selected by media registry |
| Structured output | Instructor/Pydantic validation and retry | Implemented, dependent on model's supported mode |
| Vision input | Structured client can attach local data URLs or remote image URLs | Implemented transport; model capability is largely user-declared |
| Model discovery | Generic connection discovery and manual IDs | Does not provide full media-specific capability selection |
| Image generation | `POST /images`, base64 extraction | Partial: first result only, PNG assumption, process-local response storage |
| Image reference editing | `input_references` request shape | Present; reference resolution still relies on AtlasCloud |
| Character/prop images | Services construct AtlasCloud provider | OpenRouter setting not honored |
| Video submission | `POST /videos` with model, prompt, duration, ratio, audio | Present; fixed 720p and guessed constraints |
| Video references | Ordinary references become first/last frames | Incorrect general-purpose semantics |
| Video polling | `GET /videos/{id}`, normalized status, unsigned URLs | Partial; expired state and error variants need handling |
| Video download | Generic unauthenticated downloader | Blocking incompatibility with documented content retrieval |
| Provider/model defaults | Media switches plus shared settings keys | Partial; environment-only selection and image model resolution disagree |
| Audio/video reference inputs | Video references rejected; audio refs not mapped | Unsupported |
| Native multi-shot control | Stored RenderSpec has fields but OpenRouter payload ignores them | Unsupported as a provider contract |
| Embeddings/reranking | Standalone wrapper methods | Not connected to continuity; rerank contract not validated in this audit |
| Full OpenRouter-only story | Hidden AtlasCloud dependencies remain | Not supported reliably |

## What the current API documentation establishes

OpenRouter documents dedicated image and asynchronous video endpoints. Video models expose model-specific capabilities; request validation should use them. Ordinary visual references and first/last frames are separate request modes. Completed-video content URLs require authentication. The current adapter lacks those guarantees. [Official video guide](https://openrouter.ai/docs/guides/overview/multimodal/video-generation).

Image responses contain base64 data and can include a media type; the adapter must not assume every output is one PNG. [Official image guide](https://openrouter.ai/docs/guides/overview/multimodal/image-generation).

These sources were checked on the audit date. The report does not infer that all advertised models work with VideoFlow.

## Blocking paths in the repository

1. **Credential boundary:** [OpenRouterClient](../../app/providers/openrouter_client.py) authenticates submission/polling, but [poll_service](../../app/services/poll_service.py) hands download to [media.download](../../app/services/media.py), which sends no credential. Introduce provider-specific retrieval with strict origin handling rather than adding an API key to arbitrary returned URLs.
2. **Reference transport:** [render_service.start_render](../../app/services/render_service.py) and [storyboard_service](../../app/services/storyboard_service.py) always use the AtlasCloud uploader. A local reference in an OpenRouter request can require a second account before submission.
3. **Image routing:** [character_service](../../app/services/character_service.py) and [asset_gen_service](../../app/services/asset_gen_service.py) instantiate AtlasCloud directly. Switching the storyboard provider is insufficient.
4. **Model resolution:** the shared `video_model` default resolves to AtlasCloud, and the OpenRouter image adapter ignores the saved `image_model`. A named LLM connection's custom credential is not automatically the media credential.
5. **Meaning of references:** [openrouter_video](../../app/providers/openrouter_video.py) treats character sheets, props, and storyboards as first/last frames based only on position. A storyboard contact sheet can become a literal opening frame.
6. **Capabilities:** [capabilities.py](../../app/providers/capabilities.py) uses model-name substring checks and broad continuous duration ranges. It has no advertised per-model discrete durations/resolutions or mode metadata.
7. **Render entry points:** whole-scene rendering selects the configured media provider, while from-shot rendering relies on a prompt-agent RenderSpec whose defaults remain AtlasCloud/H3. Retry behavior inherits saved spec and current adapter mismatches.

## Verification required before claiming compatibility

| Check | Required evidence |
|---|---|
| Text and structured response | Selected account/model returns each representative schema; invalid output retries/error clearly |
| Vision | Known image content reaches a vision model and produces a meaningful answer |
| Images | Text-to-image and referenced image requests; valid base64; output type; multiple/empty/error response cases |
| Video requests | Model-derived legal duration, aspect ratio, resolution and audio combinations |
| Reference semantics | Ordinary references remain guidance; explicit frame anchors keep their intended first/last role |
| Poll/download | Pending, running, completed, failed, canceled, expired, timeout, missing URLs, authenticated content and redirects |
| OpenRouter-only workflow | Empty project through characters/props/storyboard/video/QA with no AtlasCloud client use |
| Settings/restart | Built-in keys, named LLM keys, environment defaults, global/project overrides, retry and restart |
| Cost-bearing live smoke | Explicit model, limited number of requests, recorded usage, playable downloaded output |

Mocked contract tests should precede live checks. Passing a text “Test model + JSON” check should never be displayed as proof that image or video generation works.
