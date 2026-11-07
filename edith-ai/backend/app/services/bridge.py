"""EDITH PC bridge hub.

The bridge (``tools/edith_bridge.py``) runs on the user's computer and polls this server for jobs.
The server never runs commands on the PC itself: it can only hand over one of a fixed list of job
kinds, and the bridge decides locally (and asks the user on the PC when needed) whether to run it.
Nothing is reported as done until the bridge sends back a real result.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.errors import AppError

# Job kinds the server may request. The bridge maps each to a local, non-destructive command.
JOB_KINDS = {
    "run_tests": "Run the project's test command",
    "git_status": "Show git status",
    "git_diff": "Show the uncommitted diff (summary)",
    "git_log": "Show recent commits",
    "tail_log": "Show the end of a log file",
    "list_projects": "List the projects the bridge knows",
    "index_project": "Index a project's source files into EDITH's knowledge base",
}
ONLINE_WINDOW_S = 90


class BridgeOffline(AppError):
    status_code = 409
    code = "bridge_offline"


@dataclass
class Job:
    id: str
    kind: str
    params: dict[str, Any]
    created: float = field(default_factory=time.time)
    claimed: bool = False


class BridgeHub:
    def __init__(self) -> None:
        self._pending: dict[str, list[Job]] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._wake: dict[str, asyncio.Event] = {}
        self._seen: dict[str, dict[str, Any]] = {}

    # --- bridge side -----------------------------------------------------------
    def heartbeat(self, user_id: str, info: dict[str, Any]) -> None:
        self._seen[user_id] = {**info, "last_seen": time.time()}

    def status(self, user_id: str) -> dict[str, Any]:
        info = self._seen.get(user_id)
        online = bool(info and time.time() - info["last_seen"] < ONLINE_WINDOW_S)
        return {"online": online, **({k: v for k, v in info.items()} if info else {}),
                "pending": len(self._pending.get(user_id, []))}

    async def claim(self, user_id: str, wait_s: float = 20.0) -> Job | None:
        """Long-poll: return the next job, waiting up to wait_s for one to arrive."""
        self.heartbeat(user_id, self._seen.get(user_id, {}))
        deadline = time.monotonic() + wait_s
        while True:
            queue = self._pending.get(user_id) or []
            if queue:
                job = queue.pop(0)
                job.claimed = True
                return job
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ev = self._wake.setdefault(user_id, asyncio.Event())
            ev.clear()
            try:
                await asyncio.wait_for(ev.wait(), timeout=left)
            except asyncio.TimeoutError:
                return None

    def complete(self, user_id: str, job_id: str, ok: bool, output: str) -> bool:
        fut = self._futures.get(f"{user_id}:{job_id}")
        if not fut or fut.done():
            return False
        fut.set_result((ok, output))
        return True

    # --- server side -----------------------------------------------------------
    async def run(self, user_id: str, kind: str, params: dict[str, Any], timeout_s: float) -> tuple[bool, str]:
        if kind not in JOB_KINDS:
            raise AppError(f"Unknown PC job '{kind}'", code="invalid_request", status_code=422)
        if not self.status(user_id)["online"]:
            raise BridgeOffline("Your PC bridge isn't connected. On your computer run: "
                                "python edith_bridge.py serve")
        job = Job(id=str(uuid.uuid4()), kind=kind, params=params)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        key = f"{user_id}:{job.id}"
        self._futures[key] = fut
        self._pending.setdefault(user_id, []).append(job)
        self._wake.setdefault(user_id, asyncio.Event()).set()
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        finally:
            self._futures.pop(key, None)
            q = self._pending.get(user_id) or []
            if job in q:
                q.remove(job)
