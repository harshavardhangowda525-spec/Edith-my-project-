import json
import time

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.config import Settings
from app.api.sse import sse
from app.dependencies import (get_ai, get_memory, get_retrieval, get_settings_dep, get_speech, get_tasks,
                              rate_limited_user)
from app.errors import ValidationFailed
from app.models.schemas import ChatRequest, ChatTurn, SpeakRequest, TranscriptionResponse
from app.services.ai_service import AIService
from app.services.assistant import assistant_events
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.security.authentication import AuthenticatedUser
from app.services.speech_service import SpeechService
from app.services.tasks import TaskEngine

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=20),
    prompt: str | None = Form(default=None, max_length=800),
    user: AuthenticatedUser = Depends(rate_limited_user),
    speech: SpeechService = Depends(get_speech),
    settings: Settings = Depends(get_settings_dep),
) -> TranscriptionResponse:
    """Convert a push-to-talk audio clip into text (server-side provider)."""
    data = await audio.read(settings.max_audio_bytes + 1)
    if len(data) > settings.max_audio_bytes:
        raise ValidationFailed("Audio file is too large", status_code=413)
    text = await speech.transcribe(data, audio.filename or "audio.webm",
                                   audio.content_type or "", language, prompt)
    return TranscriptionResponse(text=text, provider=speech.provider.name)


@router.post("/speak")
async def speak(
    body: SpeakRequest,
    user: AuthenticatedUser = Depends(rate_limited_user),
    speech: SpeechService = Depends(get_speech),
) -> Response:
    """Generate speech audio (server-side provider). Returns audio/mpeg."""
    audio, media_type = await speech.speak(body.text, body.voice, body.style)
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post("/ask")
async def ask(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=20),
    prompt: str | None = Form(default=None, max_length=800),
    history: str | None = Form(default=None, max_length=40_000),
    followup: bool = Form(default=False),
    address: str | None = Form(default=None, max_length=30),
    route: str | None = Form(default=None, max_length=10),
    client_time: str | None = Form(default=None, max_length=40),
    battery: int | None = Form(default=None, ge=0, le=100),
    user: AuthenticatedUser = Depends(rate_limited_user),
    speech: SpeechService = Depends(get_speech),
    settings: Settings = Depends(get_settings_dep),
    ai: AIService = Depends(get_ai),
    memory: MemoryService = Depends(get_memory),
    retrieval: RetrievalService = Depends(get_retrieval),
    tasks: TaskEngine = Depends(get_tasks),
) -> StreamingResponse:
    """One round trip for a spoken question: audio in, streamed events out.

    Events: transcript, then the same as /api/assistant/stream (meta, token..., action | ignore | end, done).
    Saves the phone a second request (and its latency) compared with transcribe + assistant.
    """
    data = await audio.read(settings.max_audio_bytes + 1)
    if len(data) > settings.max_audio_bytes:
        raise ValidationFailed("Audio file is too large", status_code=413)
    try:
        turns = [ChatTurn(**t) for t in json.loads(history)][-20:] if history else []
    except (ValueError, TypeError) as exc:
        raise ValidationFailed("history must be a JSON list of {role, content}") from exc
    t0 = time.perf_counter()
    text = await speech.transcribe(data, audio.filename or "audio.wav", audio.content_type or "", language, prompt)
    stt_ms = round((time.perf_counter() - t0) * 1000, 1)
    ai.metrics.observe("stt_ms", stt_ms)
    first = [{"type": "transcript", "text": text, "stt_ms": stt_ms}]
    if not text.strip():
        return sse(_empty(), first=first)
    body = ChatRequest(message=text, history=turns, followup=followup, address=address, language=language,
                       route=route if route in ("auto", "fast", "balanced", "deep") else None,
                       client_time=client_time, battery=battery)
    return sse(assistant_events(body, user.id, ai, memory, retrieval, tasks), first=first)


async def _empty():
    yield {"type": "done", "timings": {}, "route": "none"}
