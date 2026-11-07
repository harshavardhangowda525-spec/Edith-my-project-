"""User-approved long-term memory.

Memories are only ever written through an explicit user action (POST /api/memory).
Chat never stores conversation content automatically.
"""
from __future__ import annotations

from app.errors import AppError, NotFoundError
from app.models.schemas import Memory, MemoryCreate, MemoryUpdate
from app.services.cache import TTLCache
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
        # Prompt memories are read on every question; cache briefly, invalidate on every change.
        self._cache = TTLCache(ttl_s=60, max_items=1000)

    def _invalidate(self, user_id: str) -> None:
        self._cache.invalidate(lambda k: k[1] == user_id)

    def is_enabled(self, user_id: str) -> bool:
        return self._cache.get_or_set(("enabled", user_id), lambda: self.store.get_memory_enabled(user_id))

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        self.store.set_memory_enabled(user_id, enabled)
        self._invalidate(user_id)

    def list(self, user_id: str) -> list[Memory]:
        return [_to_schema(m) for m in self.store.list_memories(user_id)]

    def create(self, user_id: str, data: MemoryCreate) -> Memory:
        if not self.is_enabled(user_id):
            raise MemoryDisabled("Persistent memory is turned off. Enable it in Privacy settings first.")
        m = _to_schema(self.store.create_memory(user_id, data.content, data.category))
        self._invalidate(user_id)
        return m

    def update(self, user_id: str, memory_id: str, data: MemoryUpdate) -> Memory:
        changes = data.model_dump(exclude_none=True)
        if not changes:
            existing = self.store.get_memory(user_id, memory_id)
            if not existing:
                raise NotFoundError("Memory not found")
            return _to_schema(existing)
        updated = self.store.update_memory(user_id, memory_id, changes)
        self._invalidate(user_id)
        if not updated:
            # Same response for "missing" and "owned by someone else" - no existence leak.
            raise NotFoundError("Memory not found")
        return _to_schema(updated)

    def delete(self, user_id: str, memory_id: str) -> None:
        if not self.store.delete_memory(user_id, memory_id):
            raise NotFoundError("Memory not found")
        self._invalidate(user_id)

    def for_prompt(self, user_id: str) -> list[str]:
        if not self.is_enabled(user_id):
            return []
        return list(self._cache.get_or_set(("prompt", user_id), lambda: tuple(self._build_prompt(user_id))))

    def _build_prompt(self, user_id: str) -> list[str]:
        items = self.store.list_memories(user_id)
        # "About me" (category profile) always comes first and is never pushed out by newer memories.
        profile = [f"About the user: {m.content}" for m in items if m.category == "profile"]
        others = [m.content for m in items if m.category != "profile"]
        return profile[:10] + others[: max(0, MAX_MEMORIES_IN_PROMPT - min(len(profile), 10))]
