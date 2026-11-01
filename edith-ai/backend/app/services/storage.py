"""Persistence layer.

``InMemoryStore`` is used for local development and tests. ``SupabaseStore``
talks to Supabase PostgREST with the service-role key, which **only ever lives
on the server**. Because the service role bypasses row-level security, every
query here filters by ``user_id`` explicitly; RLS policies in
``database/schema.sql`` remain the second line of defence for any direct client
access through the anon key.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from app.errors import ConfigurationError, ProviderError


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChunkRecord:
    document_id: str
    user_id: str
    chunk_index: int
    content: str
    title: str = ""


@dataclass
class DocumentRecord:
    id: str
    user_id: str
    title: str
    chunk_count: int
    created_at: datetime


@dataclass
class MemoryRecord:
    id: str
    user_id: str
    content: str
    category: str
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


class Store(Protocol):
    # memories
    def list_memories(self, user_id: str) -> list[MemoryRecord]: ...
    def get_memory(self, user_id: str, memory_id: str) -> MemoryRecord | None: ...
    def create_memory(self, user_id: str, content: str, category: str) -> MemoryRecord: ...
    def update_memory(self, user_id: str, memory_id: str, changes: dict[str, Any]) -> MemoryRecord | None: ...
    def delete_memory(self, user_id: str, memory_id: str) -> bool: ...
    # profile settings
    def get_memory_enabled(self, user_id: str) -> bool: ...
    def set_memory_enabled(self, user_id: str, enabled: bool) -> None: ...
    # documents
    def create_document(self, user_id: str, title: str, chunks: list[str]) -> DocumentRecord: ...
    def list_documents(self, user_id: str) -> list[DocumentRecord]: ...
    def delete_document(self, user_id: str, document_id: str) -> bool: ...
    def list_chunks(self, user_id: str, document_ids: list[str] | None = None) -> list[ChunkRecord]: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memories: dict[str, MemoryRecord] = {}
        self._memory_enabled: dict[str, bool] = {}
        self._documents: dict[str, DocumentRecord] = {}
        self._chunks: list[ChunkRecord] = []

    # --- memories ---
    def list_memories(self, user_id: str) -> list[MemoryRecord]:
        with self._lock:
            items = [m for m in self._memories.values() if m.user_id == user_id]
        return sorted(items, key=lambda m: m.created_at, reverse=True)

    def get_memory(self, user_id: str, memory_id: str) -> MemoryRecord | None:
        m = self._memories.get(memory_id)
        return m if m and m.user_id == user_id else None

    def create_memory(self, user_id: str, content: str, category: str) -> MemoryRecord:
        rec = MemoryRecord(id=str(uuid.uuid4()), user_id=user_id, content=content, category=category)
        with self._lock:
            self._memories[rec.id] = rec
        return rec

    def update_memory(self, user_id: str, memory_id: str, changes: dict[str, Any]) -> MemoryRecord | None:
        with self._lock:
            m = self._memories.get(memory_id)
            if not m or m.user_id != user_id:
                return None
            for k, v in changes.items():
                setattr(m, k, v)
            m.updated_at = _now()
            return m

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        with self._lock:
            m = self._memories.get(memory_id)
            if not m or m.user_id != user_id:
                return False
            del self._memories[memory_id]
            return True

    # --- settings ---
    def get_memory_enabled(self, user_id: str) -> bool:
        return self._memory_enabled.get(user_id, True)

    def set_memory_enabled(self, user_id: str, enabled: bool) -> None:
        self._memory_enabled[user_id] = enabled

    # --- documents ---
    def create_document(self, user_id: str, title: str, chunks: list[str]) -> DocumentRecord:
        doc = DocumentRecord(id=str(uuid.uuid4()), user_id=user_id, title=title,
                             chunk_count=len(chunks), created_at=_now())
        with self._lock:
            self._documents[doc.id] = doc
            self._chunks.extend(
                ChunkRecord(document_id=doc.id, user_id=user_id, chunk_index=i, content=c, title=title)
                for i, c in enumerate(chunks)
            )
        return doc

    def list_documents(self, user_id: str) -> list[DocumentRecord]:
        docs = [d for d in self._documents.values() if d.user_id == user_id]
        return sorted(docs, key=lambda d: d.created_at, reverse=True)

    def delete_document(self, user_id: str, document_id: str) -> bool:
        with self._lock:
            d = self._documents.get(document_id)
            if not d or d.user_id != user_id:
                return False
            del self._documents[document_id]
            self._chunks = [c for c in self._chunks if c.document_id != document_id]
            return True

    def list_chunks(self, user_id: str, document_ids: list[str] | None = None) -> list[ChunkRecord]:
        wanted = set(document_ids or [])
        return [
            c for c in self._chunks
            if c.user_id == user_id and (not wanted or c.document_id in wanted)
        ]


class SupabaseStore:
    """Supabase PostgREST adapter (server-side, service-role key)."""

    def __init__(self, url: str | None, service_key: str | None, timeout: float = 10.0) -> None:
        if not url or not service_key:
            raise ConfigurationError(
                "STORAGE_BACKEND=supabase requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
            )
        headers = {"apikey": service_key, "Content-Type": "application/json"}
        # Legacy service_role keys are JWTs and also go in Authorization. Newer
        # "sb_secret_..." keys are not JWTs and are sent in the apikey header only.
        if service_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {service_key}"
        self._client = httpx.Client(base_url=url.rstrip("/") + "/rest/v1", headers=headers,
                                    timeout=timeout)

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise ProviderError("Database request failed", code="database_error") from exc
        if r.status_code >= 400:
            raise ProviderError(f"Database error ({r.status_code})", code="database_error")
        return r.json() if r.content else None

    @staticmethod
    def _mem(row: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"], user_id=row["user_id"], content=row["content"], category=row["category"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_memories(self, user_id: str) -> list[MemoryRecord]:
        rows = self._req("GET", "/memories", params={"user_id": f"eq.{user_id}", "order": "created_at.desc"})
        return [self._mem(r) for r in rows]

    def get_memory(self, user_id: str, memory_id: str) -> MemoryRecord | None:
        rows = self._req("GET", "/memories", params={"id": f"eq.{memory_id}", "user_id": f"eq.{user_id}"})
        return self._mem(rows[0]) if rows else None

    def create_memory(self, user_id: str, content: str, category: str) -> MemoryRecord:
        rows = self._req("POST", "/memories", headers={"Prefer": "return=representation"},
                         json={"user_id": user_id, "content": content, "category": category})
        return self._mem(rows[0])

    def update_memory(self, user_id: str, memory_id: str, changes: dict[str, Any]) -> MemoryRecord | None:
        rows = self._req("PATCH", "/memories", headers={"Prefer": "return=representation"},
                         params={"id": f"eq.{memory_id}", "user_id": f"eq.{user_id}"},
                         json={**changes, "updated_at": _now().isoformat()})
        return self._mem(rows[0]) if rows else None

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        rows = self._req("DELETE", "/memories", headers={"Prefer": "return=representation"},
                         params={"id": f"eq.{memory_id}", "user_id": f"eq.{user_id}"})
        return bool(rows)

    def get_memory_enabled(self, user_id: str) -> bool:
        rows = self._req("GET", "/profiles", params={"id": f"eq.{user_id}", "select": "memory_enabled"})
        return bool(rows[0]["memory_enabled"]) if rows else True

    def set_memory_enabled(self, user_id: str, enabled: bool) -> None:
        self._req("POST", "/profiles",
                  headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                  json={"id": user_id, "memory_enabled": enabled})

    def create_document(self, user_id: str, title: str, chunks: list[str]) -> DocumentRecord:
        rows = self._req("POST", "/knowledge_documents", headers={"Prefer": "return=representation"},
                         json={"user_id": user_id, "title": title, "chunk_count": len(chunks)})
        doc = rows[0]
        if chunks:
            self._req("POST", "/document_chunks", headers={"Prefer": "return=minimal"}, json=[
                {"document_id": doc["id"], "user_id": user_id, "chunk_index": i, "content": c}
                for i, c in enumerate(chunks)
            ])
        return DocumentRecord(id=doc["id"], user_id=user_id, title=title, chunk_count=len(chunks),
                              created_at=datetime.fromisoformat(doc["created_at"]))

    def list_documents(self, user_id: str) -> list[DocumentRecord]:
        rows = self._req("GET", "/knowledge_documents",
                         params={"user_id": f"eq.{user_id}", "order": "created_at.desc"})
        return [DocumentRecord(id=r["id"], user_id=r["user_id"], title=r["title"],
                               chunk_count=r["chunk_count"],
                               created_at=datetime.fromisoformat(r["created_at"])) for r in rows]

    def delete_document(self, user_id: str, document_id: str) -> bool:
        rows = self._req("DELETE", "/knowledge_documents", headers={"Prefer": "return=representation"},
                         params={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"})
        return bool(rows)

    def list_chunks(self, user_id: str, document_ids: list[str] | None = None) -> list[ChunkRecord]:
        params = {"user_id": f"eq.{user_id}",
                  "select": "document_id,user_id,chunk_index,content,knowledge_documents(title)",
                  "limit": "2000"}
        if document_ids:
            params["document_id"] = f"in.({','.join(document_ids)})"
        rows = self._req("GET", "/document_chunks", params=params)
        return [ChunkRecord(document_id=r["document_id"], user_id=r["user_id"],
                            chunk_index=r["chunk_index"], content=r["content"],
                            title=(r.get("knowledge_documents") or {}).get("title", "")) for r in rows]
