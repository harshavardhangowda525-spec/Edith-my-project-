"""Background task engine: concurrent, prioritised, cancellable, pausable, retried, timed out,
with persistent history. EDITH acknowledges a request at once and keeps talking while it runs.

A task is only marked "completed" after its handler actually returned a result.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.errors import AppError, NotFoundError, ProviderError, ProviderTimeout, ValidationFailed

log = logging.getLogger("edith.tasks")

ACTIVE = ("queued", "running", "paused")
FINAL = ("completed", "failed", "cancelled")


class TaskCancelled(Exception):
    pass


@dataclass
class Task:
    id: str
    user_id: str
    type: str
    title: str
    params: dict[str, Any]
    priority: int = 5                 # 1 = most urgent, 9 = least
    status: str = "queued"
    progress: int = 0
    message: str = "Queued"
    result: str | None = None
    error: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    timeout_s: float = 600.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k not in ("user_id",)}


class TaskContext:
    """Given to handlers: report progress, honour cancel/pause."""

    def __init__(self, engine: "TaskEngine", task: Task) -> None:
        self.engine, self.task = engine, task

    @property
    def user_id(self) -> str:
        return self.task.user_id

    async def progress(self, pct: int, message: str) -> None:
        await self.checkpoint()
        self.task.progress = max(0, min(99, int(pct)))
        self.task.message = message[:300]
        self.engine._save(self.task)

    async def checkpoint(self) -> None:
        """Raises if cancelled; waits while paused."""
        while True:
            if self.engine._cancel.get(self.task.id):
                raise TaskCancelled()
            if self.task.status != "paused":
                return
            await asyncio.sleep(0.3)


Handler = Callable[[TaskContext], Awaitable[str]]


class TaskEngine:
    def __init__(self, store: Any, workers: int = 3) -> None:
        self.store = store
        self.workers = workers
        self.handlers: dict[str, Handler] = {}
        self.timeouts: dict[str, float] = {}
        self._queue: asyncio.PriorityQueue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancel: dict[str, bool] = {}
        self._tasks: dict[str, Task] = {}
        self._seq = itertools.count()
        self._worker_tasks: list[asyncio.Task] = []
        self.listeners: list[Callable[[Task], None]] = []
        # Remote stores (Supabase) are written on one background thread: in order, never blocking answers.
        self._writer = ThreadPoolExecutor(max_workers=1) if getattr(store, "remote", False) else None

    def register(self, type_: str, handler: Handler, timeout_s: float = 600.0) -> None:
        self.handlers[type_] = handler
        self.timeouts[type_] = timeout_s

    # ------------------------------------------------------------------ lifecycle
    def _ensure_workers(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is loop and self._queue is not None:
            return
        self._loop = loop
        self._queue = asyncio.PriorityQueue()
        self._worker_tasks = [loop.create_task(self._worker(i)) for i in range(self.workers)]
        # Crash recovery: re-queue unfinished tasks from storage (e.g. after a restart).
        for t in self._load_unfinished():
            t.status, t.message = "queued", "Resumed after restart"
            self._tasks[t.id] = t
            self._queue.put_nowait((t.priority, next(self._seq), t.id))

    def start(self) -> None:
        """Start the workers now (call from inside the running event loop)."""
        self._ensure_workers()

    async def shutdown(self) -> None:
        for w in self._worker_tasks:
            w.cancel()
        self._worker_tasks = []
        self._queue = None

    # ------------------------------------------------------------------ API
    async def submit(self, user_id: str, type_: str, params: dict[str, Any], title: str | None = None,
                     priority: int = 5) -> Task:
        if type_ not in self.handlers:
            raise ValidationFailed(f"Unknown task type '{type_}'. Available: {', '.join(sorted(self.handlers))}")
        self._ensure_workers()
        task = Task(id=str(uuid.uuid4()), user_id=user_id, type=type_, title=(title or type_)[:200],
                    params=params, priority=max(1, min(9, priority)), timeout_s=self.timeouts.get(type_, 600.0))
        self._tasks[task.id] = task
        self._save(task)
        assert self._queue is not None
        await self._queue.put((task.priority, next(self._seq), task.id))
        return task

    def get(self, user_id: str, task_id: str) -> Task:
        t = self._tasks.get(task_id) or self._from_store(user_id, task_id)
        if not t or t.user_id != user_id:
            raise NotFoundError("Task not found")
        return t

    def list(self, user_id: str, limit: int = 50) -> list[Task]:
        mine = {t.id: t for t in self._tasks.values() if t.user_id == user_id}
        for row in self._store_list(user_id):
            mine.setdefault(row.id, row)
        return sorted(mine.values(), key=lambda t: t.created_at, reverse=True)[:limit]

    def cancel(self, user_id: str, task_id: str) -> Task:
        t = self.get(user_id, task_id)
        if t.status in FINAL:
            return t
        self._cancel[t.id] = True
        if t.status in ("queued", "paused"):
            self._finish(t, "cancelled", message="Cancelled")
        return t

    def pause(self, user_id: str, task_id: str) -> Task:
        t = self.get(user_id, task_id)
        if t.status in ("queued", "running"):
            t.status, t.message = "paused", "Paused"
            self._save(t)
        return t

    def resume(self, user_id: str, task_id: str) -> Task:
        t = self.get(user_id, task_id)
        if t.status == "paused":
            t.status = "running" if t.attempts else "queued"
            t.message = "Resumed"
            self._save(t)
        return t

    async def retry(self, user_id: str, task_id: str) -> Task:
        t = self.get(user_id, task_id)
        if t.status not in ("failed", "cancelled"):
            raise ValidationFailed("Only failed or cancelled tasks can be retried")
        return await self.submit(user_id, t.type, t.params, t.title, t.priority)

    # ------------------------------------------------------------------ worker
    async def _worker(self, n: int) -> None:
        assert self._queue is not None
        q = self._queue
        while True:
            _, _, task_id = await q.get()
            t = self._tasks.get(task_id)
            if not t or t.status in FINAL:
                continue
            while t.status == "paused" and not self._cancel.get(t.id):
                await asyncio.sleep(0.3)
            if self._cancel.get(t.id):
                self._finish(t, "cancelled", message="Cancelled")
                continue
            await self._run(t)

    async def _run(self, t: Task) -> None:
        ctx = TaskContext(self, t)
        handler = self.handlers[t.type]
        while True:
            t.attempts += 1
            t.status, t.message = "running", "Working…" if t.attempts == 1 else f"Retrying (attempt {t.attempts})"
            self._save(t)
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(handler(ctx), timeout=t.timeout_s)
                self._finish(t, "completed", result=result, message=f"Done in {time.perf_counter() - started:.1f}s")
                return
            except TaskCancelled:
                self._finish(t, "cancelled", message="Cancelled")
                return
            except asyncio.TimeoutError:
                self._finish(t, "failed", error=f"Timed out after {int(t.timeout_s)} s")
                return
            except (ProviderError, ProviderTimeout) as exc:
                if t.attempts >= t.max_attempts or getattr(exc, "code", "") == "provider_auth":
                    self._finish(t, "failed", error=exc.message)
                    return
                delay = min(30.0, 2.0 ** t.attempts)  # exponential backoff: 2 s, 4 s, ...
                t.message = f"Temporary problem ({exc.code}); retrying in {int(delay)} s"
                self._save(t)
                await asyncio.sleep(delay)
            except AppError as exc:
                self._finish(t, "failed", error=exc.message)
                return
            except Exception as exc:  # never crash the worker
                log.exception("task %s failed", t.id)
                self._finish(t, "failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
                return

    def _finish(self, t: Task, status: str, result: str | None = None, error: str | None = None,
                message: str | None = None) -> None:
        t.status = status
        if result is not None:
            t.result = result
        if error is not None:
            t.error = error
        t.progress = 100 if status == "completed" else t.progress
        t.message = message or ("Done" if status == "completed" else error or status)
        t.finished_at = datetime.now(timezone.utc).isoformat()
        self._cancel.pop(t.id, None)
        self._save(t)
        for fn in self.listeners:
            try:
                fn(t)
            except Exception:  # listeners must not break tasks
                log.exception("task listener failed")

    # ------------------------------------------------------------------ persistence
    def _save(self, t: Task) -> None:
        t.updated_at = datetime.now(timezone.utc).isoformat()
        row = t.__dict__.copy()
        if self._writer:
            self._writer.submit(self._write, t.user_id, row)
        else:
            self._write(t.user_id, row)

    def _write(self, user_id: str, row: dict[str, Any]) -> None:
        try:
            self.store.save_task(user_id, row)
        except Exception:
            log.warning("could not persist task %s", row.get("id"))

    def _from_store(self, user_id: str, task_id: str) -> Task | None:
        try:
            row = self.store.get_task(user_id, task_id)
        except Exception:
            return None
        return Task(**row) if row else None

    def _store_list(self, user_id: str) -> list[Task]:
        try:
            return [Task(**r) for r in self.store.list_tasks(user_id)]
        except Exception:
            return []

    def _load_unfinished(self) -> list[Task]:
        try:
            return [Task(**r) for r in self.store.unfinished_tasks()]
        except Exception:
            return []
