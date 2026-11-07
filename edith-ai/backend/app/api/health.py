from fastapi import APIRouter, Depends, Request

from app.config import Settings
from app.dependencies import current_user, get_settings_dep
from app.security.authentication import AuthenticatedUser
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings_dep)) -> HealthResponse:
    """Public liveness/config probe. Reports *whether* things are configured, never the values."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.environment,
        ai_provider=settings.ai_provider,
        ai_configured=settings.ai_configured,
        mock_mode=settings.is_mock,
        speech_provider=settings.speech_kind,
        storage_backend=settings.storage_backend,
        auth_mode=settings.auth_mode,
        tts_available=settings.speech_kind in ("openai", "groq"),
        leads_configured=settings.leads_configured,
        email_configured=settings.email_configured,
    )


@router.get("/api/metrics", tags=["health"])
def metrics(request: Request, user: AuthenticatedUser = Depends(current_user)) -> dict:
    """Live performance numbers: latency percentiles per stage, cache hit rate, failures, tokens."""
    from app.services.assistant import response_cache

    ai = request.app.state.ai
    snap = ai.metrics.snapshot()
    snap["circuit_breakers"] = ai.breaker.state()
    snap["routes"] = {r: request.app.state.settings.route_model(r) for r in ("fast", "balanced", "deep")}
    snap["response_cache_items"] = len(response_cache._data)
    return snap
