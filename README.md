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

### Frontend (SvelteKit Studio)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (expects the API on :8000)
```

Svelte 5 + Tailwind + shadcn-svelte. The home page is the **Studio**: an
editable entity canvas (@xyflow/svelte) showing characters → assets → scenes →
shots → jobs → outputs, side by side with a **guided-intent chat** panel.
Type 「给乐乐的场景生成分镜图」 — the intent agent classifies the message
(`POST /chat`), the panel shows a pre-filled action card, and Run calls the
real pipeline endpoint. On the canvas: click a node to edit it in a side
panel, drag-connect character→scene (cast) or asset→shot (reference), delete
an edge to detach, drag shots to reorder. Job status streams in live over SSE
(`GET /events`). Secondary pages: Assets (uploads + rendered videos), Characters,
Scenes (step-by-step pipeline), Render (jobs + caption controls).
The backend serves `/storage` statically and allows CORS from :5173/:4173.

`ffmpeg` is required for thumbnails / QA frame extraction (degrades gracefully if
absent).

### Simple video creation

Open `http://localhost:5173/create` or choose **Create video** in the sidebar.
Describe the story, choose a visual style, format, language, and dialogue mode,
then click **Create video**. VideoFlow runs the script, scene, shot, dialogue,
storyboard, and render stages automatically. Finished jobs appear under **My
videos**; Scenes, Characters, Assets, and Studio remain available under
**Advanced** when manual control is needed.

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

### Choosing additional AI connections

In **Settings → Providers**, configure a built-in provider or use **Add a named
connection**. Presets cover OpenAI, Claude, Gemini (OpenAI-compatible endpoint),
MiniMax, DeepSeek, OpenRouter, OpenCode Zen/Go, AtlasCloud, and custom endpoints.
Multiple connections can share a preset while keeping independent keys, URLs,
models, and protocols. Existing agent defaults and saved settings are preserved.

Select the API protocol supported by the model: Chat Completions, Responses,
or Anthropic Messages. Gateways may use different protocols for different
models; create separate named connections for those routes. Chat connections
offer tool calling, JSON mode, or schema-in-prompt output. Responses uses
schema-in-prompt with local validation/retry; Anthropic uses native tools.
All outputs are validated against the agent's Pydantic schema.

Save credentials, optionally **Load models**, then choose the connection and
model per agent under the agent settings. Model lists are suggestions and may
be unavailable; manual IDs are supported. **Test model + JSON** makes a small
real request and consumes provider usage. Connection tests alone do not prove
vision support; enable image inputs only for a model that supports them.

UI keys and URLs override environment defaults; clearing a saved override
returns to the environment. New named connections inherit their preset's
environment key, but do not inherit another connection's saved key. Environment
changes require a backend restart. Named connections persist in an additive
`llm_connections` table. No automatic provider fallback is performed.

**ChatGPT subscriptions:** choose **ChatGPT via Codex**. Install the Codex CLI
on the backend computer and run `codex login` there, selecting ChatGPT login.
Refresh Settings afterward. Authentication and refresh are managed by the CLI;
`codex logout` disconnects the shared CLI login. VideoFlow never copies login
tokens into its settings database. The installed CLI must support
`--ignore-user-config`, `--ignore-rules`, `--ephemeral`, and `--output-schema`.
Requests run in a temporary directory with a read-only sandbox and shell tools
disabled. Subscription usage limits and account model access apply; a model
available through the API is not necessarily available through Codex. Enter a
model supported by your account (Codex discovery is not exposed here).
Local/uploaded reference images are supported; remote image URLs are rejected
for this connection. Failed requests surface errors without API-key fallback.

API credentials retain the existing local database storage mechanism (base64
obfuscation, not encryption). Protect access to this computer and database.

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
| `POST /chat` | guided-intent chat: classifies a message into a pipeline action + pre-filled slots (LLM never executes) |
| `GET /events` | SSE stream of render-job status transitions |
| `POST`/`DELETE /scenes/{id}/cast/{character_id}` | add / remove a character from a scene's cast |
| `POST`/`DELETE /shots/{id}/assets/{asset_id}` | attach / detach a reference asset on a shot |
| `GET /caption-config` | caption styles + whisper model sizes + defaults |
| `DELETE /scenes/{id}`, `DELETE /shots/{id}` | delete a scene (cascades its shots; render history kept) or a shot |
| `POST /scenes/{id}/refine`, `POST /shots/{id}/refine` | AI-assisted editing: `{instruction}` → agent returns only the fields to change |
| `POST /scenes/{id}/assets/generate` | asset planner defines needed props/backgrounds and ERNIE generates + links them |

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

`POST /outputs/{id}/caption {style, model, language}` (or the controls on the
Render page) transcribes the rendered video's voice track with
**faster-whisper** (local, open source — model selectable per request from
tiny→large-v3, default via `WHISPER_MODEL`; `language: null` auto-detects) and
burns styled subtitles in with FFmpeg/libass. Rendered and captioned videos
are also registered in the Assets library automatically. Style presets: `kids` (big yellow + black outline), `clean`,
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
