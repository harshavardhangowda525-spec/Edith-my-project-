"""Server-side speech (optional).

V1 defaults to the browser's Web Speech API for both recognition and synthesis.
This service exists so a dedicated speech provider can be plugged in without
touching the API layer. ``SPEECH_PROVIDER=openai`` uses OpenAI-compatible
``/audio/transcriptions`` and ``/audio/speech`` endpoints.
"""
from __future__ import annotations

from typing import Protocol

import httpx

from app.config import Settings
from app.errors import ConfigurationError, ProviderError, ProviderTimeout, ValidationFailed

ALLOWED_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg",
    "audio/mp4", "audio/m4a", "audio/x-m4a", "video/webm",
}


class SpeechProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, filename: str, content_type: str,
                         language: str | None) -> str: ...

    async def speak(self, text: str, voice: str | None) -> tuple[bytes, str]: ...


class OpenAISpeechProvider:
    name = "openai"

    def __init__(self, s: Settings) -> None:
        key = s.speech_api_key or s.ai_api_key
        if not key:
            raise ConfigurationError("SPEECH_API_KEY is not set on the server")
        self.s, self.key = s, key

    async def _post(self, path: str, **kw: object) -> httpx.Response:
        url = self.s.speech_base_url.rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.s.ai_timeout_seconds, connect=10)) as c:
                r = await c.post(url, headers={"Authorization": f"Bearer {self.key}"}, **kw)  # type: ignore[arg-type]
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("Speech provider timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach the speech provider") from exc
        if r.status_code >= 400:
            raise ProviderError(f"Speech provider returned HTTP {r.status_code}")
        return r

    async def transcribe(self, audio: bytes, filename: str, content_type: str,
                         language: str | None) -> str:
        data = {"model": self.s.stt_model}
        if language:
            data["language"] = language.split("-")[0]
        r = await self._post("/audio/transcriptions", data=data,
                             files={"file": (filename, audio, content_type)})
        try:
            return str(r.json()["text"]).strip()
        except (ValueError, KeyError) as exc:
            raise ProviderError("Speech provider returned an unexpected response") from exc

    async def speak(self, text: str, voice: str | None) -> tuple[bytes, str]:
        r = await self._post("/audio/speech", json={
            "model": self.s.tts_model, "voice": voice or self.s.tts_voice,
            "input": text, "response_format": "mp3",
        })
        return r.content, "audio/mpeg"


class SpeechService:
    def __init__(self, settings: Settings, provider: SpeechProvider | None = None) -> None:
        self.settings = settings
        self._provider = provider

    @property
    def provider(self) -> SpeechProvider:
        if self._provider is None:
            if self.settings.speech_provider == "none":
                raise ConfigurationError(
                    "Server-side speech is not configured. The app uses your browser's built-in "
                    "speech recognition and synthesis instead.", code="speech_not_configured")
            self._provider = OpenAISpeechProvider(self.settings)
        return self._provider

    async def transcribe(self, audio: bytes, filename: str, content_type: str,
                         language: str | None = None) -> str:
        base_type = (content_type or "").split(";")[0].strip().lower()
        if base_type not in ALLOWED_AUDIO_TYPES:
            raise ValidationFailed(f"Unsupported audio type '{base_type or 'unknown'}'")
        if not audio:
            raise ValidationFailed("Audio file is empty")
        if len(audio) > self.settings.max_audio_bytes:
            raise ValidationFailed("Audio file is too large", status_code=413)
        return await self.provider.transcribe(audio, filename, base_type, language)

    async def speak(self, text: str, voice: str | None = None) -> tuple[bytes, str]:
        return await self.provider.speak(text, voice)
