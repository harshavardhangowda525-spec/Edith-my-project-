"""Server-side speech (optional).

V1 defaults to the browser's Web Speech API for both recognition and synthesis.
This service exists so a dedicated speech provider can be plugged in without
touching the API layer. ``SPEECH_PROVIDER=openai`` uses OpenAI-compatible
``/audio/transcriptions`` and ``/audio/speech`` endpoints.
"""
from __future__ import annotations

import asyncio
import io
import re
import wave
from typing import Protocol

import httpx

from app.config import GROQ_VOICES, Settings
from app.errors import ConfigurationError, ProviderError, ProviderTimeout, ValidationFailed

ALLOWED_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg",
    "audio/mp4", "audio/m4a", "audio/x-m4a", "video/webm",
}


class SpeechProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, filename: str, content_type: str,
                         language: str | None, prompt: str | None = None) -> str: ...

    async def speak(self, text: str, voice: str | None, style: str | None = None) -> tuple[bytes, str]: ...


def split_for_tts(text: str, limit: int) -> list[str]:
    """Pieces of at most `limit` characters, cut at sentence, then clause, then word boundaries."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text] if text else []
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > limit:
            cut = max(sentence.rfind(sep, 0, limit) for sep in (", ", "; ", " - ", " "))
            cut = cut if cut > limit // 3 else limit
            pieces.append(sentence[:cut].strip(" ,;-"))
            sentence = sentence[cut:].strip(" ,;-")
        if sentence:
            if pieces and len(pieces[-1]) + 1 + len(sentence) <= limit:
                pieces[-1] += " " + sentence
            else:
                pieces.append(sentence)
    return [p for p in pieces if p]


def join_wavs(parts: list[bytes]) -> bytes:
    """Concatenate WAV files with the same format into one WAV."""
    if len(parts) == 1:
        return parts[0]
    out = io.BytesIO()
    writer: wave.Wave_write | None = None
    try:
        for part in parts:
            with wave.open(io.BytesIO(part)) as r:
                if writer is None:
                    writer = wave.open(out, "wb")
                    writer.setparams(r.getparams())
                writer.writeframes(r.readframes(r.getnframes()))
    except (wave.Error, EOFError) as exc:
        raise ProviderError("Speech provider returned audio EDITH couldn't join") from exc
    finally:
        if writer is not None:
            writer.close()
    return out.getvalue()


class OpenAISpeechProvider:
    name = "openai"

    def __init__(self, s: Settings) -> None:
        self.name = s.speech_kind
        key = s.speech_api_key or s.ai_api_key
        if not key:
            raise ConfigurationError("SPEECH_API_KEY is not set on the server")
        self.s, self.key = s, key

    async def _post(self, path: str, **kw: object) -> httpx.Response:
        url = self.s.speech_base + path
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
                         language: str | None, prompt: str | None = None) -> str:
        data = {"model": self.s.stt_model_name, "temperature": "0"}
        if language:
            data["language"] = language.split("-")[0]
        # Spelling hints (names, "EDITH", ...); Whisper allows ~224 tokens.
        data["prompt"] = ("EDITH. " + (prompt or "")).strip()[:600]
        r = await self._post("/audio/transcriptions", data=data,
                             files={"file": (filename, audio, content_type)})
        try:
            return str(r.json()["text"]).strip()
        except (ValueError, KeyError) as exc:
            raise ProviderError("Speech provider returned an unexpected response") from exc

    async def speak(self, text: str, voice: str | None, style: str | None = None) -> tuple[bytes, str]:
        if self.s.speech_kind == "groq":
            return await self._speak_groq(text, voice, style)
        if self.s.speech_kind != "openai":
            raise ConfigurationError(f"Server text-to-speech is not available with {self.s.speech_kind}; "
                                     "the app speaks answers with the device voice.",
                                     code="speech_not_configured")
        r = await self._post("/audio/speech", json={
            "model": self.s.tts_model_name, "voice": voice or self.s.tts_voice_name,
            "input": text[:4000], "response_format": "mp3",
        })
        return r.content, "audio/mpeg"

    async def _speak_groq(self, text: str, voice: str | None, style: str | None) -> tuple[bytes, str]:
        """Groq Orpheus: max 200 characters per request, WAV only. Long text is split into
        sentences, generated in parallel and joined, so it sounds like one answer."""
        voice = (voice or "").lower() if (voice or "").lower() in GROQ_VOICES else self.s.tts_voice_name
        tag = f"[{style.strip().lower()}] " if style and style.strip() else ""
        limit = self.s.tts_max_chars - len(tag) - 2
        pieces = split_for_tts(text, limit)[:12]
        if not pieces:
            raise ValidationFailed("Nothing to say")
        pieces[0] = tag + pieces[0]

        async def one(piece: str) -> bytes:
            r = await self._post("/audio/speech", json={
                "model": self.s.tts_model_name, "voice": voice, "input": piece, "response_format": "wav"})
            return r.content

        parts = await asyncio.gather(*(one(p) for p in pieces))
        return join_wavs(list(parts)), "audio/wav"


class SpeechService:
    def __init__(self, settings: Settings, provider: SpeechProvider | None = None) -> None:
        self.settings = settings
        self._provider = provider

    @property
    def provider(self) -> SpeechProvider:
        if self._provider is None:
            if self.settings.speech_kind == "none":
                raise ConfigurationError(
                    "Server-side speech is not configured. The app uses your browser's built-in "
                    "speech recognition and synthesis instead.", code="speech_not_configured")
            self._provider = OpenAISpeechProvider(self.settings)
        return self._provider

    async def transcribe(self, audio: bytes, filename: str, content_type: str,
                         language: str | None = None, prompt: str | None = None) -> str:
        base_type = (content_type or "").split(";")[0].strip().lower()
        if base_type not in ALLOWED_AUDIO_TYPES:
            raise ValidationFailed(f"Unsupported audio type '{base_type or 'unknown'}'")
        if not audio:
            raise ValidationFailed("Audio file is empty")
        if len(audio) > self.settings.max_audio_bytes:
            raise ValidationFailed("Audio file is too large", status_code=413)
        return await self.provider.transcribe(audio, filename, base_type, language, prompt)

    async def speak(self, text: str, voice: str | None = None, style: str | None = None) -> tuple[bytes, str]:
        return await self.provider.speak(text, voice, style)
