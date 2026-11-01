from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from app.config import Settings
from app.dependencies import get_settings_dep, get_speech, rate_limited_user
from app.errors import ValidationFailed
from app.models.schemas import SpeakRequest, TranscriptionResponse
from app.security.authentication import AuthenticatedUser
from app.services.speech_service import SpeechService

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=20),
    user: AuthenticatedUser = Depends(rate_limited_user),
    speech: SpeechService = Depends(get_speech),
    settings: Settings = Depends(get_settings_dep),
) -> TranscriptionResponse:
    """Convert a push-to-talk audio clip into text (server-side provider)."""
    data = await audio.read(settings.max_audio_bytes + 1)
    if len(data) > settings.max_audio_bytes:
        raise ValidationFailed("Audio file is too large", status_code=413)
    text = await speech.transcribe(data, audio.filename or "audio.webm",
                                   audio.content_type or "", language)
    return TranscriptionResponse(text=text, provider=speech.provider.name)


@router.post("/speak")
async def speak(
    body: SpeakRequest,
    user: AuthenticatedUser = Depends(rate_limited_user),
    speech: SpeechService = Depends(get_speech),
) -> Response:
    """Generate speech audio (server-side provider). Returns audio/mpeg."""
    audio, media_type = await speech.speak(body.text, body.voice)
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})
