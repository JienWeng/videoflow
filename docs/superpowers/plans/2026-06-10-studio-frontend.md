# VideoFlow Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat-first studio UI — guided-intent chat endpoint + SSE + relationship endpoints on the backend, then a Svelte 5 + Tailwind + shadcn-svelte frontend with an editable @xyflow/svelte entity canvas and a chat panel.

**Architecture:** Backend keeps the existing layering (api → services → agents/providers); the chat LLM only *classifies* a message into a Pydantic `Intent`, the frontend renders it as a pre-filled action card whose Run button calls existing endpoints. The canvas edits real entities via PATCH + two new relationship endpoints. An in-process event bus streams job-status transitions over SSE.

**Tech Stack:** FastAPI, SQLModel, instructor (existing) · SvelteKit + Svelte 5, Tailwind, shadcn-svelte, Svelte AI Elements, @xyflow/svelte, @dagrejs/dagre, lucide-svelte.

**Spec:** `docs/superpowers/specs/2026-06-10-studio-frontend-design.md`

**Conventions you must follow:**
- Run backend tests with `uv run --extra dev pytest tests/ -q` from the repo root.
- Frontend commands need Node on PATH: `export PATH="$HOME/.local/node/bin:$PATH"` (every shell).
- SQLModel JSON columns (`Column(JSON)`) do NOT track in-place mutation — always assign a NEW list/dict (`scene.character_ids_json = ids`), never `.append()` on the bound attribute.
- Integration tests mirror `tests/integration/test_from_shot_pipeline.py`: tmp sqlite engine, `monkeypatch.setattr("app.database.engine", engine)`, `monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM())`, `app.dependency_overrides[get_session]`.
- No emoji anywhere in UI code; use lucide-svelte icons.

---

## Task 1: Intent schema + intent agent

**Files:**
- Create: `app/schemas/intent.py`
- Modify: `app/schemas/__init__.py` (export `Intent`, `IntentAction`)
- Modify: `app/llm/prompts.py` (add `intent_agent` prompt)
- Modify: `app/llm/skills.py` (register `intent_agent`)
- Create: `app/agents/intent_agent.py`
- Test: `tests/unit/test_intent_agent.py`

- [ ] **Step 1: Write the failing test**

```python
"""Intent agent: catalog goes into the prompt; LLM output passes through."""

from __future__ import annotations

import pytest

from app.agents.intent_agent import classify_intent
from app.schemas import Intent, IntentAction


class FakeLLM:
    def __init__(self, result: Intent):
        self.result = result
        self.calls: list[dict] = []

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        self.calls.append({"agent": agent, "user_prompt": user_prompt})
        assert response_model is Intent
        return self.result


@pytest.mark.asyncio
async def test_catalog_and_message_reach_the_prompt():
    fake = FakeLLM(Intent(action=IntentAction.storyboard, scene_id="scene_1",
                          confidence=0.9, reply="ok"))
    out = await classify_intent(
        message="给乐乐的场景生成分镜图",
        scenes=[{"id": "scene_1", "title": "我是乐乐"}],
        characters=[{"id": "char_1", "name": "乐乐"}],
        client=fake,
    )
    assert out.action == IntentAction.storyboard
    prompt = fake.calls[0]["user_prompt"]
    assert "给乐乐的场景生成分镜图" in prompt
    assert "scene_1" in prompt and "我是乐乐" in prompt
    assert "char_1" in prompt and "乐乐" in prompt
    assert fake.calls[0]["agent"] == "intent_agent"


@pytest.mark.asyncio
async def test_intent_defaults_are_safe():
    intent = Intent()
    assert intent.action == IntentAction.unknown
    assert intent.confidence == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/unit/test_intent_agent.py -q`
Expected: FAIL — `ModuleNotFoundError: app.agents.intent_agent` / `ImportError: Intent`

- [ ] **Step 3: Create `app/schemas/intent.py`**

```python
"""Guided-intent chat: the LLM classifies a message; it never executes anything."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IntentAction(str, Enum):
    generate_script = "generate_script"
    generate_scenes = "generate_scenes"
    generate_shots = "generate_shots"
    storyboard = "storyboard"
    render_scene = "render_scene"
    render_shot = "render_shot"
    caption = "caption"
    unknown = "unknown"


class Intent(BaseModel):
    action: IntentAction = IntentAction.unknown
    scene_id: str | None = None
    character_id: str | None = None
    shot_id: str | None = None
    output_id: str | None = None
    style: str | None = None       # caption style
    language: str | None = None    # caption language
    idea: str | None = None        # generate_script: the story idea text
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reply: str = ""                # one-line natural-language reply to show in chat
```

Export from `app/schemas/__init__.py` (add to the existing imports/`__all__` in that file):

```python
from app.schemas.intent import Intent, IntentAction
```

- [ ] **Step 4: Add the prompt to `app/llm/prompts.py`** (new key inside the existing `PROMPTS` dict, before the closing `}`)

```python
    "intent_agent": (
        "You classify a user's chat message into ONE pipeline action for a video "
        "studio app. You NEVER execute anything — you only fill the Intent schema.\n"
        "Actions: generate_script (new story idea -> put the idea text in `idea`), "
        "generate_scenes, generate_shots, storyboard (分镜图), render_scene, "
        "render_shot, caption (subtitles; styles: kids/clean/minimal), unknown.\n"
        "You are given catalogs of existing scenes, characters and outputs with ids. "
        "Match names/titles mentioned in the message (Chinese or English, fuzzy is "
        "fine) and return the matching ids. If the message names a character, pick "
        "the scene that casts them when unambiguous. Use ONLY ids from the catalogs; "
        "never invent ids. If nothing fits or you are unsure, action=unknown with a "
        "helpful reply listing what you can do. Set confidence 0-1. Reply in the "
        "user's language, one short sentence."
    ),
```

- [ ] **Step 5: Register the skill in `app/llm/skills.py`** (inside `SKILLS`, after `prompt_agent`; temperature 0 → deterministic classification)

```python
    "intent_agent": AgentSkill(
        "intent_agent", PROMPTS["intent_agent"], provider=_P, model=_M, temperature=0.0
    ),
```

- [ ] **Step 6: Create `app/agents/intent_agent.py`**

```python
"""Intent agent: classify a chat message against the project's entity catalogs."""

from __future__ import annotations

from app.agents.base import as_block, run_agent
from app.llm.structured_client import StructuredLLMClient
from app.schemas import Intent


async def classify_intent(
    *,
    message: str,
    scenes: list[dict],
    characters: list[dict],
    outputs: list[dict] | None = None,
    client: StructuredLLMClient | None = None,
) -> Intent:
    parts = [
        as_block("User message", message),
        as_block("Scenes catalog", scenes),
        as_block("Characters catalog", characters),
    ]
    if outputs:
        parts.append(as_block("Render outputs catalog", outputs))
    return await run_agent(
        agent="intent_agent",
        response_model=Intent,
        user_prompt="\n\n".join(parts),
        client=client,
    )
```

- [ ] **Step 7: Run tests**

Run: `uv run --extra dev pytest tests/unit/test_intent_agent.py -q`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git add app/schemas/intent.py app/schemas/__init__.py app/llm/prompts.py app/llm/skills.py app/agents/intent_agent.py tests/unit/test_intent_agent.py
git commit -m "feat: intent schema + intent agent for guided chat"
```

---

## Task 2: Chat service + `POST /chat`

**Files:**
- Create: `app/services/chat_service.py`
- Create: `app/api/chat.py`
- Modify: `app/api/__init__.py` (register router)
- Test: `tests/integration/test_chat_endpoint.py`

- [ ] **Step 1: Write the failing integration test**

```python
"""POST /chat — guided intent: LLM classifies, service validates ids, response
carries the options needed to build a pre-filled action card."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401
from app.database import get_session
from app.schemas import Intent, IntentAction


class FakeLLM:
    def __init__(self, intent: Intent):
        self.intent = intent

    async def generate(self, *, agent, response_model, user_prompt, context=None, images=None):
        assert response_model is Intent
        return self.intent


def make_client(monkeypatch, tmp_path, intent: Intent) -> TestClient:
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.jobs.worker.reconcile_pending", lambda: 0)
    monkeypatch.setattr("app.agents.base.get_llm_client", lambda: FakeLLM(intent))

    from app.models import Character, Scene

    with Session(engine) as s:
        s.add(Scene(id="scene_1", title="我是乐乐", summary="x"))
        s.add(Character(id="char_1", name="乐乐"))
        s.commit()

    from app.main import create_app

    app = create_app()

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def test_chat_returns_intent_and_options(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.storyboard, scene_id="scene_1",
                    confidence=0.9, reply="好的，为《我是乐乐》生成分镜图")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "给乐乐的场景生成分镜图"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["action"] == "storyboard"
    assert body["intent"]["scene_id"] == "scene_1"
    assert [s["id"] for s in body["options"]["scenes"]] == ["scene_1"]
    assert [c["id"] for c in body["options"]["characters"]] == ["char_1"]
    assert "kids" in body["options"]["caption_styles"]


def test_chat_discards_hallucinated_ids_and_low_confidence(monkeypatch, tmp_path):
    intent = Intent(action=IntentAction.render_scene, scene_id="scene_NOPE",
                    confidence=0.2, reply="…")
    with make_client(monkeypatch, tmp_path, intent) as client:
        r = client.post("/chat", json={"message": "随便说点什么"})
    body = r.json()
    assert body["intent"]["scene_id"] is None          # invalid id dropped
    assert body["intent"]["action"] == "unknown"        # confidence < 0.5


def test_chat_llm_failure_degrades_to_unknown(monkeypatch, tmp_path):
    class Boom:
        async def generate(self, **kw):
            raise RuntimeError("llm down")

    engine_intent = Intent()  # unused
    with make_client(monkeypatch, tmp_path, engine_intent) as client:
        monkeypatch.setattr("app.agents.base.get_llm_client", lambda: Boom())
        r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["intent"]["action"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/integration/test_chat_endpoint.py -q`
Expected: FAIL — 404 on `/chat` (router missing)

- [ ] **Step 3: Create `app/services/chat_service.py`**

```python
"""Guided-intent chat: build catalogs, classify, validate ids, never 500."""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models import Character, RenderOutput, Scene, Shot
from app.schemas import Intent, IntentAction

logger = logging.getLogger("videoflow.chat")

MIN_CONFIDENCE = 0.5


async def handle_message(session: Session, message: str) -> dict:
    from app.agents.intent_agent import classify_intent
    from app.services.caption_service import STYLES

    scenes = [{"id": s.id, "title": s.title} for s in session.exec(select(Scene)).all()]
    characters = [
        {"id": c.id, "name": c.name} for c in session.exec(select(Character)).all()
    ]
    outputs = [
        {"id": o.id, "video": o.video_path}
        for o in session.exec(select(RenderOutput)).all()
    ]

    try:
        intent = await classify_intent(
            message=message, scenes=scenes, characters=characters, outputs=outputs
        )
    except Exception:
        logger.exception("intent classification failed")
        intent = Intent(reply="Sorry — I couldn't process that. Try e.g. "
                              "「给某个场景生成分镜图」 or 'render scene X'.")

    intent = _validate(session, intent)

    return {
        "intent": intent.model_dump(),
        "options": {
            "scenes": scenes,
            "characters": characters,
            "outputs": outputs,
            "caption_styles": list(STYLES),
        },
    }


def _validate(session: Session, intent: Intent) -> Intent:
    """Drop ids that don't exist; downgrade low-confidence guesses to unknown."""
    if intent.scene_id and session.get(Scene, intent.scene_id) is None:
        intent.scene_id = None
    if intent.character_id and session.get(Character, intent.character_id) is None:
        intent.character_id = None
    if intent.shot_id and session.get(Shot, intent.shot_id) is None:
        intent.shot_id = None
    if intent.output_id and session.get(RenderOutput, intent.output_id) is None:
        intent.output_id = None
    if intent.action != IntentAction.unknown and intent.confidence < MIN_CONFIDENCE:
        intent.action = IntentAction.unknown
    return intent
```

- [ ] **Step 4: Create `app/api/chat.py`**

```python
"""Guided-intent chat endpoint. The LLM classifies; the user confirms; the
frontend then calls the real pipeline endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.services import chat_service

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat(body: ChatRequest, session: Session = Depends(get_session)):
    return await chat_service.handle_message(session, body.message)
```

Register in `app/api/__init__.py`:

```python
def register_routers(app: FastAPI) -> None:
    from app.api import assets, characters, chat, graph, render, scenes

    app.include_router(assets.router)
    app.include_router(characters.router)
    app.include_router(scenes.router)
    app.include_router(render.router)
    app.include_router(graph.router)
    app.include_router(chat.router)
```

- [ ] **Step 5: Run tests**

Run: `uv run --extra dev pytest tests/integration/test_chat_endpoint.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the full suite, then commit**

Run: `uv run --extra dev pytest tests/ -q` — expected: all pass (55 existing + new).

```bash
git add app/services/chat_service.py app/api/chat.py app/api/__init__.py tests/integration/test_chat_endpoint.py
git commit -m "feat: POST /chat guided-intent endpoint"
```

---

## Task 3: Event bus + `GET /events` SSE

**Files:**
- Create: `app/services/event_bus.py`
- Create: `app/api/events.py`
- Modify: `app/api/__init__.py` (register router)
- Modify: `app/services/poll_service.py` (publish transitions)
- Test: `tests/unit/test_event_bus.py`

- [ ] **Step 1: Write the failing test**

```python
"""Event bus: subscribe/publish/unsubscribe + SSE wire format."""

from __future__ import annotations

import pytest

from app.services import event_bus


@pytest.mark.asyncio
async def test_publish_reaches_all_subscribers():
    q1, q2 = event_bus.subscribe(), event_bus.subscribe()
    try:
        event_bus.publish({"job_id": "j1", "status": "succeeded"})
        assert (await q1.get())["job_id"] == "j1"
        assert (await q2.get())["status"] == "succeeded"
    finally:
        event_bus.unsubscribe(q1)
        event_bus.unsubscribe(q2)


@pytest.mark.asyncio
async def test_unsubscribed_queue_gets_nothing():
    q = event_bus.subscribe()
    event_bus.unsubscribe(q)
    event_bus.publish({"job_id": "j2", "status": "failed"})
    assert q.empty()


def test_sse_format():
    line = event_bus.format_sse({"a": 1})
    assert line == 'data: {"a": 1}\n\n'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/unit/test_event_bus.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `app/services/event_bus.py`**

```python
"""In-process pub/sub for job-status events (drives the SSE endpoint).

Consistent with the in-memory worker queue: single-process by design. A full
queue subscriber is skipped rather than blocking the publisher.
"""

from __future__ import annotations

import asyncio
import json

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def format_sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
```

- [ ] **Step 4: Create `app/api/events.py`**

```python
"""Server-sent events: job-status transitions for live UI updates."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services import event_bus

router = APIRouter(tags=["events"])

HEARTBEAT_S = 15.0


@router.get("/events")
async def events() -> StreamingResponse:
    async def stream():
        q = event_bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                    yield event_bus.format_sse(event)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            event_bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
```

Add `events` to `register_routers` in `app/api/__init__.py` (same pattern as Task 2: import it and `app.include_router(events.router)`).

- [ ] **Step 5: Publish transitions from `app/services/poll_service.py`**

Add the import at the top: `from app.services import event_bus, media` (replacing the existing `from app.services import media`).

After the `running` commit (right after `session.commit()` following `job.status = RenderStatus.running`):

```python
        event_bus.publish({"job_id": job.id, "status": "running"})
```

In `_fail()`, after `session.commit()`:

```python
    event_bus.publish({"job_id": job.id, "status": "failed", "error": error})
```

At the end of `process_job`, after the final `session.commit()` (the succeeded one):

```python
        event_bus.publish({"job_id": job.id, "status": "succeeded", "output_id": output.id})
```

- [ ] **Step 6: Run tests**

Run: `uv run --extra dev pytest tests/unit/test_event_bus.py tests/integration/ -q`
Expected: PASS (event bus tests + all existing integration tests still green)

- [ ] **Step 7: Commit**

```bash
git add app/services/event_bus.py app/api/events.py app/api/__init__.py app/services/poll_service.py tests/unit/test_event_bus.py
git commit -m "feat: SSE job-status events via in-process event bus"
```

---

## Task 4: Relationship + reorder endpoints, richer /graph nodes

**Files:**
- Modify: `app/services/scene_service.py` (cast/asset attach-detach, `shot_order` in `update_shot`)
- Modify: `app/api/scenes.py` (4 new routes, `shot_order` in `ShotEdit`)
- Modify: `app/api/graph.py` (nodes carry `data` for canvas thumbnails/status)
- Test: extend `tests/integration/test_scene_pipeline.py`

- [ ] **Step 1: Write failing tests** (append to `tests/integration/test_scene_pipeline.py`, reusing its existing client fixture — adapt fixture name to what's in the file)

```python
def test_cast_and_shot_asset_relationships(client_ctx):
    client = client_ctx  # adapt to the fixture's actual shape
    # seed via existing helpers/fixtures: scene_1, char_1, asset_1, shot_1 exist
    r = client.post("/scenes/scene_1/cast/char_1")
    assert r.status_code == 200
    assert "char_1" in r.json()["character_ids_json"]
    # idempotent
    r = client.post("/scenes/scene_1/cast/char_1")
    assert r.json()["character_ids_json"].count("char_1") == 1

    r = client.delete("/scenes/scene_1/cast/char_1")
    assert "char_1" not in r.json()["character_ids_json"]

    r = client.post("/shots/shot_1/assets/asset_1")
    assert "asset_1" in r.json()["asset_ids_json"]
    r = client.delete("/shots/shot_1/assets/asset_1")
    assert "asset_1" not in r.json()["asset_ids_json"]

    # unknown ids -> 404
    assert client.post("/scenes/scene_1/cast/char_NOPE").status_code == 404
    assert client.post("/shots/shot_NOPE/assets/asset_1").status_code == 404


def test_shot_reorder_via_patch(client_ctx):
    client = client_ctx
    r = client.patch("/shots/shot_1", json={"shot_order": 5})
    assert r.status_code == 200
    assert r.json()["shot_order"] == 5


def test_graph_nodes_carry_canvas_data(client_ctx):
    client = client_ctx
    nodes = client.get("/graph").json()["nodes"]
    by_id = {n["id"]: n for n in nodes}
    assert "data" in by_id["asset_1"]            # file_path for thumbnails
    scene_node = by_id["scene_1"]
    assert scene_node["data"]["aspect_ratio"]
```

(Match seeded ids to what the existing fixture creates — read the fixture first and reuse its ids; if it seeds different ids, use those.)

- [ ] **Step 2: Run to verify failures**

Run: `uv run --extra dev pytest tests/integration/test_scene_pipeline.py -q`
Expected: new tests FAIL (404 / missing keys), existing tests PASS.

- [ ] **Step 3: Add service functions to `app/services/scene_service.py`**

```python
def add_cast_member(session: Session, scene_id: str, character_id: str) -> Scene:
    scene = get_scene(session, scene_id)
    if session.get(Character, character_id) is None:
        raise NotFoundError(f"character {character_id} not found")
    ids = list(scene.character_ids_json or [])
    if character_id not in ids:
        scene.character_ids_json = [*ids, character_id]  # reassign: JSON column
        scene.updated_at = utcnow()
        session.add(scene)
        session.commit()
        session.refresh(scene)
    return scene


def remove_cast_member(session: Session, scene_id: str, character_id: str) -> Scene:
    scene = get_scene(session, scene_id)
    ids = list(scene.character_ids_json or [])
    if character_id in ids:
        scene.character_ids_json = [i for i in ids if i != character_id]
        scene.updated_at = utcnow()
        session.add(scene)
        session.commit()
        session.refresh(scene)
    return scene


def attach_shot_asset(session: Session, shot_id: str, asset_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    if session.get(Asset, asset_id) is None:
        raise NotFoundError(f"asset {asset_id} not found")
    ids = list(shot.asset_ids_json or [])
    if asset_id not in ids:
        shot.asset_ids_json = [*ids, asset_id]
        shot.updated_at = utcnow()
        session.add(shot)
        session.commit()
        session.refresh(shot)
    return shot


def detach_shot_asset(session: Session, shot_id: str, asset_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError(f"shot {shot_id} not found")
    ids = list(shot.asset_ids_json or [])
    if asset_id in ids:
        shot.asset_ids_json = [i for i in ids if i != asset_id]
        shot.updated_at = utcnow()
        session.add(shot)
        session.commit()
        session.refresh(shot)
    return shot
```

Check imports at the top of `scene_service.py` — ensure `Asset`, `Character`, `utcnow` are imported (`from app.models import Asset, Character, ...`; `from app.models.base import utcnow`).

Also extend `update_shot(...)` with a `shot_order: int | None = None` keyword and the corresponding `if shot_order is not None: shot.shot_order = shot_order` branch.

- [ ] **Step 4: Add routes to `app/api/scenes.py`**

Add `shot_order: int | None = None` to `ShotEdit`. Then:

```python
@router.post("/scenes/{scene_id}/cast/{character_id}")
def add_cast(scene_id: str, character_id: str, session: Session = Depends(get_session)):
    return scene_service.add_cast_member(session, scene_id, character_id)


@router.delete("/scenes/{scene_id}/cast/{character_id}")
def remove_cast(scene_id: str, character_id: str, session: Session = Depends(get_session)):
    return scene_service.remove_cast_member(session, scene_id, character_id)


@router.post("/shots/{shot_id}/assets/{asset_id}")
def attach_asset(shot_id: str, asset_id: str, session: Session = Depends(get_session)):
    return scene_service.attach_shot_asset(session, shot_id, asset_id)


@router.delete("/shots/{shot_id}/assets/{asset_id}")
def detach_asset(shot_id: str, asset_id: str, session: Session = Depends(get_session)):
    return scene_service.detach_shot_asset(session, shot_id, asset_id)
```

Confirm the PATCH `/shots/{id}` handler forwards `shot_order` (it passes `**body.model_dump(exclude_none=True)`-style or named args — if named, add `shot_order=body.shot_order`).

- [ ] **Step 5: Enrich `/graph` nodes in `app/api/graph.py`**

Change the `node()` helper and call sites so each node carries a `data` dict the canvas can render from:

```python
    def node(id: str, type_: str, label: str, **data) -> None:
        nodes.append({"id": id, "type": type_, "label": label, "data": data})
```

Call-site additions:
- asset: `node(a.id, "asset", a.name or a.id, file_path=a.file_path, asset_type=a.type)`
- scene: `node(s.id, "scene", s.title or s.id, aspect_ratio=s.aspect_ratio, duration=s.duration, summary=s.summary)`
- shot: `node(sh.id, "shot", f"#{sh.shot_order + 1} {sh.prompt[:40]}", scene_id=sh.scene_id, shot_order=sh.shot_order, duration=sh.duration, prompt=sh.prompt, camera=sh.camera, movement=sh.movement)`
- render_job: `node(j.id, "render_job", ..., status=str(j.status))`
- output: `node(o.id, "output", ..., video_path=o.video_path, thumbnail_path=o.thumbnail_path, captioned_path=o.captioned_path)`
- character: `node(c.id, "character", c.name)` (no extra data needed; thumbnail comes from its reference asset edge)

- [ ] **Step 6: Run tests, fix, commit**

Run: `uv run --extra dev pytest tests/ -q` — all pass.

```bash
git add app/services/scene_service.py app/api/scenes.py app/api/graph.py tests/integration/test_scene_pipeline.py
git commit -m "feat: cast/asset relationship endpoints, shot reorder, canvas-ready graph nodes"
```

---

## Task 5: Caption config + whisper model parameter

**Files:**
- Modify: `app/services/caption_service.py` (model registry, per-size cache, `model` param)
- Modify: `app/api/render.py` (`CaptionRequest.model`, `GET /caption-config`)
- Test: extend `tests/unit/test_captions.py` and `tests/integration/test_render_pipeline.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_captions.py`:

```python
from app.services.caption_service import WHISPER_MODELS


def test_whisper_model_registry():
    assert WHISPER_MODELS == ["tiny", "base", "small", "medium", "large-v3"]
```

Append to `tests/integration/test_render_pipeline.py` (inside/alongside the existing caption-endpoint test, which already mocks `transcribe` and `burn_subtitles` — extend the `transcribe` mock to capture kwargs):

```python
def test_caption_config_endpoint(client):  # adapt fixture name
    r = client.get("/caption-config")
    assert r.status_code == 200
    body = r.json()
    assert "kids" in body["styles"]
    assert "large-v3" in body["models"]
    assert body["default_model"] == "small"
    assert body["default_language"] == "zh"
```

And in the existing caption test, POST with `{"style": "kids", "model": "tiny"}` and assert the captured `transcribe` call received `model_size="tiny"`.

- [ ] **Step 2: Run to verify failures**

Run: `uv run --extra dev pytest tests/unit/test_captions.py tests/integration/test_render_pipeline.py -q`
Expected: new tests FAIL (ImportError / 404).

- [ ] **Step 3: Implement in `app/services/caption_service.py`**

```python
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
```

Change the lazy model cache from a single instance to a per-size dict (current code caches one `WhisperModel`; replace with):

```python
_models: dict[str, "WhisperModel"] = {}


def _get_model(size: str):
    from faster_whisper import WhisperModel

    if size not in _models:
        _models[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _models[size]
```

`transcribe(video_path, language, model_size: str | None = None)` — resolve `size = model_size or get_settings().whisper_model` and use `_get_model(size)`. `caption_output(session, output_id, style, language="zh", model: str | None = None)` — validate `model in WHISPER_MODELS` when provided (raise the project's `ValidationError`/`ValueError` consistent with existing style errors), pass through to `transcribe`.

- [ ] **Step 4: API in `app/api/render.py`**

```python
class CaptionRequest(BaseModel):
    style: str = "kids"
    language: str | None = "zh"  # None -> auto-detect
    model: str | None = None     # None -> settings.whisper_model
```

Pass `model=body.model` into `caption_service.caption_output`. Add:

```python
@router.get("/caption-config")
def caption_config():
    from app.config import get_settings
    from app.services.caption_service import STYLES, WHISPER_MODELS

    return {
        "styles": list(STYLES),
        "models": WHISPER_MODELS,
        "default_model": get_settings().whisper_model,
        "default_language": "zh",
    }
```

Keep `GET /caption-styles` as-is (back-compat).

- [ ] **Step 5: Run, commit**

Run: `uv run --extra dev pytest tests/ -q` — all pass.

```bash
git add app/services/caption_service.py app/api/render.py tests/unit/test_captions.py tests/integration/test_render_pipeline.py
git commit -m "feat: caption-config endpoint + selectable whisper model"
```

---

## Task 6: Register render outputs as Assets

**Files:**
- Modify: `app/services/poll_service.py` (create Asset on success)
- Modify: `app/services/caption_service.py` (mirror captioned_path onto the asset)
- Test: extend `tests/integration/test_render_pipeline.py`

- [ ] **Step 1: Write failing test** (append; the render-pipeline test already drives a job to `succeeded`)

```python
def test_successful_render_registers_video_asset(client_ctx):
    # after the existing render flow reaches succeeded:
    assets = client.get("/assets").json()
    video_assets = [a for a in assets if a["type"] == "video"]
    assert len(video_assets) == 1
    a = video_assets[0]
    assert a["file_path"].endswith(".mp4")
    assert a["metadata_json"]["render_job_id"]
    assert a["metadata_json"]["render_output_id"]
```

And after the caption-endpoint test runs, assert the same asset's `metadata_json["captioned_path"]` is set.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest tests/integration/test_render_pipeline.py -q` — new assertions FAIL.

- [ ] **Step 3: Implement in `app/services/poll_service.py`**

Import `Asset` (`from app.models import Asset, RenderJob, RenderOutput, RenderStatus`). After the `session.refresh(output)` line:

```python
        # Surface the render in the Assets library (reusable as a reference).
        session.add(Asset(
            type="video",
            name=f"Render {job.scene_id or job.id}",
            file_path=str(video_path),
            metadata_json={
                "render_output_id": output.id,
                "render_job_id": job.id,
                "scene_id": job.scene_id,
            },
        ))
        session.commit()
```

- [ ] **Step 4: Mirror captions in `app/services/caption_service.py`**

In `caption_output`, after setting and committing `output.captioned_path`:

```python
    from sqlmodel import select

    from app.models import Asset

    for a in session.exec(select(Asset)).all():
        if a.metadata_json.get("render_output_id") == output_id:
            a.metadata_json = {**a.metadata_json, "captioned_path": output.captioned_path}
            session.add(a)
            session.commit()
            break
```

(Linear scan is fine: SQLite JSON columns aren't queryable here and the table is small.)

- [ ] **Step 5: Run full suite, commit**

Run: `uv run --extra dev pytest tests/ -q` — all pass.

```bash
git add app/services/poll_service.py app/services/caption_service.py tests/integration/test_render_pipeline.py
git commit -m "feat: register render outputs in the Assets library"
```

**Backend phase complete — the frontend tasks below depend on Tasks 1–6 being merged.**

---

## Task 7: Frontend foundation — Svelte 5 + Tailwind + shadcn-svelte

**Files:** `frontend/package.json`, `frontend/svelte.config.js`, `frontend/src/app.css`, `frontend/components.json` (new), `frontend/src/lib/components/ui/*` (generated)

No unit tests for this task; the gate is `npm run build` + visual parity.

- [ ] **Step 1: Migrate to Svelte 5**

```bash
export PATH="$HOME/.local/node/bin:$PATH"
cd frontend
npx sv migrate svelte-5      # accept; it codemods $props/$state/onclick where safe
npm i -D svelte@^5 @sveltejs/kit@latest @sveltejs/vite-plugin-svelte@latest vite@latest @sveltejs/adapter-static@latest
npm run build
```

Expected: build passes. Fix any leftovers the codemod flags (it inserts `@migration` comments) — typical fixes: `export let x` → `let { x } = $props()`, `on:click` → `onclick`, reactive `$:` → `$derived`/`$effect`. The app is 6 small pages; fix manually.

- [ ] **Step 2: Add Tailwind + init shadcn-svelte**

```bash
npx sv add tailwindcss       # adds tailwind v4 + vite plugin + app.css import
npx shadcn-svelte@latest init   # base color: slate; css: src/app.css; alias $lib/components
npx shadcn-svelte@latest add button card select tabs dialog sheet badge table input label textarea separator scroll-area resizable sonner skeleton tooltip dropdown-menu
npm i lucide-svelte
npm run build
```

Expected: build passes; `src/lib/components/ui/` populated. Note: shadcn-svelte init/add are interactive — accept defaults except base color `slate`. If the CLI asks about Tailwind v4 vs v3, choose v4 (the `sv add` default).

- [ ] **Step 3: Port the dark studio theme**

Keep dark-only: add `class="dark"` on `<html>` in `frontend/src/app.html`. Move any custom tokens from the old `app.css` into the `:root`/`.dark` CSS-variable block shadcn generated. Delete dead hand-rolled classes only when the page that used them is restyled (Task 8) — don't break pages now.

- [ ] **Step 4: Verify each page still loads**

```bash
npm run build && npm run preview -- --port 4173
```

Open Dashboard, Assets, Characters, Scenes, Render, Graph — all render without console errors (backend on :8000: `uv run uvicorn app.main:app --port 8000` from repo root).

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "chore: migrate frontend to Svelte 5 + Tailwind + shadcn-svelte"
```

---

## Task 8: Restyle existing pages with shadcn + lucide

**Files:** `frontend/src/routes/+layout.svelte`, `frontend/src/routes/{+page,assets,characters,scenes,render}/+page.svelte`, `frontend/src/app.css`

- [ ] **Step 1: New layout** — sidebar becomes a slim left rail with lucide icons + labels; `/` is "Studio". Replace `frontend/src/routes/+layout.svelte`:

```svelte
<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { Clapperboard, Image, Users, ListVideo, Film } from 'lucide-svelte';
  import { Toaster } from '$lib/components/ui/sonner';

  let { children } = $props();

  const nav = [
    { href: '/', label: 'Studio', icon: Clapperboard },
    { href: '/assets', label: 'Assets', icon: Image },
    { href: '/characters', label: 'Characters', icon: Users },
    { href: '/scenes', label: 'Scenes', icon: ListVideo },
    { href: '/render', label: 'Render', icon: Film }
  ];
</script>

<div class="flex h-screen bg-background text-foreground">
  <aside class="flex w-48 shrink-0 flex-col border-r border-border p-3 gap-1">
    <div class="px-2 py-3 text-sm font-semibold tracking-wide">VideoFlow</div>
    {#each nav as item}
      <a
        href={item.href}
        class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent
               {$page.url.pathname === item.href ? 'bg-accent font-medium' : 'text-muted-foreground'}"
      >
        <item.icon class="size-4" />
        {item.label}
      </a>
    {/each}
  </aside>
  <main class="flex-1 overflow-auto">
    {@render children()}
  </main>
</div>
<Toaster richColors />
```

- [ ] **Step 2: Restyle pages one at a time** (assets → characters → scenes → render → dashboard). Mechanical swaps, keep all behavior: `<button>` → shadcn `Button`, panels → `Card`, `<select>` → shadcn `Select`, tables → shadcn `Table`, status text → `Badge` (`succeeded`→default, `failed`→destructive, `running`→secondary), errors → `toast.error(...)` from sonner instead of inline error divs where it reads better. Page padding `p-6`, headings `text-lg font-semibold mb-4`. **Assets page additions** (spec): show `type === "video"` assets with a `<video>` preview (reuse `VideoPreview` component) and a "From render" badge when `metadata_json.render_job_id` exists.

- [ ] **Step 3: Render-page caption controls gain model + language** — replace the style-only select with three selects fed by `GET /caption-config`:

```svelte
<script lang="ts">
  // in addition to existing state:
  let captionCfg: { styles: string[]; models: string[]; default_model: string; default_language: string } | null = $state(null);
  // onMount: captionCfg = await get('/caption-config');
  // per-output selections, defaulting from captionCfg
</script>
<!-- style / model / language selects + the existing Auto captions button; POST body:
     { style, model, language } -->
```

- [ ] **Step 4: Build, eyeball every page, commit**

```bash
npm run build && npm run preview -- --port 4173
git add frontend && git commit -m "feat: restyle all pages with shadcn-svelte + lucide"
```

---

## Task 9: Entity canvas (@xyflow/svelte)

**Files:**
- Create: `frontend/src/lib/canvas/layout.ts`, `frontend/src/lib/canvas/transform.ts`, `frontend/src/lib/canvas/EntityNode.svelte`, `frontend/src/lib/canvas/EntityCanvas.svelte`, `frontend/src/lib/canvas/NodePanel.svelte`
- Delete: `frontend/src/routes/graph/` (page replaced by the canvas)

- [ ] **Step 1: Install**

```bash
export PATH="$HOME/.local/node/bin:$PATH" && cd frontend
npm i @xyflow/svelte @dagrejs/dagre
```

- [ ] **Step 2: `src/lib/canvas/transform.ts`** — API graph → flow nodes/edges:

```ts
import type { Node, Edge } from '@xyflow/svelte';

export type ApiGraph = {
  nodes: { id: string; type: string; label: string; data?: Record<string, any> }[];
  edges: { source: string; target: string; label: string }[];
};

export function toFlow(g: ApiGraph): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = g.nodes.map((n) => ({
    id: n.id,
    type: 'entity',
    position: { x: 0, y: 0 }, // dagre assigns; localStorage overrides
    data: { kind: n.type, label: n.label, ...(n.data ?? {}) }
  }));
  const edges: Edge[] = g.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    label: e.label || undefined
  }));
  return { nodes, edges };
}

const POS_KEY = 'videoflow.canvas.positions';

export function loadPositions(): Record<string, { x: number; y: number }> {
  try { return JSON.parse(localStorage.getItem(POS_KEY) ?? '{}'); } catch { return {}; }
}

export function savePositions(nodes: Node[]) {
  const pos = Object.fromEntries(nodes.map((n) => [n.id, n.position]));
  localStorage.setItem(POS_KEY, JSON.stringify(pos));
}
```

- [ ] **Step 3: `src/lib/canvas/layout.ts`** — dagre auto-layout:

```ts
import dagre from '@dagrejs/dagre';
import type { Node, Edge } from '@xyflow/svelte';

const W = 180, H = 64;

export function layout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    return { ...n, position: { x: p.x - W / 2, y: p.y - H / 2 } };
  });
}
```

- [ ] **Step 4: `src/lib/canvas/EntityNode.svelte`** — one custom node, switching on `data.kind`; image thumbs for assets, video poster for outputs, status badge for jobs:

```svelte
<script lang="ts">
  import { Handle, Position, type NodeProps } from '@xyflow/svelte';
  import { Users, Image, ListVideo, Film, Clapperboard, LayoutGrid } from 'lucide-svelte';
  import { mediaUrl, isImage } from '$lib/api';
  import { Badge } from '$lib/components/ui/badge';

  let { data }: NodeProps = $props();

  const icons: Record<string, any> = {
    character: Users, asset: Image, scene: Clapperboard,
    shot: ListVideo, render_job: Film, output: Film, storyboard: LayoutGrid
  };
  const Icon = $derived(icons[data.kind] ?? Image);
</script>

<div class="w-[180px] rounded-md border border-border bg-card px-2 py-1.5 text-xs shadow-sm
            data-[kind=scene]:border-primary" data-kind={data.kind}>
  <Handle type="target" position={Position.Left} />
  <div class="flex items-center gap-1.5">
    <Icon class="size-3.5 shrink-0 text-muted-foreground" />
    <span class="truncate font-medium">{data.label}</span>
  </div>
  {#if data.kind === 'asset' && data.file_path && isImage(data.file_path)}
    <img src={mediaUrl(data.file_path)} alt={data.label} class="mt-1 h-16 w-full rounded object-cover" />
  {:else if data.kind === 'output' && data.thumbnail_path}
    <img src={mediaUrl(data.thumbnail_path)} alt={data.label} class="mt-1 h-16 w-full rounded object-cover" />
  {/if}
  {#if data.kind === 'render_job'}
    <Badge variant={data.status === 'succeeded' ? 'default' : data.status === 'failed' ? 'destructive' : 'secondary'} class="mt-1">
      {data.status}
    </Badge>
  {/if}
  <Handle type="source" position={Position.Right} />
</div>
```

- [ ] **Step 5: `src/lib/canvas/EntityCanvas.svelte`** — flow with connect/detach/reorder rules:

```svelte
<script lang="ts">
  import { SvelteFlow, Background, Controls, MiniMap, type Node, type Edge, type Connection } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { get, post, del } from '$lib/api';
  import { toFlow, loadPositions, savePositions } from './transform';
  import { layout } from './layout';
  import EntityNode from './EntityNode.svelte';
  import { toast } from 'svelte-sonner';

  let { onselect }: { onselect: (node: Node | null) => void } = $props();

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);
  const nodeTypes = { entity: EntityNode };

  export async function refresh() {
    const g = toFlow(await get('/graph'));
    const saved = loadPositions();
    const laid = layout(g.nodes, g.edges);
    nodes = laid.map((n) => (saved[n.id] ? { ...n, position: saved[n.id] } : n));
    edges = g.edges;
  }

  export function focusNode(id: string) {
    nodes = nodes.map((n) => ({ ...n, selected: n.id === id }));
    // SvelteFlow's fitView on selection: use the useSvelteFlow() hook's fitView
    // with { nodes: [{ id }], duration: 400 } from a child component if needed.
  }

  $effect(() => { refresh(); });

  function kind(id: string) { return nodes.find((n) => n.id === id)?.data?.kind; }

  async function onconnect(c: Connection) {
    try {
      // character -> scene = cast; asset -> shot = reference (either drag direction)
      const [a, b] = [c.source, c.target];
      if (kind(a) === 'character' && kind(b) === 'scene') await post(`/scenes/${b}/cast/${a}`, {});
      else if (kind(b) === 'character' && kind(a) === 'scene') await post(`/scenes/${a}/cast/${b}`, {});
      else if (kind(a) === 'asset' && kind(b) === 'shot') await post(`/shots/${b}/assets/${a}`, {});
      else if (kind(b) === 'asset' && kind(a) === 'shot') await post(`/shots/${a}/assets/${b}`, {});
      else { toast.error('Connect character→scene or asset→shot'); return; }
      await refresh();
    } catch (e: any) { toast.error(e.message); }
  }

  async function ondelete({ edges: deleted }: { nodes: Node[]; edges: Edge[] }) {
    for (const e of deleted) {
      try {
        if (kind(e.source) === 'scene' && kind(e.target) === 'character')
          await del(`/scenes/${e.source}/cast/${e.target}`);
        else if (kind(e.source) === 'shot' && kind(e.target) === 'asset')
          await del(`/shots/${e.source}/assets/${e.target}`);
      } catch (err: any) { toast.error(err.message); }
    }
    await refresh();
  }
</script>

<div class="h-full w-full">
  <SvelteFlow
    bind:nodes bind:edges {nodeTypes} fitView
    onconnect={onconnect}
    ondelete={ondelete}
    onnodeclick={({ node }) => onselect(node)}
    onpaneclick={() => onselect(null)}
    onnodedragstop={() => savePositions(nodes)}
    proOptions={{ hideAttribution: true }}
  >
    <Background />
    <Controls />
    <MiniMap />
  </SvelteFlow>
</div>
```

Add `del` to `frontend/src/lib/api.ts` if missing (same shape as `post` but method DELETE, no body). Check the installed `@xyflow/svelte` docs if prop names differ (`onconnect`/`ondelete`/`onnodeclick` are the Svelte 5 callback props in v1; in v0.x they were `on:connect` events — match the installed major version).

- [ ] **Step 6: `src/lib/canvas/NodePanel.svelte`** — side panel editing per kind (scene fields → `PATCH /scenes/{id}`; shot fields incl. `shot_order` → `PATCH /shots/{id}`; output → video preview + caption controls reusing the Task 8 caption UI; others read-only). Use shadcn `Sheet` (open when a node is selected), `Input`/`Textarea`/`Button`, save → toast + `refresh()` callback prop. Fields map exactly to `SceneEdit`/`ShotEdit` models.

- [ ] **Step 7: Delete the old graph page and nav entry**

```bash
rm -r frontend/src/routes/graph
```

(Nav already replaced in Task 8.)

- [ ] **Step 8: Build + manual check, commit**

```bash
npm run build && npm run preview -- --port 4173
```

With the backend running and existing data: open Studio, see laid-out entity graph with thumbnails; drag a node (position survives reload); connect 乐乐 → a scene (cast updates, edge appears); delete that edge; click a shot, edit prompt, Save (PATCH 200).

```bash
git add frontend && git commit -m "feat: editable entity canvas with @xyflow/svelte"
```

---

## Task 10: Chat panel (Svelte AI Elements) + action cards

**Files:**
- Create: `frontend/src/lib/chat/ChatPanel.svelte`, `frontend/src/lib/chat/ActionCard.svelte`

- [ ] **Step 1: Install Svelte AI Elements chat primitives**

Per https://svelte-ai-elements.vercel.app — add its registry to `frontend/components.json`:

```json
"registries": { "@ai-elements": "https://svelte-ai-elements.vercel.app/r/{name}.json" }
```

then:

```bash
npx shadcn-svelte@latest add @ai-elements/conversation @ai-elements/message @ai-elements/prompt-input
```

Fallback if the registry is unavailable: build the panel from shadcn `ScrollArea` + `Input` + `Button` directly — the markup below only assumes a scrollable message list and an input row, so swap the imports.

- [ ] **Step 2: `src/lib/chat/ActionCard.svelte`** — the pre-filled confirm card. Props: `intent`, `options`, `onran(result)`, `onfocus(nodeId)`. Renders per `intent.action`:

| action | controls (pre-filled from intent) | Run calls |
|---|---|---|
| generate_script | textarea seeded with `intent.idea` | `POST /scripts/generate {idea}` |
| generate_scenes | scene-script select | `POST /scenes/{scene_id}/generate` |
| generate_shots | scene select | `POST /scenes/{scene_id}/shots/generate` |
| storyboard | scene select | `POST /scenes/{scene_id}/storyboard` |
| render_scene | scene select | `POST /scenes/{scene_id}/render` |
| render_shot | scene + shot selects (shots fetched on scene change via `GET /scenes/{id}/shots`) | `POST /render/from-shot` |
| caption | output + style + model + language selects (from `/caption-config`) | `POST /outputs/{id}/caption` |
| unknown | static capability list, no Run | — |

Implementation: a `$state` copy of the intent slots, shadcn `Select`s bound to them fed by `options.scenes` / `options.characters` / `options.outputs` / caption config, one Run `Button` with busy state; on success `toast.success(...)`, call `onran(result)` and — when the result contains an id (`scene_id`, `job_id`, asset id) — `onfocus(thatId)` so the canvas highlights it. Errors → `toast.error`. Write the fetch arms as a simple `switch (intent.action)`.

- [ ] **Step 3: `src/lib/chat/ChatPanel.svelte`**

```svelte
<script lang="ts">
  import { post } from '$lib/api';
  import ActionCard from './ActionCard.svelte';
  // AI Elements imports (or the shadcn fallback primitives):
  // import { Conversation, ConversationContent } from '$lib/components/ai-elements/conversation';
  // import { Message, MessageContent } from '$lib/components/ai-elements/message';
  // import { PromptInput } from '$lib/components/ai-elements/prompt-input';

  type Msg =
    | { role: 'user'; text: string }
    | { role: 'assistant'; text: string; intent?: any; options?: any };

  let { onfocus, onmutate }: { onfocus: (id: string) => void; onmutate: () => void } = $props();

  let messages = $state<Msg[]>([
    { role: 'assistant', text: 'Tell me what to do — e.g. 「给乐乐的场景生成分镜图」, "render scene 我是乐乐", "add captions".' }
  ]);
  let input = $state('');
  let busy = $state(false);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    input = '';
    messages = [...messages, { role: 'user', text }];
    busy = true;
    try {
      const r = await post('/chat', { message: text });
      messages = [...messages, { role: 'assistant', text: r.intent.reply, intent: r.intent, options: r.options }];
    } catch (e: any) {
      messages = [...messages, { role: 'assistant', text: `Error: ${e.message}` }];
    } finally {
      busy = false;
    }
  }
</script>

<!-- Conversation list: render each message; assistant messages with
     intent.action !== 'unknown' additionally render
     <ActionCard intent={m.intent} options={m.options} {onfocus} onran={onmutate} />.
     Bottom: prompt input bound to `input`, submit -> send(), disabled while busy. -->
```

(Fill the markup with the installed AI Elements components — `Conversation` auto-scrolls; `PromptInput` handles Enter-to-send — or the shadcn fallback.)

- [ ] **Step 4: Build, manual check with backend running** (type the storyboard message, see the card pre-filled with the right scene, Run fires the endpoint), **commit**

```bash
npm run build
git add frontend && git commit -m "feat: guided-intent chat panel with action cards"
```

---

## Task 11: Studio shell + SSE store

**Files:**
- Create: `frontend/src/lib/sse.ts`
- Modify: `frontend/src/routes/+page.svelte` (dashboard → Studio split view)
- Modify: `frontend/src/routes/render/+page.svelte` (consume SSE instead of 5s polling)

- [ ] **Step 1: `src/lib/sse.ts`**

```ts
import { API_BASE } from '$lib/api';

export type JobEvent = { job_id: string; status: string; output_id?: string; error?: string };

/** Subscribe to job events; falls back to polling the caller provides. */
export function subscribeJobs(onEvent: (e: JobEvent) => void, onFallback?: () => void): () => void {
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let retries = 0;

  function startPolling() {
    if (!pollTimer && onFallback) pollTimer = setInterval(onFallback, 5000);
  }

  function connect() {
    es = new EventSource(`${API_BASE}/events`);
    es.onmessage = (ev) => { retries = 0; onEvent(JSON.parse(ev.data)); };
    es.onerror = () => {
      es?.close();
      if (++retries > 3) startPolling();
      else setTimeout(connect, 1000 * retries);
    };
  }
  connect();
  return () => { es?.close(); if (pollTimer) clearInterval(pollTimer); };
}
```

(Export `API_BASE` from `api.ts` if it isn't already.)

- [ ] **Step 2: Studio page — replace `frontend/src/routes/+page.svelte`**

```svelte
<script lang="ts">
  import * as Resizable from '$lib/components/ui/resizable';
  import EntityCanvas from '$lib/canvas/EntityCanvas.svelte';
  import NodePanel from '$lib/canvas/NodePanel.svelte';
  import ChatPanel from '$lib/chat/ChatPanel.svelte';
  import { subscribeJobs } from '$lib/sse';
  import { onMount } from 'svelte';
  import type { Node } from '@xyflow/svelte';

  let canvas: EntityCanvas;
  let selected = $state<Node | null>(null);

  onMount(() => subscribeJobs(() => canvas?.refresh(), () => canvas?.refresh()));
</script>

<Resizable.PaneGroup direction="horizontal" class="h-full">
  <Resizable.Pane defaultSize={72} minSize={40}>
    <EntityCanvas bind:this={canvas} onselect={(n) => (selected = n)} />
  </Resizable.Pane>
  <Resizable.Handle withHandle />
  <Resizable.Pane defaultSize={28} minSize={20} class="border-l border-border">
    <ChatPanel onfocus={(id) => canvas?.focusNode(id)} onmutate={() => canvas?.refresh()} />
  </Resizable.Pane>
</Resizable.PaneGroup>

<NodePanel node={selected} onclose={() => (selected = null)} onsaved={() => canvas?.refresh()} />
```

- [ ] **Step 3: Render page — swap the 5s `setInterval` for `subscribeJobs(refreshOneJob, refreshAll)`** keeping polling as the fallback path already built into `subscribeJobs`.

- [ ] **Step 4: Build + full manual pass, commit**

```bash
npm run build && npm run preview -- --port 4173
```

End-to-end check with backend running: Studio loads with canvas + chat; chat message produces a card; Run storyboard → canvas gains the 分镜图 node without manual refresh (SSE/refresh); resize the split; select node → panel edits save.

```bash
git add frontend && git commit -m "feat: studio split shell with live SSE updates"
```

---

## Task 12: Final verification + docs

- [ ] **Step 1: Full backend suite**

Run: `uv run --extra dev pytest tests/ -q` — expected: all pass, no warnings about coroutines.

- [ ] **Step 2: Frontend build**

Run: `cd frontend && npm run build` — expected: clean build.

- [ ] **Step 3: Live smoke test** — backend `uv run uvicorn app.main:app --port 8000`, frontend preview, run one real chat→storyboard→render→caption flow on existing data (this hits real AtlasCloud; confirm with the user before spending render credits).

- [ ] **Step 4: Update `README.md`** — Frontend section: Studio (chat + canvas) description, new endpoints table rows (`POST /chat`, `GET /events`, cast/asset relationship routes, `GET /caption-config`), note that outputs now appear in Assets. Remove the Graph-page mention.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: studio frontend + new endpoints"
```
