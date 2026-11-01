"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["user", "assistant"]


class ChatTurn(BaseModel):
    role: Role
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Short-term context: the client sends the recent turns it holds.
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    mode: Literal["earbud", "detailed", "meeting"] = "earbud"
    model: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=20, description="BCP-47 tag, e.g. en-US")
    use_memory: bool = True
    use_documents: bool = True

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v


class Source(BaseModel):
    document_id: str
    title: str
    chunk_index: int
    excerpt: str
    score: float


class ChatResponse(BaseModel):
    reply: str
    model: str
    provider: str
    mock: bool
    sources: list[Source] = Field(default_factory=list)
    memories_used: int = 0


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    category: str = Field(default="general", max_length=50)

    @field_validator("content")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("content must not be blank")
        return v


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    category: str | None = Field(default=None, max_length=50)


class Memory(BaseModel):
    id: str
    user_id: str
    content: str
    category: str
    created_at: datetime
    updated_at: datetime


class MemorySettings(BaseModel):
    memory_enabled: bool


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)


class Document(BaseModel):
    id: str
    user_id: str
    title: str
    chunk_count: int
    created_at: datetime


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = Field(default=None, max_length=50)


class TranscriptionResponse(BaseModel):
    text: str
    provider: str


class MeetingBriefingRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    document_ids: list[str] = Field(default_factory=list, max_length=20)


class MeetingSummaryRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=50_000)
    # The user must confirm that all participants consented to any recording.
    consent_confirmed: bool


class MeetingResponse(BaseModel):
    content: str
    sources: list[Source] = Field(default_factory=list)
    model: str
    mock: bool


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    ai_provider: str
    ai_configured: bool
    mock_mode: bool
    speech_provider: str
    storage_backend: str
    auth_mode: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
