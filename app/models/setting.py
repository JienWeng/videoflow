"""Persisted settings tables.

Three concerns live here:

- `AgentSetting`: per-agent LLM routing overrides (provider/model). A row exists
  only for agents the user has explicitly overridden; absence means "use the
  skill default". Nulls in provider/model clear the override. `project_id` scopes
  an override to one project (NULL = a global/default override).
- `AppSetting`: a generic key/value store for app-level defaults the user can
  change from Settings (default aspect ratio, caption style, model choices …).
  `scope` is 'global' or 'project'; a 'project' row is keyed by `project_id` and
  overlays the global row for that project (see settings_service.resolve).
- `ProviderSecret`: a configured provider's API key (+ optional base_url),
  persisted so keys survive a restart and can be changed from the UI without
  editing `.env`. The key is stored lightly obfuscated (base64) — this is NOT
  strong crypto, just to keep it from being plain-text-grep-able at rest; this is
  a single-user local app.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import new_id, utcnow


class AgentSetting(SQLModel, table=True):
    __tablename__ = "agent_settings"

    id: str = Field(default_factory=lambda: new_id("aset"), primary_key=True)
    agent: str = Field(unique=True, index=True)
    project_id: str | None = Field(default=None, index=True)
    provider: str | None = None
    model: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    id: str = Field(default_factory=lambda: new_id("appset"), primary_key=True)
    scope: str = Field(default="global", index=True)  # 'global' | 'project'
    project_id: str | None = Field(default=None, index=True)
    key: str = Field(index=True)
    # Stored as JSON so any value type (str/int/float/bool/list/dict) round-trips.
    value: object = Field(default=None, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)


class Connection(SQLModel, table=True):
    __tablename__ = "llm_connections"
    name: str = Field(primary_key=True)
    label: str
    preset: str
    protocol: str
    base_url: str | None = None
    model: str = ""
    mode: str = "auto"
    vision: bool = True


class ProviderSecret(SQLModel, table=True):
    __tablename__ = "provider_secrets"

    id: str = Field(default_factory=lambda: new_id("psec"), primary_key=True)
    provider: str = Field(unique=True, index=True)
    # Obfuscated (base64) API key — see settings_service._obfuscate/_deobfuscate.
    api_key: str = ""
    base_url: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
