from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import get_settings_dep
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
    )
