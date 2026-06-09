"""Application configuration — a single pydantic-settings source of truth.

Reads from the environment / `.env`. Required secrets are validated at startup
(see `Settings.require_keys`) so the app fails fast rather than at first call.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # MiniMax (text LLM, OpenAI-compatible endpoint)
    minimax_api_key: str = Field(default="", alias="MINIMAX_API_KEY")
    minimax_base_url: str = Field(
        default="https://api.minimax.io/v1", alias="MINIMAX_BASE_URL"
    )
    minimax_text_model: str = Field(
        default="MiniMax-Text-01", alias="MINIMAX_TEXT_MODEL"
    )

    # Additional LLM providers (optional; used when a skill routes to them)
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="GEMINI_BASE_URL",
    )
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    # AtlasCloud (image + video gateway)
    atlascloud_api_key: str = Field(default="", alias="ATLASCLOUD_API_KEY")
    atlascloud_base_url: str = Field(
        default="https://api.atlascloud.ai/api/v1", alias="ATLASCLOUD_BASE_URL"
    )
    atlas_image_model: str = Field(
        default="baidu/ERNIE-Image-Turbo/text-to-image", alias="ATLAS_IMAGE_MODEL"
    )
    atlas_video_model: str = Field(
        default="kwaivgi/kling-video-o3-pro/reference-to-video",
        alias="ATLAS_VIDEO_MODEL",
    )

    # Default video aspect ratio (16:9 | 9:16 | 1:1). Configurable per deployment.
    default_aspect_ratio: str = Field(default="9:16", alias="DEFAULT_ASPECT_RATIO")

    # Storage / DB
    storage_root: Path = Field(default=Path("./storage"), alias="STORAGE_ROOT")
    database_url: str = Field(default="sqlite:///./db.sqlite", alias="DATABASE_URL")

    # LLM tuning
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")
    llm_timeout_s: float = Field(default=60.0, alias="LLM_TIMEOUT_S")
    llm_temperature: float = Field(default=0.4, alias="LLM_TEMPERATURE")

    # Render polling
    poll_interval_s: float = Field(default=5.0, alias="POLL_INTERVAL_S")
    poll_timeout_s: float = Field(default=600.0, alias="POLL_TIMEOUT_S")
    max_concurrent_polls: int = Field(default=3, alias="MAX_CONCURRENT_POLLS")

    # Worker
    worker_concurrency: int = Field(default=2, alias="WORKER_CONCURRENCY")

    @property
    def assets_dir(self) -> Path:
        return self.storage_root / "assets"

    @property
    def characters_dir(self) -> Path:
        return self.storage_root / "characters"

    @property
    def outputs_dir(self) -> Path:
        return self.storage_root / "outputs"

    def ensure_dirs(self) -> None:
        for d in (self.assets_dir, self.characters_dir, self.outputs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def missing_keys(self) -> list[str]:
        """Return the names of required secrets that are unset."""
        missing = []
        if not self.minimax_api_key:
            missing.append("MINIMAX_API_KEY")
        if not self.atlascloud_api_key:
            missing.append("ATLASCLOUD_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
