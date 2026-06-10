# VideoFlow — AI-Integration Foundation

Local-first AI video studio backend. Turns a story idea into a Kling o3
reference-to-video render, keeping characters consistent via AI-generated
reference sheets. Every AI step emits **schema-validated JSON** enforced by
`instructor` + Pydantic; AI agents never call video providers directly.

## Stack

- **Text LLM**: MiniMax (`MiniMax-Text-01`) via its OpenAI-compatible endpoint,
  wrapped by **instructor** for strict structured output (validate + retry).
- **Image**: AtlasCloud `baidu/ERNIE-Image-Turbo` — generates multi-angle
  character reference sheets.
- **Video**: AtlasCloud `kwaivgi/kling-video-o3-pro/reference-to-video` — the only
  video provider. Multi-shot + voice/sound + multiple named reference images.
- **API/DB**: FastAPI + SQLModel (SQLite). Background polling via an asyncio worker.

## Setup

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
cp .env.example .env      # fill in MINIMAX_API_KEY and ATLASCLOUD_API_KEY
uv run uvicorn app.main:app --reload
```

### Frontend (SvelteKit)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (expects the API on :8000)
```

Pages: Dashboard, Assets (upload / AI tag / search), Characters (bible,
reference sheets, photo upload), Scenes (idea → script → scenes → shots →
分镜图 → render), Render (job table + video previews), Graph (relationships).
The backend serves `/storage` statically and allows CORS from :5173/:4173.

`ffmpeg` is required for thumbnails / QA frame extraction (degrades gracefully if
absent).

## Architecture

```
api → services → {agents, providers, models}
agents → llm (structured-output engine)
providers → AtlasCloud / MiniMax  (the only HTTP egress)
```

Agents and providers converge **only inside `render_service`** — agents produce a
`RenderSpec` (JSON), the service maps it to a provider payload. Key files:

- `app/llm/structured_client.py` — the reusable `generate(response_model=...)`
  engine. Per-model capability map picks the instructor Mode (native json_schema
  for MiniMax-Text-01, prompt-injected JSON otherwise).
- `app/schemas/render_schema.py` — `RenderSpec`: named references (`@Name`
  tokens → `images[]`), voice-on defaults, multi-shot validation.
- `app/providers/atlascloud_video.py` — RenderSpec → Kling o3 payload.
- `app/providers/atlascloud_client.py` — the single AtlasCloud HTTP boundary.
- `app/providers/url_resolver.py` — uploads local assets to AtlasCloud once, caches
  the URL on the asset record.
- `app/jobs/worker.py` + `app/services/poll_service.py` — background render polling,
  with a startup reconciler for crash recovery.

## Agent skills (per-LLM routing)

Each agent is a declarative **skill** in `app/llm/skills.py`: its system prompt
plus which LLM it uses and how it's tuned.

```python
"script_agent": AgentSkill("script_agent", PROMPTS["script_agent"],
                           provider="anthropic", model="claude-sonnet-4-6",
                           temperature=0.8),
"asset_recogniser": AgentSkill("asset_recogniser", PROMPTS["asset_recogniser"],
                               provider="minimax", temperature=0.2),
```

Supported providers: `minimax`, `openai`, `anthropic`, `gemini` (set the matching
`*_API_KEY` in `.env`). The structured-output engine builds the right instructor
backend per provider and enforces the **same Pydantic schema** on all of them —
swap an agent's brain by editing one line. Default routing is MiniMax everywhere.

## Pipeline

```
idea ─script─▶ scenes ─scene─▶ SceneSpec ─shot─▶ shots
                                                   │
character ─bible─▶ CharacterBible ─ERNIE─▶ reference sheets (assets)
                                                   │
                              prompt agent ─▶ RenderSpec (@named refs, voice)
                                                   │
                         render_service ─▶ upload refs ─▶ Kling o3 ─▶ job(202)
                                                   │
                       worker: poll ─▶ download mp4 + thumb ─▶ QA ─▶ succeeded
```

## Key endpoints

| Endpoint | Purpose |
|---|---|
| `POST /assets/upload`, `POST /assets/{id}/recognise` | upload + AI metadata |
| `POST /characters/{id}/bible` | generate CharacterBible |
| `POST /characters/{id}/reference-sheets` | ERNIE multi-angle reference images |
| `POST /assets/upload` (`-F character_id=...`) | upload YOUR character photo as a reference |
| `POST /scripts/generate` → `/scenes/{id}/generate` → `/scenes/{id}/shots/generate` | text pipeline |
| `POST /scenes/{id}/storyboard` | 分镜图: ERNIE NxN contact sheet from the scene's shots (2x2–4x4, consistent characters/scene/lighting) |
| `POST /scenes/{id}/render` | deterministic whole-scene multi-shot render — shots become the indexed `multi_prompt`, references auto-collected (characters + assets + 分镜图), voice on |
| `POST /render` | submit a `RenderSpec` (202 + job id) |
| `POST /render/from-shot` | prompt-agent builds the spec from a stored shot |
| `GET /render-jobs/{id}` | job status + outputs (with QA score) |
| `GET /graph` | relationship graph (characters → assets → scenes → shots → jobs → outputs) |

## Render example (named references + voice + multi-shot)

```json
POST /render
{
  "scene_id": "scene_1",
  "duration": 5,
  "aspect_ratio": "9:16",
  "prompt": "@Kling Lipstick streaks across @Image, then blooms on water",
  "reference_images": [
    {"name": "Kling Lipstick", "asset_id": "asset_abc"},
    {"name": "Image", "asset_id": "asset_def"}
  ],
  "sound": true,
  "keep_original_sound": true,
  "multi_shot": true,
  "shot_type": "customize",
  "multi_prompt": [
    {"prompt": "color river streaks across black", "duration": 3},
    {"prompt": "lipstick bullet blooms on water", "duration": 2}
  ]
}
```

## Tests

```bash
uv run pytest -q
```

Unit: structured-client error handling, Kling payload mapping, URL-resolver
caching. Integration: full text pipeline and render→QA pipeline (all mocked, no
network or keys required).

## Vision QA & referenced 分镜图

- **QA is vision-first**: `qa_agent` routes to an AtlasCloud-hosted VL model
  (`qwen3-vl`, OpenAI-compatible at `https://api.atlascloud.ai/v1` with the same
  ATLASCLOUD_API_KEY) and receives the scene's 分镜图 + character sheets +
  frames sampled from the rendered video, judging real consistency.
- **分镜图 uses true image references**: when the scene's cast has reference
  sheets, the storyboard is generated by `google/nano-banana-2/edit` with those
  sheets as `images[]` inputs and panels in the scene's aspect ratio; it falls
  back to ERNIE text-to-image when no references exist.
- **Editing**: `PATCH /scenes/{id}` and `PATCH /shots/{id}` partial updates,
  editable inline on the frontend Scenes page before rendering.

## Auto-captions (CapCut-style)

`POST /outputs/{id}/caption` (or the button on the Render page) transcribes the
rendered video's voice track with **faster-whisper** (local, open source — model
size via `WHISPER_MODEL`, default `small`) and burns styled subtitles in with
FFmpeg/libass. Style presets: `kids` (big yellow + black outline), `clean`,
`minimal` — see `GET /caption-styles`. Chinese renders via Noto Sans CJK in
`storage/fonts/` (gitignored; on a fresh clone fetch it with
`curl -fsSL -o storage/fonts/NotoSansCJKsc-Bold.otf https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf`).
The editable `.ass` file is kept next to the captioned `*_captioned.mp4`, so
you can fix a line and re-burn.

## Known foundation limitations

- **Vision gap (asset_recogniser only)**: asset recognition still structures
  user-supplied descriptions rather than looking at the file.
- **In-memory job queue**: durable via the `render_jobs` status table + startup
  reconciler; Celery/RQ is the scale-up path.
- **ChromaDB** vector memory is intentionally deferred.
