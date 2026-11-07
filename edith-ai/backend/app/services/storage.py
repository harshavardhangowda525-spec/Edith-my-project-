"""Persistence layer.

``InMemoryStore`` is used for local development and tests. ``SupabaseStore``
talks to Supabase PostgREST with the service-role key, which **only ever lives
on the server**. Because the service role bypasses row-level security, every
query here filters by ``user_id`` explicitly; RLS policies in
``database/schema.sql`` remain the second line of defence for any direct client
access through the anon key.
"""
from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit

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
    # leads
    def save_lead(self, user_id: str, lead: dict[str, Any]) -> dict[str, Any]: ...
    def list_leads(self, user_id: str) -> list[dict[str, Any]]: ...
    def delete_lead(self, user_id: str, lead_id: str) -> bool: ...
    # background tasks
    def save_task(self, user_id: str, task: dict[str, Any]) -> None: ...
    def get_task(self, user_id: str, task_id: str) -> dict[str, Any] | None: ...
    def list_tasks(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]: ...
    def unfinished_tasks(self) -> list[dict[str, Any]]: ...


TASK_FIELDS = ("id", "user_id", "type", "title", "params", "priority", "status", "progress", "message", "result",
               "error", "attempts", "max_attempts", "timeout_s", "created_at", "updated_at", "finished_at")
LEAD_FIELDS = ("place_id", "name", "phone", "phone_international", "address", "rating", "reviews",
               "maps_url", "social_url", "query", "status", "notes")


def _clean_lead(lead: dict[str, Any]) -> dict[str, Any]:
    out = {k: lead.get(k) for k in LEAD_FIELDS}
    out["status"] = out.get("status") or "new"
    return out


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memories: dict[str, MemoryRecord] = {}
        self._memory_enabled: dict[str, bool] = {}
        self._documents: dict[str, DocumentRecord] = {}
        self._chunks: list[ChunkRecord] = []
        self._leads: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, dict[str, Any]] = {}

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

    def save_lead(self, user_id: str, lead: dict[str, Any]) -> dict[str, Any]:
        data = _clean_lead(lead)
        with self._lock:
            for existing in self._leads.values():  # one row per business per user
                if existing["user_id"] == user_id and existing["place_id"] == data["place_id"]:
                    existing.update({k: v for k, v in data.items() if v is not None})
                    return dict(existing)
            rec = {"id": str(uuid.uuid4()), "user_id": user_id, **data, "created_at": _now()}
            self._leads[rec["id"]] = rec
            return dict(rec)

    def list_leads(self, user_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self._leads.values() if r["user_id"] == user_id]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    def delete_lead(self, user_id: str, lead_id: str) -> bool:
        with self._lock:
            r = self._leads.get(lead_id)
            if not r or r["user_id"] != user_id:
                return False
            del self._leads[lead_id]
            return True

    def save_task(self, user_id: str, task: dict[str, Any]) -> None:
        with self._lock:
            self._tasks[task["id"]] = {k: task.get(k) for k in TASK_FIELDS}

    def get_task(self, user_id: str, task_id: str) -> dict[str, Any] | None:
        t = self._tasks.get(task_id)
        return dict(t) if t and t["user_id"] == user_id else None

    def list_tasks(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = [dict(t) for t in self._tasks.values() if t["user_id"] == user_id]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]

    def unfinished_tasks(self) -> list[dict[str, Any]]:
        return []  # in-memory tasks don't survive a restart anyway

    def list_chunks(self, user_id: str, document_ids: list[str] | None = None) -> list[ChunkRecord]:
        wanted = set(document_ids or [])
        return [
            c for c in self._chunks
            if c.user_id == user_id and (not wanted or c.document_id in wanted)
        ]


def normalize_supabase_url(url: str) -> str:
    """Turn common pastes into https://<ref>.supabase.co.

    Handles dashboard links (supabase.com/dashboard/project/<ref>/...), a missing
    https://, and copies that include /rest/v1 or other paths.
    """
    url = url.strip().strip("\"'")
    m = re.search(r"supabase\.com/dashboard/project/([a-z0-9]+)", url)
    if m:
        return f"https://{m.group(1)}.supabase.co"
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.hostname and parts.hostname.endswith(".supabase.co"):
        return f"https://{parts.hostname}"
    return url.rstrip("/").removesuffix("/rest/v1")  # self-hosted Supabase: keep host/path


def _database_error(r: httpx.Response) -> ProviderError:
    """Explain a PostgREST error without exposing keys or row data."""
    try:
        body = r.json()
    except ValueError:
        body = None
    code = body.get("code", "") if isinstance(body, dict) else ""
    detail = (body.get("message", "") if isinstance(body, dict) else "")[:200]
    if code in ("PGRST205", "42P01", "PGRST106") or "schema cache" in detail or "does not exist" in detail:
        msg = ("Supabase database tables are missing. In Supabase open SQL Editor, paste all of "
               "edith-ai/database/schema.sql and click Run.")
    elif r.status_code == 404:
        msg = ("Supabase address not found. SUPABASE_URL must look like https://<project-ref>.supabase.co "
               "(Supabase -> Project Settings -> Data API -> Project URL).")
    elif r.status_code in (401, 403):
        msg = ("Supabase rejected the key. Set SUPABASE_SERVICE_ROLE_KEY to the service_role (or "
               "sb_secret_...) key of the same project as SUPABASE_URL.")
    elif code == "23503":
        msg = ("OWNER_USER_ID is not a user in this Supabase project. Copy the User UID from "
               "Authentication -> Users of the same project as SUPABASE_URL.")
    else:
        msg = f"Database error ({r.status_code})"
    if detail:
        msg += f" [Supabase says: {detail}]"
    return ProviderError(msg, code="database_error")


class SupabaseStore:
    """Supabase PostgREST adapter (server-side, service-role key)."""

    remote = True  # network-backed: the task engine writes to it off the event loop

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
        self.base_url = normalize_supabase_url(url)
        self._client = httpx.Client(base_url=self.base_url + "/rest/v1", headers=headers,
                                    timeout=timeout)

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach Supabase. Check SUPABASE_URL "
                                "(https://<project-ref>.supabase.co).", code="database_error") from exc
        if r.status_code >= 400:
            raise _database_error(r)
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

    # --- leads (Supabase) ---
    def save_lead(self, user_id: str, lead: dict[str, Any]) -> dict[str, Any]:
        rows = self._req("POST", "/leads",
                         headers={"Prefer": "resolution=merge-duplicates,return=representation"},
                         params={"on_conflict": "user_id,place_id"},
                         json={"user_id": user_id, **_clean_lead(lead)})
        return rows[0]

    def list_leads(self, user_id: str) -> list[dict[str, Any]]:
        return self._req("GET", "/leads", params={"user_id": f"eq.{user_id}", "order": "created_at.desc",
                                                  "limit": "1000"})

    def delete_lead(self, user_id: str, lead_id: str) -> bool:
        rows = self._req("DELETE", "/leads", headers={"Prefer": "return=representation"},
                         params={"id": f"eq.{lead_id}", "user_id": f"eq.{user_id}"})
        return bool(rows)

    # --- background tasks (Supabase) ---
    def save_task(self, user_id: str, task: dict[str, Any]) -> None:
        self._req("POST", "/tasks", headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                  params={"on_conflict": "id"}, json={k: task.get(k) for k in TASK_FIELDS})

    def get_task(self, user_id: str, task_id: str) -> dict[str, Any] | None:
        rows = self._req("GET", "/tasks", params={"id": f"eq.{task_id}", "user_id": f"eq.{user_id}"})
        return rows[0] if rows else None

    def list_tasks(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._req("GET", "/tasks", params={"user_id": f"eq.{user_id}", "order": "created_at.desc",
                                                  "limit": str(limit)})

    def unfinished_tasks(self) -> list[dict[str, Any]]:
        return self._req("GET", "/tasks", params={"status": "in.(queued,running,paused)", "limit": "200"})
