"""Environment-based configuration for EDITH AI.

All credentials come from environment variables (or a local ``.env`` file).
Nothing secret is ever hard-coded or returned to clients.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application ---------------------------------------------------------
    app_name: str = "EDITH AI"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # --- AI provider ---------------------------------------------------------
    # "openai"    -> any OpenAI-compatible /chat/completions endpoint
    # "anthropic" -> Anthropic Messages API (dedicated adapter)
    # "mock"      -> deterministic offline responses, clearly labeled
    ai_provider: Literal["openai", "anthropic", "mock"] = "mock"
    ai_api_key: str | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"
    ai_allowed_models: str = ""  # comma-separated whitelist users may pick from
    ai_timeout_seconds: float = 30.0
    ai_max_output_tokens: int = 600
    ai_temperature: float = 0.4

    # --- Server-side speech (optional; browser speech is the V1 default) ----
    speech_provider: Literal["openai", "none"] = "none"
    speech_api_key: str | None = None
    speech_base_url: str = "https://api.openai.com/v1"
    stt_model: str = "whisper-1"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    max_audio_bytes: int = 10 * 1024 * 1024

    # --- Authentication -------------------------------------------------------
    # "personal" -> one owner protected by a long secret password (OWNER_ACCESS_TOKEN);
    #               intended for a single-user online deployment
    # "supabase" -> verify Supabase-issued JWTs (HS256 with the project JWT secret)
    # "local"    -> static bearer tokens from LOCAL_ACCESS_TOKENS (dev only)
    auth_mode: Literal["personal", "supabase", "local"] = "local"
    owner_access_token: str | None = None
    owner_user_id: str = "00000000-0000-0000-0000-000000000001"
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_service_role_key: str | None = None
    # "token1:user-uuid-1,token2:user-uuid-2"
    local_access_tokens: str = ""

    # --- Storage --------------------------------------------------------------
    # "memory"   -> in-process store (lost on restart; dev/tests)
    # "supabase" -> Supabase PostgREST using the service-role key server-side
    storage_backend: Literal["memory", "supabase"] = "memory"

    # --- Security -------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_minute: int = 30
    max_request_bytes: int = 1 * 1024 * 1024
    max_message_chars: int = 4000

    # --- Static frontend (single-container deployment) -------------------------
    # When set and the folder exists, the built React app is served from "/".
    static_dir: str | None = None

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_model_list(self) -> list[str]:
        models = [m.strip() for m in self.ai_allowed_models.split(",") if m.strip()]
        if self.ai_model not in models:
            models.insert(0, self.ai_model)
        return models

    @property
    def local_token_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for pair in self.local_access_tokens.split(","):
            if ":" in pair:
                token, user_id = pair.split(":", 1)
                if token.strip() and user_id.strip():
                    mapping[token.strip()] = user_id.strip()
        return mapping

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider == "mock" or bool(self.ai_api_key)

    @property
    def is_mock(self) -> bool:
        return self.ai_provider == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()

