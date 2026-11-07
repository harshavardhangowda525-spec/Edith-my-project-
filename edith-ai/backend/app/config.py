"""Environment-based configuration for EDITH AI.

All credentials come from environment variables (or a local ``.env`` file).
Nothing secret is ever hard-coded or returned to clients.
"""
from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


OPENAI_DEFAULT_URL = "https://api.openai.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"

# Named OpenAI-compatible services: AI_PROVIDER=<name> fills in the address and a
# starting model. AI_BASE_URL / AI_MODEL still override them when set.
# (base_url, default_model, needs_api_key)
OPENAI_COMPATIBLE_PRESETS: dict[str, tuple[str, str, bool]] = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", True),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini", True),
    "together": ("https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo", True),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat", True),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest", True),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", True),
    "ollama": ("http://localhost:11434/v1", "llama3.1", False),
    "lmstudio": ("http://localhost:1234/v1", "local-model", False),
}
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")
_PASTE_JUNK = " \t\r\n\"'`<>"

def _host(url: str) -> str:
    return urlsplit(url if "://" in url else "https://" + url).hostname or ""


# Default fast / deep models per provider (AI_MODEL is the balanced one). Override with
# AI_MODEL_FAST / AI_MODEL_DEEP. Providers not listed use AI_MODEL for every route.
ROUTE_PRESETS: dict[str, tuple[str, str]] = {
    "groq": ("llama-3.1-8b-instant", "openai/gpt-oss-120b"),
    "anthropic": ("claude-haiku-5-5", "claude-opus-5-5"),
}

ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com/v1"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5-5"
# Server speech-to-text services (OpenAI-compatible /audio/transcriptions): (base_url, stt_model)
SPEECH_PRESETS: dict[str, tuple[str, str]] = {
    "openai": (OPENAI_DEFAULT_URL, "whisper-1"),
    # whisper-large-v3: Groq lists 10.3% word error rate vs 12% for -turbo; accuracy matters for voice.
    "groq": ("https://api.groq.com/openai/v1", "whisper-large-v3"),
}
# Server text-to-speech: (model, default voice, max characters per request)
TTS_PRESETS: dict[str, tuple[str, str, int]] = {
    "openai": ("tts-1", "alloy", 4000),
    "groq": ("canopylabs/orpheus-v1-english", "hannah", 200),
}
GROQ_VOICES = ("autumn", "diana", "hannah", "austin", "daniel", "troy")
SUPPORTED_AI_PROVIDERS = ["openai", "anthropic", "mock", *OPENAI_COMPATIBLE_PRESETS]


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
    # "groq", "openrouter", "together", "deepseek", "mistral", "gemini", "ollama",
    # "lmstudio" -> OpenAI-compatible services with their address pre-filled
    # Anything else is reported as a configuration problem (the app still starts).
    ai_provider: str = "mock"
    ai_api_key: str | None = None
    ai_base_url: str = ""
    ai_model: str = ""
    ai_allowed_models: str = ""  # comma-separated whitelist users may pick from
    # Model routing: simple requests -> fast model, coding -> AI_MODEL, hard multi-step -> deep model.
    ai_routing: Literal["auto", "off"] = "auto"
    ai_model_fast: str = ""
    ai_model_deep: str = ""
    # Latency budgets (seconds) per route; a slower/failed model falls back to the next one.
    route_timeout_fast: float = 12.0
    route_timeout_balanced: float = 30.0
    route_timeout_deep: float = 60.0
    ai_max_output_tokens_deep: int = 2000
    ai_timeout_seconds: float = 30.0
    ai_max_output_tokens: int = 600
    ai_temperature: float = 0.4

    # --- Server-side speech (optional; browser speech is the V1 default) ----
    # "auto"   -> use the AI provider's speech-to-text when it has one (groq, openai)
    # "groq" | "openai" | "none"
    speech_provider: str = "auto"
    speech_api_key: str | None = None
    speech_base_url: str = ""
    stt_model: str = ""
    tts_model: str = ""
    tts_voice: str = ""
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

    # --- Lead finder (Google Places API, official Google Maps business data) ------
    google_maps_api_key: str | None = None

    # --- Email (Gmail SMTP with an App password; send-only) -----------------------
    gmail_address: str | None = None
    gmail_app_password: str | None = None
    email_sender_name: str | None = None

    # --- GitHub intelligence (optional; a fine-grained read-only token is enough) ----
    github_token: str | None = None
    github_default_repo: str | None = None   # "owner/name" used when you just say "check GitHub"

    # --- Background tasks & PC bridge ---------------------------------------------
    task_workers: int = 3
    bridge_job_timeout_s: float = 900.0

    # --- Logging: "text" (default) or "json" (one JSON object per line) -----------
    log_format: Literal["text", "json"] = "text"

    # --- Static frontend (single-container deployment) -------------------------
    # When set and the folder exists, the built React app is served from "/".
    static_dir: str | None = None

    @field_validator("ai_provider")
    @classmethod
    def _norm_provider(cls, v: str) -> str:
        return (v or "mock").strip().lower().replace("-", "").replace(" ", "") or "mock"

    @field_validator("owner_access_token", "supabase_url", "supabase_service_role_key",
                     "supabase_jwt_secret", "google_maps_api_key", "gmail_address", "github_token",
                     "github_default_repo", mode="before")
    @classmethod
    def _strip_pasted(cls, v: object) -> object:
        """Values pasted into hosting dashboards often carry spaces, newlines or quotes."""
        if isinstance(v, str):
            v = v.strip(_PASTE_JUNK)
            return v or None
        return v

    @field_validator("gmail_app_password", mode="before")
    @classmethod
    def _app_password(cls, v: object) -> object:
        """Google shows app passwords as 'abcd efgh ijkl mnop'; spaces are not part of it."""
        if isinstance(v, str):
            v = "".join(v.split()).strip(_PASTE_JUNK)
            return v or None
        return v

    @property
    def leads_configured(self) -> bool:
        return bool(self.google_maps_api_key)

    @property
    def email_configured(self) -> bool:
        return bool(self.gmail_address and self.gmail_app_password)

    @field_validator("owner_user_id", mode="before")
    @classmethod
    def _extract_uuid(cls, v: object) -> object:
        """Accept 'UID: <uuid>', quoted, upper-case or whitespace-padded pastes."""
        if isinstance(v, str):
            m = _UUID_RE.search(v)
            if m:
                h = m.group(0).replace("-", "").lower()
                return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
            return v.strip(_PASTE_JUNK) or "00000000-0000-0000-0000-000000000001"
        return v

    @model_validator(mode="after")
    def _fill_provider_defaults(self) -> "Settings":
        self.ai_api_key = (self.ai_api_key or "").strip() or None
        base, model = self.ai_base_url.strip(), self.ai_model.strip()
        preset = OPENAI_COMPATIBLE_PRESETS.get(self.ai_provider)
        if preset:
            # Ignore a leftover OpenAI address/model: it can't work with another service.
            if not base or base.rstrip("/") == OPENAI_DEFAULT_URL:
                base = preset[0]
            if not model or model == OPENAI_DEFAULT_MODEL:
                model = preset[1]
        elif self.ai_provider == "anthropic":
            base = base or ANTHROPIC_DEFAULT_URL
            model = model or ANTHROPIC_DEFAULT_MODEL
        # People often paste the full endpoint; keep only the API base.
        base = base.rstrip("/")
        for tail in ("/chat/completions", "/completions", "/messages", "/models"):
            if base.endswith(tail):
                base = base[: -len(tail)].rstrip("/")
        if preset and base and _host(base) == _host(preset[0]):
            base = preset[0]  # e.g. https://api.groq.com -> https://api.groq.com/openai/v1
        self.ai_base_url = base or OPENAI_DEFAULT_URL
        self.ai_model = model or OPENAI_DEFAULT_MODEL
        return self

    @property
    def speech_kind(self) -> str:
        """Resolved server speech provider: 'openai', 'groq' or 'none'."""
        sp = (self.speech_provider or "auto").strip().lower()
        if sp == "auto":
            if self.ai_provider in SPEECH_PRESETS and (self.speech_api_key or self.ai_api_key):
                return self.ai_provider
            return "none"
        return sp if sp in SPEECH_PRESETS else "none"

    @property
    def speech_base(self) -> str:
        return (self.speech_base_url.strip().rstrip("/")
                or SPEECH_PRESETS.get(self.speech_kind, (OPENAI_DEFAULT_URL, ""))[0])

    @property
    def tts_model_name(self) -> str:
        return self.tts_model.strip() or TTS_PRESETS.get(self.speech_kind, ("tts-1", "", 0))[0]

    @property
    def tts_voice_name(self) -> str:
        return self.tts_voice.strip() or TTS_PRESETS.get(self.speech_kind, ("", "alloy", 0))[1]

    @property
    def tts_max_chars(self) -> int:
        return TTS_PRESETS.get(self.speech_kind, ("", "", 4000))[2]

    @property
    def stt_model_name(self) -> str:
        return self.stt_model.strip() or SPEECH_PRESETS.get(self.speech_kind, ("", "whisper-1"))[1]

    @property
    def ai_provider_kind(self) -> str | None:
        """Which adapter to use: 'openai', 'anthropic', 'mock', or None if unknown."""
        if self.ai_provider in ("openai", "anthropic", "mock"):
            return self.ai_provider
        if self.ai_provider in OPENAI_COMPATIBLE_PRESETS:
            return "openai"
        return None

    @property
    def ai_key_required(self) -> bool:
        preset = OPENAI_COMPATIBLE_PRESETS.get(self.ai_provider)
        return preset[2] if preset else self.ai_provider_kind != "mock"

    @property
    def ai_provider_problem(self) -> str | None:
        if self.ai_provider_kind is None:
            return (f"AI_PROVIDER '{self.ai_provider}' is not supported. Use one of: "
                    + ", ".join(SUPPORTED_AI_PROVIDERS))
        if self.ai_key_required and not self.ai_api_key:
            return "AI_API_KEY is not set on the server. Set it in backend/.env or use AI_PROVIDER=mock."
        return None

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def route_model(self, route: str) -> str:
        """Model for a route: 'fast', 'balanced' or 'deep'."""
        if route == "balanced" or self.ai_routing == "off":
            return self.ai_model
        preset = ROUTE_PRESETS.get(self.ai_provider)
        if route == "fast":
            return self.ai_model_fast.strip() or (preset[0] if preset else self.ai_model)
        return self.ai_model_deep.strip() or (preset[1] if preset else self.ai_model)

    def route_timeout(self, route: str) -> float:
        return {"fast": self.route_timeout_fast, "deep": self.route_timeout_deep}.get(route, self.route_timeout_balanced)

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
        return self.ai_provider_problem is None

    @property
    def is_mock(self) -> bool:
        return self.ai_provider_kind == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()

