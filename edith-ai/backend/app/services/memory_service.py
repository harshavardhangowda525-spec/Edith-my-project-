"""User-approved long-term memory.

Memories are only ever written through an explicit user action (POST /api/memory).
Chat never stores conversation content automatically.
"""
from __future__ import annotations

from app.errors import AppError, NotFoundError
from app.models.schemas import Memory, MemoryCreate, MemoryUpdate
from app.services.storage import MemoryRecord, Store

MAX_MEMORIES_IN_PROMPT = 15


class MemoryDisabled(AppError):
    status_code = 409
    code = "memory_disabled"


def _to_schema(m: MemoryRecord) -> Memory:
    return Memory(id=m.id, user_id=m.user_id, content=m.content, category=m.category,
                  created_at=m.created_at, updated_at=m.updated_at)


class MemoryService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def is_enabled(self, user_id: str) -> bool:
        return self.store.get_memory_enabled(user_id)

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        self.store.set_memory_enabled(user_id, enabled)

    def list(self, user_id: str) -> list[Memory]:
        return [_to_schema(m) for m in self.store.list_memories(user_id)]

    def create(self, user_id: str, data: MemoryCreate) -> Memory:
        if not self.is_enabled(user_id):
            raise MemoryDisabled("Persistent memory is turned off. Enable it in Privacy settings first.")
        return _to_schema(self.store.create_memory(user_id, data.content, data.category))

    def update(self, user_id: str, memory_id: str, data: MemoryUpdate) -> Memory:
        changes = data.model_dump(exclude_none=True)
        if not changes:
            existing = self.store.get_memory(user_id, memory_id)
            if not existing:
                raise NotFoundError("Memory not found")
            return _to_schema(existing)
        updated = self.store.update_memory(user_id, memory_id, changes)
        if not updated:
            # Same response for "missing" and "owned by someone else" - no existence leak.
            raise NotFoundError("Memory not found")
        return _to_schema(updated)

    def delete(self, user_id: str, memory_id: str) -> None:
        if not self.store.delete_memory(user_id, memory_id):
            raise NotFoundError("Memory not found")

    def for_prompt(self, user_id: str) -> list[str]:
        if not self.is_enabled(user_id):
            return []
        return [m.content for m in self.store.list_memories(user_id)[:MAX_MEMORIES_IN_PROMPT]]
