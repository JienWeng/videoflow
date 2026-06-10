# VideoFlow Studio — chat-first frontend with editable entity canvas

Date: 2026-06-10
Status: approved (brainstormed with user)

## Goal

Replace the page-centric SvelteKit frontend with a **Studio**: an editable
project entity canvas as the primary surface, a guided-intent chat panel
alongside it, live job updates, and two gap fixes (whisper config in the UI,
render outputs surfaced in the Assets library). Industry-standard look,
consistent design system, no emoji in the UI (lucide icons only).

## Decisions made

| Question | Decision |
|---|---|
| Framework | Keep SvelteKit; upgrade Svelte 4 → 5 |
| UI system | Tailwind CSS + shadcn-svelte (copy-in components) |
| Chat UI | Svelte AI Elements (shadcn-svelte registry: Conversation, Message, PromptInput) |
| Chat brain | Guided intent — LLM classifies only, never executes; user confirms via action card |
| Canvas | Project **entity graph** (not a pipeline builder) via @xyflow/svelte |
| Layout | Studio split view: canvas left, chat panel right, old pages as secondary tabs |
| Chainlit | Rejected — chat-only surface, can't host the canvas, second frontend stack |
| Live updates | SSE (`GET /events`) replaces 5s polling |

## Architecture

```
SvelteKit (Svelte 5, Tailwind, shadcn-svelte)
├─ / (Studio)         canvas (@xyflow/svelte) + chat panel (Svelte AI Elements)
├─ /assets /characters /scenes /render   existing pages, restyled, secondary tabs
└─ src/lib/api.ts     + SSE store, + chat/intent client

FastAPI (existing layering: api → services → agents/providers)
├─ POST /chat               intent_agent → Intent (structured, temperature 0)
├─ GET  /events             SSE job-status stream (worker publishes transitions)
├─ POST/DELETE relationship endpoints (cast member, shot asset)
├─ PATCH shot reorder (shot_order)
├─ GET  /caption-config     styles + whisper model sizes + defaults
├─ POST /outputs/{id}/caption gains `model` param
└─ worker: on render success, register output video as an Asset
```

## Components

### 1. Guided-intent chat (`POST /chat`)

- New `intent_agent` skill in `app/llm/skills.py` (provider minimax,
  temperature 0), structured output via the existing `structured_client`.
- `Intent` schema: `action` enum (`generate_script | generate_scenes |
  generate_shots | storyboard | render_scene | render_shot | caption |
  unknown`), resolved slots (`scene_id` fuzzy-matched by title, `character_id`
  by name, `style`, `language`), `confidence`, `reply` (one-line natural reply).
- The endpoint resolves slot names against the DB (scene titles, character
  names) and returns the intent + the candidate entity list used, so the
  action card can show a pre-filled dropdown.
- The LLM never executes anything. The frontend renders an **action card**
  (shadcn Card inside the conversation): pre-filled selects + one Run button
  that calls the existing endpoint. `unknown` → card listing capabilities.
- Chat history is client-side only (no persistence in v1).

### 2. Entity canvas (`@xyflow/svelte`)

- Node types: character, asset (thumbnail), scene, shot, storyboard (分镜图
  thumbnail), output (video poster + status badge). Data from existing
  `GET /graph`; the static-SVG Graph page is removed.
- Click node → shadcn `Sheet` side panel editing fields via `PATCH
  /scenes/{id}` / `PATCH /shots/{id}` (extended with PATCH for characters and
  assets where fields are editable).
- Drag-connect character→scene = add to cast; asset→shot = attach reference.
  Delete edge = detach. Two small relationship endpoints
  (`POST/DELETE /scenes/{id}/cast/{character_id}`,
  `POST/DELETE /shots/{id}/assets/{asset_id}`).
- Drag shot nodes within a scene to reorder → persists `shot_order`.
- Layout: dagre auto-layout on load; manual positions persisted in
  localStorage (no DB schema change).
- Chat action cards highlight/zoom to the node they produced.

### 3. Live updates (SSE)

- `GET /events`: server-sent events; the worker publishes
  `{job_id, status, output_id?}` on each transition through an in-process
  asyncio broadcast (consistent with the in-memory queue design).
- Frontend: a single store subscribes; canvas badges, render page table, and
  chat cards update live. Polling fallback retained if EventSource errors.

### 4. Gap fixes

- **Whisper in UI**: `GET /caption-config` → `{styles, models:
  [tiny…large-v3], default_model, default_language}`. `CaptionRequest` gains
  `model: str | None` (falls back to `settings.whisper_model`). Caption
  controls (render page + output node panel) expose style + model + language.
- **Outputs as assets**: on render success the worker creates an `Asset`
  (kind `video`, file_path = output video, metadata links `output_id` and
  `scene_id`). Captioned videos update/extend the record. Outputs then appear
  in the Assets library and are selectable as Kling references.

## Error handling

- `/chat`: LLM failure or low confidence → `unknown` intent with a helpful
  reply; never a 500 for classification problems.
- Relationship endpoints validate existence (404 via `NotFoundError`) and are
  idempotent (re-adding an existing cast member is a no-op).
- SSE: client reconnects with backoff; UI falls back to polling.

## Testing (TDD, same conventions as the 55 existing tests)

- Unit: Intent schema validation, slot resolution (fuzzy title match), caption
  config/model param, asset registration on job success.
- Integration: `/chat` with fake LLM → action card payload; relationship
  endpoints round-trip in `/graph`; reorder persists; SSE emits on a mocked
  job transition.
- Frontend: `npm run build` must pass; component logic kept thin.

## Phases

1. **Backend**: intent agent + `/chat`, SSE, relationship/reorder endpoints,
   `caption-config` + model param, outputs-as-assets.
2. **Frontend foundation**: Svelte 5 + Tailwind + shadcn-svelte migration of
   existing pages (visual parity, lucide icons, no emoji).
3. **Canvas**: entity graph, side-panel editing, connect/reorder.
4. **Studio shell**: split layout, chat panel (Svelte AI Elements), action
   cards, zoom-to-node, SSE-driven badges.

## Out of scope (v1)

- Chat history persistence, multi-turn slot filling, streaming LLM replies.
- Pipeline-builder canvas view (possible phase 2 of the canvas).
- Storing node positions in the DB.
- Project scoping / multi-project workspaces.
