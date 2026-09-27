# OpenRouter compatibility audit — 27 September 2026

[Audit overview](2026-09-27-implementation.md) · [Provider setup](../handbook/03-providers.md)

## Verdict

**The contract and routing defects identified below have been repaired and regression-tested. Full live compatibility is not yet certified.** Verification is mocked; no paid OpenRouter request was made. Account/model availability and generated quality remain unverified. In particular, OpenRouter's video guide does not specify whether local data-URL references are accepted, so reference-to-video needs a live smoke test.

## Compatibility matrix

| Capability | Present implementation | Assessment |
|---|---|---|
| Built-in text connection | OpenAI-compatible Chat Completions preset and credential resolution | Implemented; live model behavior unverified |
| Named connections | Independent key/URL/model/protocol and output mode | Implemented for LLM routing; not selected by media registry |
| Structured output | Instructor/Pydantic validation and retry | Implemented, dependent on model's supported mode |
| Vision input | Structured client can attach local data URLs or remote image URLs | Implemented transport; model capability is largely user-declared |
| Model discovery | Generic connection discovery and manual IDs | Does not provide full media-specific capability selection |
| Image generation | `POST /images`, data extraction for all returned outputs | Implemented; preserves declared media type and local file extension; provider limits remain model-specific |
| Image reference editing | `input_references` request shape and local data URL resolver | Implemented; OpenRouter image guide documents HTTP(S) and data URLs |
| Character/prop images | Selected image provider is resolved by settings | Implemented in code; live end-to-end run not performed |
| Video submission | Model catalog checked before `POST /videos` | Implemented for model, duration, aspect ratio, resolution, audio; live model behavior unverified |
| Video references | Guidance refs and explicit first/last frames use separate fields | Correct request semantics; when frame anchors are present they take precedence |
| Video polling | `GET /videos/{id}`, normalized terminal states | Implemented, including expired/cancelled failures |
| Video download | Provider-specific `/videos/{id}/content?index=N` request with bearer auth | Implemented and mocked; live authenticated retrieval unverified |
| Provider/model defaults | Provider-aware defaults and settings on direct/from-shot/whole-scene paths | Implemented and covered by tests |
| Audio/video reference inputs | Video references rejected; audio refs not mapped | Unsupported |
| Native multi-shot control | Timed storyboard beats are included in the prompt | No native multi-shot field exists in the documented video request; output quality is model-dependent |
| Embeddings/reranking | Standalone wrapper methods | Not connected to continuity; rerank contract not validated in this audit |
| Full OpenRouter-only story | Media generation paths now resolve to OpenRouter when selected | Routing is implemented, but a zero-AtlasCloud live workflow has not been verified |

## What the current API documentation establishes

OpenRouter documents dedicated image and asynchronous video endpoints. The implementation now uses model-specific video metadata, distinct guidance/frame fields, and authenticated content retrieval. [Official video guide](https://openrouter.ai/docs/guides/overview/multimodal/video-generation).

Image responses contain base64 data and can include a media type; the adapter preserves all returned outputs and their actual format. [Official image guide](https://openrouter.ai/docs/guides/overview/multimodal/image-generation).

These sources were checked on the audit date. The report does not infer that all advertised models work with VideoFlow.

## Blocking paths in the repository

The previously identified implementation defects are repaired in the current source. Remaining release checks are external: live text/vision/image/video behavior, actual authenticated download, model-specific output quality, and reference-to-video acceptance for local data URLs. Named LLM connections still use independent credentials; configure the built-in OpenRouter media credential for these dedicated endpoints.

## Verification required before claiming compatibility

| Check | Required evidence |
|---|---|
| Text and structured response | Live account/model schema behavior; invalid output retries/error clearly |
| Vision | Known image content reaches a vision model and produces a meaningful answer |
| Images | Mocked request/response, all outputs and media types covered; live generation still required |
| Video requests | Mocked model-derived duration, aspect ratio and resolution; live model behavior still required |
| Reference semantics | Mocked guidance vs frame-anchor fields; live data-URL reference-to-video still required |
| Poll/download | Mocked authenticated content endpoint and terminal states; live retrieval/redirect behavior still required |
| OpenRouter-only workflow | Live empty-project run through characters/props/storyboard/video/QA with no AtlasCloud client use |
| Settings/restart | Built-in keys, named LLM keys, environment defaults, global/project overrides, retry and restart |
| Cost-bearing live smoke | Explicit model, limited number of requests, recorded usage, playable downloaded output |

Mocked contract tests should precede live checks. Passing a text “Test model + JSON” check should never be displayed as proof that image or video generation works.
