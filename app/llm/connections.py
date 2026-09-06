"""Provider presets and named connections; no credentials in catalog entries."""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from sqlmodel import Session, select
from app.models.setting import Connection
from uuid import uuid4


@dataclass(frozen=True)
class Preset:
    label: str
    protocol: str
    url: str | None = None
    model: str = ""
    env: str = ""


PRESETS = {
    "minimax": Preset("MiniMax", "chat", "https://api.minimax.io/v1", "MiniMax-Text-01", "MINIMAX"),
    "openai": Preset("OpenAI API", "chat", "https://api.openai.com/v1", "gpt-5.6-luna", "OPENAI"),
    "anthropic": Preset("Anthropic / Claude", "anthropic", "https://api.anthropic.com", "claude-sonnet-4-6", "ANTHROPIC"),
    "gemini": Preset("Google Gemini", "chat", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "GEMINI"),
    "atlas": Preset("AtlasCloud", "chat", "https://api.atlascloud.ai/v1", "qwen/qwen3-vl-30b-a3b-instruct", "ATLASCLOUD"),
    "openrouter": Preset("OpenRouter", "chat", "https://openrouter.ai/api/v1", "", "OPENROUTER"),
    "deepseek": Preset("DeepSeek", "chat", "https://api.deepseek.com", "deepseek-chat", "DEEPSEEK"),
    "opencode": Preset("OpenCode Zen", "responses", "https://opencode.ai/zen/v1", "", "OPENCODE"),
    "opencode-go": Preset("OpenCode Go", "chat", "https://opencode.ai/zen/go/v1", "", "OPENCODE_GO"),
    "codex": Preset("ChatGPT via Codex", "codex", model="gpt-5.6-luna"),
    "custom": Preset("Custom endpoint", "chat"),
}


def catalog(session: Session | None = None) -> dict[str, dict]:
    entries = {k: {**asdict(v), "preset": k, "mode": "auto", "vision": True} for k, v in PRESETS.items()}
    if session is not None:
        for row in session.exec(select(Connection)).all():
            entries[row.name] = {"label": row.label, "preset": row.preset, "protocol": row.protocol,
                                 "url": row.base_url, "model": row.model, "env": "",
                                 "mode": row.mode, "vision": row.vision}
    return entries


def definition(name: str, session: Session | None = None) -> dict:
    if session is not None:
        return catalog(session)[name]
    if name in PRESETS:
        return catalog()[name]
    from app.database import engine
    with Session(engine) as db:
        return catalog(db)[name]


def env_value(name: str, suffix: str, fallback: str = "") -> str:
    from dotenv import dotenv_values
    preset = PRESETS.get(name)
    if preset is None:
        preset = PRESETS[definition(name)["preset"]]
    if not preset or not preset.env:
        return fallback
    key = f"{preset.env}_{suffix}"
    return os.environ.get(key, dotenv_values(".env").get(key) or fallback)


def request_headers(name: str) -> dict[str, str]:
    headers = {"User-Agent": "VideoFlow/0.1.0"}
    if definition(name)["preset"] in ("opencode", "opencode-go"):
        headers["x-opencode-session"] = str(uuid4())
    return headers
