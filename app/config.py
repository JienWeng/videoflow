"""Application configuration — a single pydantic-settings source of truth.

Reads from the environment / `.env`. Required secrets are validated at startup
(see `Settings.require_keys`) so the app fails fast rather than at first call.
"""

from __future__ import annotations

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
    openai_model: str = Field(default="gpt-5.6-luna", alias="OPENAI_MODEL")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="GEMINI_BASE_URL",
    )
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    deepseek_model: str = Field(default="deepseek-v4-flash", alias="DEEPSEEK_MODEL")

    # AtlasCloud (image + video gateway)
    atlascloud_api_key: str = Field(default="", alias="ATLASCLOUD_API_KEY")
    atlascloud_base_url: str = Field(
        default="https://api.atlascloud.ai/api/v1", alias="ATLASCLOUD_BASE_URL"
    )
    atlas_image_model: str = Field(
        default="openai/gpt-image-2/text-to-image", alias="ATLAS_IMAGE_MODEL"
    )
    atlas_video_model: str = Field(
        default="minimax/h3-developer/text-to-video",
        alias="ATLAS_VIDEO_MODEL",
    )
    atlas_image_quality: str = Field(default="low", alias="ATLAS_IMAGE_QUALITY")
    atlas_video_resolution: str = Field(default="480P", alias="ATLAS_VIDEO_RESOLUTION")
    atlas_video_prompt_expansion: bool = Field(
        default=False, alias="ATLAS_VIDEO_PROMPT_EXPANSION"
    )
    # Max reference images for the video model — live-verified Kling o3-pro
    # limit (ret:1201 "max number is 7" above 7, despite docs claiming 10).
    atlas_video_max_refs: int = Field(default=7, alias="ATLAS_VIDEO_MAX_REFS")
    # Reference-image generation (分镜图 with character sheets as inputs).
    atlas_image_ref_model: str = Field(
        default="google/nano-banana-2/edit", alias="ATLAS_IMAGE_REF_MODEL"
    )
    # AtlasCloud-hosted LLMs (OpenAI-compatible; NOT under /api/v1).
    atlas_llm_base_url: str = Field(
        default="https://api.atlascloud.ai/v1", alias="ATLAS_LLM_BASE_URL"
    )
    atlas_vl_model: str = Field(
        default="qwen/qwen3-vl-30b-a3b-instruct", alias="ATLAS_VL_MODEL"
    )

    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_image_model: str = Field(
        default="openai/gpt-image-2", alias="OPENROUTER_IMAGE_MODEL"
    )
    openrouter_video_model: str = Field(
        default="google/veo-3.1-lite", alias="OPENROUTER_VIDEO_MODEL"
    )

    # Default video aspect ratio (16:9 | 9:16 | 1:1). Configurable per deployment.
    default_aspect_ratio: str = Field(default="9:16", alias="DEFAULT_ASPECT_RATIO")
    default_video_provider: str = Field(default="atlascloud", alias="DEFAULT_VIDEO_PROVIDER")
    default_image_provider: str = Field(default="atlascloud", alias="DEFAULT_IMAGE_PROVIDER")

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

    # Auto-captions (faster-whisper model size: tiny/base/small/medium/large-v3)
    whisper_model: str = Field(default="small", alias="WHISPER_MODEL")

    # ---- App defaults (overridable per project/global via app_settings) ----
    # These are the DEFAULTS layer the settings resolver overlays DB rows on top
    # of. They live here so a fresh install has sensible behaviour with no DB rows.
    default_scene_duration: float = Field(
        default=5.0, alias="DEFAULT_SCENE_DURATION"
    )
    caption_style: str = Field(default="default", alias="CAPTION_STYLE")
    caption_language: str = Field(default="auto", alias="CAPTION_LANGUAGE")
    dialogue_language: str = Field(default="zh", alias="DIALOGUE_LANGUAGE")
    # Negative-prompt fragments appended to render requests (empty by default).
    render_negatives: list[str] = Field(
        default_factory=list, alias="RENDER_NEGATIVES"
    )

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


# A manually-managed singleton cache (NOT lru_cache) so a settings WRITE can
# invalidate it: provider keys / base-urls persisted to the DB are read back into
# a fresh Settings on the next get_settings() call, taking effect without a
# restart. settings_service.invalidate_settings_cache() is called on every write.
_cached_settings: Settings | None = None


def get_settings() -> Settings:
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = Settings()
    return _cached_settings


def invalidate_settings_cache() -> None:
    """Drop the cached Settings so the next get_settings() rebuilds from env.

    Called after persisting a provider secret / base-url so live clients that
    read get_settings() pick up the change. Also resets provider singletons that
    captured a Settings at construction time (the AtlasCloud client and the LLM
    structured client) so they rebuild against the new configuration."""
    global _cached_settings
    _cached_settings = None
    # Reset singletons that snapshot Settings at construction — guarded so this
    # stays import-safe even if those modules aren't loaded yet.
    try:
        from app.providers import atlascloud_client

        atlascloud_client._singleton = None
    except Exception:
        pass
    try:
        from app.llm import structured_client

        structured_client._singleton = None
    except Exception:
        pass
