"""Small thread-safe TTL cache with explicit invalidation."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable


class TTLCache:
    def __init__(self, ttl_s: float, max_items: int = 1000) -> None:
        self.ttl, self.max = ttl_s, max_items
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires, value = item
            if time.monotonic() > expires:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max:
                self._data.popitem(last=False)

    def get_or_set(self, key: Hashable, factory: Callable[[], Any]) -> Any:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.set(key, value)
        return value

    def invalidate(self, predicate: Callable[[Hashable], bool] | None = None) -> None:
        with self._lock:
            if predicate is None:
                self._data.clear()
            else:
                for k in [k for k in self._data if predicate(k)]:
                    del self._data[k]
