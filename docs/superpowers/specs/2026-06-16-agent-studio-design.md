# Agent Studio — editable prompts, tuning & context per agent

Date: 2026-06-16
Status: approved (global scope, v1)

## Goal

From **Settings → Agents**, let the user fully customize each AI agent:

1. **Prompt engineering** — override the agent's system prompt with free text (default shown, one-click reset).
2. **Tuning** — set temperature and max_retries (provider/model already configurable today).
3. **Relationships / "what each agent sees"** — toggle which optional context blocks flow *into* each agent (e.g. does `prompt_agent` receive the style guide? does `shot_agent` see the overall story?).

Scope decisions (locked with the user):
- **Global only** (no per-project scope in v1).
- **Full free-text prompt override** with a safe fallback to the default.
- **Context-flow control only** — the pipeline ORDER stays hardcoded (no reorder / DAG editor).

## Background (current architecture)

- `app/llm/prompts.py` — `PROMPTS[agent]` static system-prompt strings. **They contain no single-brace `{placeholder}` tokens**; context is NOT injected into the system prompt. (`str.format` over them is a defensive no-op.)
- `app/agents/<agent>.py` — each agent builds its **user prompt** from a list of `as_block(label, value)` calls joined by `\n\n`. Several blocks are conditional (`if style:`, `if story:` …). This conditional set IS the "what each agent sees" surface.
- `app/llm/skills.py` — `SKILLS[agent] = AgentSkill(name, system_prompt, provider, model, temperature, max_retries)`. An in-process mirror `_OVERRIDES` (loaded from DB at startup) overrides provider/model. `get_effective_skill(agent)` merges them.
- `app/llm/structured_client.py` — reads `get_effective_skill(agent)`; uses `skill.system_prompt`, `skill.temperature`, `skill.max_retries`. So a prompt/temp/retries override flows to the LLM with **zero new plumbing** once the mirror carries it. `_format()` silently returns the template on `KeyError/IndexError` (must be hardened — see Safety).
- `app/models/setting.py` — `AgentSetting(agent UNIQUE, project_id, provider, model, updated_at)`, one row per overridden agent.
- `app/database.py` — `_migrate()` is the additive-SQLite-migration home (ALTER TABLE … ADD COLUMN).
- `app/services/settings_service.py` — `set_override`, `get_overrides`, `load_overrides`, `effective_skill`, `agent_view`, `all_agents`.
- `app/api/settings.py` — `GET /settings/agents`, `PUT /settings/agents/{agent}`.
- `frontend/src/routes/settings/+page.svelte` — Agents tab: per-agent provider/model dropdowns.

## Design

### 1. Data model — extend `AgentSetting`

Add four nullable columns (one row per agent already exists for provider/model):

| column | type | meaning |
|---|---|---|
| `system_prompt` | TEXT NULL | full prompt override; NULL = code default |
| `temperature` | FLOAT NULL | NULL = skill default |
| `max_retries` | INT NULL | NULL = skill default |
| `context_excludes` | JSON NULL | list of optional context keys switched OFF |

Added via `_migrate()` `ALTER TABLE agent_settings ADD COLUMN …` (PRAGMA-guarded, like existing migrations). NULL everywhere = "use default", so existing rows and reset both Just Work.

### 2. In-process mirror (`skills.py`)

Replace `_OVERRIDES: dict[str, tuple]` with `_OVERRIDES: dict[str, dict]` carrying all override fields. Functions:
- `set_record(agent, *, provider, model, system_prompt, temperature, max_retries, context_excludes)` — store the full record (used by `load_overrides`).
- `context_excludes(agent) -> set[str]` — the disabled keys for an agent (empty if none).
- `get_effective_skill(agent)` — `dataclasses.replace(base, provider=…, model=…, system_prompt=…, temperature=…, max_retries=…)` applying any non-None override field.
- Keep `clear_overrides()`. Keep a back-compat `set_override(agent, provider, model)` (delegates to `set_record`), but the service rebuilds the whole mirror via `load_overrides(session)` after each write, so fine-grained mirror mutation isn't relied upon.

### 3. Context-source registry + gating

In `skills.py`:
```python
@dataclass(frozen=True)
class ContextSource:
    key: str
    label: str
    required: bool = False

AGENT_CONTEXT_SOURCES: dict[str, list[ContextSource]] = { ... }
```

`required=True` sources are shown locked-on in the UI (transparency) and are NOT gated in code. `required=False` (optional) sources are gated.

In `app/agents/base.py`:
```python
def gated_block(agent, key, label, value) -> list[str]:
    if value in (None, "", [], {}):       # same emptiness skip as today
        return []
    if key in skills.context_excludes(agent):
        return []
    return [as_block(label, value)]
```
Each agent module replaces its conditional `if x: parts.append(as_block(...))` with `parts += gated_block(agent, key, label, x)`. Trailing instruction clauses that depend on a source (e.g. scene_agent's "Match the project style guide …" when `style`) gate on `bool(value) and key not in excludes`.

`qa_agent`'s `reference_images` toggle additionally drops the reference images from the `images=` list (and the descriptive "Attached images" text reflects the new counts).

**Per-agent optional context sources** (key → label):

- **script_agent**: `style` (Project style guide), `characters` (Existing characters)
- **scene_agent**: `assets` (Linked assets), `available_characters` (Other available characters), `library` (Asset library), `style`, `story`  · required: `character_bibles`, `available_asset_ids`
- **shot_agent**: `characters` (Cast), `assets`, `style`, `story`
- **prompt_agent**: `style`, `story`, `character_bibles` (drives voice + appearance)
- **qa_agent**: `reference_images` (reference sheets / storyboard attached to vision)
- **intent_agent**: `history` (Conversation so far), `outputs` (Render outputs catalog), `state` (Project state)  · required: `scenes`, `characters`
- **asset_planner**: `library`, `characters`, `story`, `style`, `shots`
- **style_agent**: `scripts`, `scenes`, `characters`, `assets`
- **refine_agent**: `style`, `story`
- **idea_agent**: `style`, `characters`
- **character_memory**: `style`
- **asset_recogniser**: `known_character_ids`

### 4. Resolution path

`structured_client.generate()` already reads `skill.system_prompt / temperature / max_retries` from `get_effective_skill`. With the mirror carrying overrides, customizations take effect live. `context_excludes` is consulted by `gated_block` at prompt-assembly time.

### 5. Safety & validation

- **Harden `_format`** to catch `Exception` (not just `KeyError/IndexError`) and fall back to the raw template — a user-entered prompt with malformed braces must never crash an agent call.
- **Placeholder validation** (`prompts.extract_placeholders` via `string.Formatter().parse`, ignoring escaped `{{ }}`):
  - `allowed = extract_placeholders(default_prompt)` (empty for every current agent).
  - On save: malformed braces → **422**; any placeholder ∉ allowed → **422** (`"unknown placeholder {x}; this agent provides none"`). Missing-allowed → non-blocking `warnings` (moot today since allowed is empty, but future-proof).
- **Clamp** temperature to [0, 2], max_retries to [0, 5].
- **context_excludes** validated: every key must be a known *optional* source key for that agent (else 422).
- **Reset** nulls all four columns (and clears provider/model too) → back to code defaults.

### 6. API (`app/api/settings.py` + `settings_service.py`)

Routing and studio customization are kept on **separate endpoints** so a prompt
edit can never accidentally clear provider/model (the existing PUT conflates
"absent" with "clear"):

- `GET /settings/agents` — unchanged list (provider/model + a `customized: bool` flag added).
- `GET /settings/agents/{agent}` — **new**: full detail
  `{agent, label, provider, model, default_provider, default_model, customized, system_prompt, default_prompt, required_placeholders, temperature, default_temperature, max_retries, default_max_retries, context_sources:[{key,label,required,enabled}]}`.
- `PUT /settings/agents/{agent}` — **unchanged**: provider/model routing only.
- `PUT /settings/agents/{agent}/customization` — **new**: `{system_prompt?, temperature?, max_retries?, context_excludes?}`, REPLACE semantics (unset field → code default). Validates as in §5. Returns the detail view.
- `POST /settings/agents/{agent}/reset` — **new**: clear ALL customization (routing + studio).

Service: a unified `_upsert(session, agent, **changes)` updates only supplied columns, deletes the row only when every field is empty (preserves `test_clear_override_reverts`), then `load_overrides(session)` to rebuild the mirror. `load_overrides` now reads the full row and calls `skills.set_record`. `set_override` keeps its signature + `agent_view` return shape (test contract); `set_customization` REPLACES the four studio columns and leaves routing intact.

### 7. Frontend (`settings/+page.svelte`)

Each agent row becomes **expandable**. Collapsed: label + provider/model + "Customized" badge. Expanded:
- provider/model dropdowns (existing)
- temperature slider (0–2) + max-retries stepper (0–5)
- **"What this agent sees"** — checkbox list of `context_sources` (required = checked + disabled)
- **System prompt** textarea (pre-filled with default or current override) + inline validation error + **Reset to default** button (calls reset endpoint)
- Save (PUT) / per-field dirty handling consistent with the existing tab.

### 8. Testing

Backend (extends the green 576-test suite):
- migration adds columns; `load_overrides` round-trips prompt/temp/retries/excludes.
- `get_effective_skill` merges each override field.
- `gated_block` drops a block when its key is excluded; keeps it otherwise; required sources never gated.
- behavior per representative agent: excluding `style` removes the style block from the assembled user prompt; `qa_agent` `reference_images` exclude drops the images.
- placeholder validation: malformed braces → 422; unknown placeholder → 422; plain text → ok.
- temperature/retries clamping; context_excludes unknown-key → 422.
- reset restores defaults; provider/model-only override still deletes row on clear (existing tests stay green).
- API: GET detail shape; PUT each field; reset.
- `_format` no longer raises on malformed template.

## YAGNI cuts (v1)
- No per-project scope (global only).
- No pipeline reorder / DAG editor (context-flow only).
- No prompt versioning/history.

Both scope extensions can layer onto the same precedence + registry later.
