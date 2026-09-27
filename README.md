# VideoFlow

A local AI video workspace for turning an idea into scripts, characters, scenes, shots, storyboards, and generated video takes. Python/FastAPI stores the work in SQLite and local files; the SvelteKit frontend provides a guided Create flow and an advanced production workspace.

## Start here

- **[User handbook](docs/handbook/README.md)** — 12 parts covering every main screen and workflow.
- **[Install from zero](docs/handbook/02-installation.md)** — no existing project, database, or assets required.
- **[Configure providers](docs/handbook/03-providers.md)** — credentials, models, agents, and media engines.
- **[Create your first video](docs/handbook/05-first-video.md)** — begin with an idea in an empty project.
- **[Working philosophy](docs/working-philosophy.md)** — inspectable stages, deliberate spending, reusable assets, and honest capabilities.

## Current readiness

The 27 September 2026 audit covers the working implementation, including the OpenRouter and AtlasCloud model migration. **OpenRouter support is partial; a fully OpenRouter-only workflow is not established.** Character/prop generation and reference uploads still depend on AtlasCloud, and OpenRouter video retrieval has an authentication gap.

The current AtlasCloud video adapter emits H3 text-to-video payloads. It does not preserve the older Kling reference-image and structured multi-shot contract. Existing UI controls and saved specs can therefore overstate what reaches the model.

Verification: **582 backend tests passed, 23 failed**. Frontend type check and production build passed. No paid provider generation or graphical browser walkthrough was verified. See the reports before relying on unattended generation:

| Report | Contents |
|---|---|
| [Implementation status and backlog](docs/audits/2026-09-27-implementation.md) | Completed, partial, missing, prioritized defects, acceptance criteria |
| [OpenRouter compatibility](docs/audits/2026-09-27-openrouter.md) | Text, images, video, references, settings, downloads, verification gates |
| [UI review](docs/audits/2026-09-27-ui.md) | Excessive controls, missing guidance, misleading states, visual checks still needed |
| [Verification evidence](docs/audits/2026-09-27-verification.md) | Commands, results, failed tests, and limits |

## Quick local launch

Requires Git, uv, Python 3.12, Node 22.12+, and npm. Install FFmpeg with libass for captions and frame extraction. See the handbook for installation and Windows configuration-copy commands.

From a fresh clone:

```sh
git clone https://github.com/JienWeng/videoflow.git
cd videoflow
uv sync --frozen --extra dev --python 3.12
cp .env.example .env
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open [Create video](http://localhost:5173/create). Configure providers and agent assignments before generation. Opening the workspace needs no API key; generation does. Do not overwrite an existing `.env` when updating.

The code defaults story agents to OpenCode Go and media to AtlasCloud. Provider keys alone do not reroute agents. Select your available models in Settings, and read the media limitations above before changing routes.

## Architecture

```text
UI → API → services → agents → structured LLM client
                   → provider adapters → remote generation
                   → SQLite / local storage / background operations
```

Agents propose schema-validated data. Services own persistence and execution. Jobs track remote generation separately from local download, QA, and caption work. The Create workflow returns scene jobs; whole-project movie assembly is not implemented.

Key areas: [`app/llm`](app/llm), [`app/services`](app/services), [`app/providers`](app/providers), [`frontend/src/routes`](frontend/src/routes). The running API reference is at [localhost:8000/docs](http://localhost:8000/docs).

## Development checks

```sh
uv run pytest -q
```

From `frontend`:

```sh
npm run check
npm run build
```

The historical [PROJECT.md](PROJECT.md) and `docs/superpowers/` documents describe plans, not the current support matrix. Use the handbook and audit for current behavior.
