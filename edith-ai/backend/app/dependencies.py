"""FastAPI dependency wiring.

Services are created once per process and stored on ``app.state`` so tests can
swap them (e.g. a mocked AI provider) without monkey-patching modules.
"""
from __future__ import annotations

from fastapi import Depends, Header, Request

from app.config import Settings
from app.errors import RateLimited
from app.security.authentication import AuthenticatedUser, authenticate
from app.services.ai_service import AIService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.services.speech_service import SpeechService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_ai(request: Request) -> AIService:
    return request.app.state.ai


def get_speech(request: Request) -> SpeechService:
    return request.app.state.speech


def get_memory(request: Request) -> MemoryService:
    return request.app.state.memory


def get_retrieval(request: Request) -> RetrievalService:
    return request.app.state.retrieval


def get_tasks(request: Request):
    return request.app.state.tasks


def get_bridge(request: Request):
    return request.app.state.bridge


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    user = authenticate(authorization, request.app.state.settings)
    request.state.user_id = user.id
    return user


def rate_limited_user(
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
) -> AuthenticatedUser:
    """Authenticated user + per-user rate limit for expensive (AI/speech) endpoints."""
    allowed, retry = request.app.state.rate_limiter.check(f"user:{user.id}")
    if not allowed:
        err = RateLimited(f"Too many requests. Try again in {int(retry) + 1}s.")
        err.retry_after = int(retry) + 1  # type: ignore[attr-defined]
        raise err
    return user
