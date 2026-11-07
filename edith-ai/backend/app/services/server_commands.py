"""Spoken commands EDITH handles on the server (no phone action needed):

- project memory:  "remember that we use Riverpod in the Flutter app"
                   "remember for project shop: the API is on Render"
                   "what do you remember about project shop"
- background work: "in the background, research the best vector database for 1M documents"
                   "check GitHub" / "check github for owner/repo"
                   "run the tests on my PC" / "git status on my PC"
                   "what are my tasks" / "cancel the last task"

Destructive actions (deleting memories, running anything not on the bridge's fixed list) are
never done by voice; deleting and correcting memories happens in the Memory panel.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.errors import AppError
from app.models.schemas import MemoryCreate
from app.services.memory_service import MemoryService
from app.services.tasks import ACTIVE, TaskEngine

MEMORY_CATEGORIES = ("general", "profile", "project", "decision", "error_fix", "preference", "task", "command")

_CATEGORY_HINTS = [
    ("error_fix", re.compile(r"\b(error|bug|fix(ed)?|exception|crash|traceback|fails?|failing|broke)\b")),
    ("decision", re.compile(r"\b(decided|decision|we (?:chose|picked|use|will use|are using)|go with|chose)\b")),
    ("command", re.compile(r"\b(command|run |npm |pip |flutter |docker |git |python |yarn |pnpm )")),
    ("preference", re.compile(r"\b(i (?:prefer|like|love|hate|don'?t like|want)|always|never|prefer)\b")),
    ("task", re.compile(r"\b(todo|to do|need to|have to|must|deadline|by (?:monday|tuesday|wednesday|thursday|"
                        r"friday|tomorrow|next week))\b")),
]
_REMEMBER = re.compile(r"^(?:please\s+)?(?:remember|keep in mind|don'?t forget)(?:\s+(?:that|this))?"
                       r"(?:\s+for\s+(?:the\s+)?project\s+(?P<project>[\w .-]{1,40}?)\s*[:,-]?\s+(?:that\s+)?)?"
                       r"\s*[:,-]?\s*(?P<fact>.{3,})$", re.I)
_QUESTIONY = re.compile(r"^(?:when|what|how|who|where|why|the time|me|my name)\b", re.I)
_RECALL = re.compile(r"^what do you (?:remember|know)(?: about)?(?:\s+(?:the\s+)?project\s+(?P<project>[\w .-]{1,40}))?"
                     r"(?: about me)?\??$", re.I)
_BACKGROUND = re.compile(r"^(?:in the background[, ]+|start a (?:background )?task (?:to )?)"
                         r"(?:please\s+)?(?:research|look into|investigate|find out|think about)\s+(?P<q>.{5,})$"
                         r"|^(?:research|look into|investigate)\s+(?P<q2>.{5,}?)\s+in the background\.?$", re.I)
_GITHUB = re.compile(r"^(?:check|summari[sz]e|how is|what'?s (?:new|happening) (?:on|in))\s+(?:my\s+)?github"
                     r"(?:\s+(?:for|repo|repository)\s+(?P<repo>[\w.-]+/[\w.-]+))?\??$", re.I)
_PC = [
    ("run_tests", re.compile(r"^run (?:the |my )?tests?(?: on my (?:pc|computer|laptop))?(?: for (?P<p>[\w .-]+))?\.?$", re.I)),
    ("git_status", re.compile(r"^(?:git status|what changed)(?: on my (?:pc|computer|laptop))?(?: (?:in|for) (?P<p>[\w .-]+))?\??$", re.I)),
    ("git_log", re.compile(r"^(?:show )?(?:recent|latest|last) commits(?: (?:in|for) (?P<p>[\w .-]+))?\??$", re.I)),
    ("index_project", re.compile(r"^(?:index|scan|learn) (?:my |the )?(?:project|code|codebase)(?: (?P<p>[\w .-]+))?\.?$", re.I)),
]
_TASKS = re.compile(r"^(?:what are|list|show)(?: me)? my (?:background )?tasks\??$|^(?:task|tasks) status\??$", re.I)
_CANCEL = re.compile(r"^(?:cancel|stop) (?:the |my )?(?:last |latest |current )?(?:background )?task\.?$", re.I)


def _clean(text: str) -> str:
    return " ".join(text.strip().split()).strip(" .!")


def guess_category(fact: str, project: str | None) -> str:
    low = fact.lower()
    for name, pattern in _CATEGORY_HINTS:
        if pattern.search(low):
            return name
    return "project" if project else "general"


def parse(text: str) -> dict[str, Any] | None:
    t = _clean(text)
    if m := _RECALL.match(t):
        return {"kind": "recall", "project": (m.group("project") or "").strip() or None}
    if (m := _REMEMBER.match(t)) and not _QUESTIONY.match(m.group("fact")) and not text.strip().endswith("?"):
        project = (m.group("project") or "").strip() or None
        fact = m.group("fact").strip()
        return {"kind": "remember", "project": project, "fact": fact, "category": guess_category(fact, project)}
    if m := _BACKGROUND.match(t):
        return {"kind": "task", "type": "research", "params": {"question": (m.group("q") or m.group("q2")).strip()}}
    if m := _GITHUB.match(t):
        return {"kind": "task", "type": "github_summary", "params": {"repo": m.group("repo")}}
    for kind, pattern in _PC:
        if m := pattern.match(t):
            args = {"project": (m.group("p") or "").strip() or None}
            return {"kind": "task", "type": "pc", "params": {"kind": kind, "args": args}}
    if _TASKS.match(t):
        return {"kind": "list_tasks"}
    if _CANCEL.match(t):
        return {"kind": "cancel_task"}
    return None


TITLES = {"research": "Research: {question}", "github_summary": "GitHub summary",
          "pc": "PC: {kind}"}


async def run(cmd: dict[str, Any], user_id: str, memory: MemoryService, tasks: TaskEngine | None,
              address: str | None) -> tuple[str, dict[str, Any] | None]:
    """Execute a parsed server command. Returns (what to say, optional task to report)."""
    sir = f", {address}" if address else ""
    kind = cmd["kind"]
    if kind == "remember":
        content = f"[Project {cmd['project']}] {cmd['fact']}" if cmd["project"] else cmd["fact"]
        try:
            await run_in_threadpool(memory.create, user_id, MemoryCreate(content=content[:1000], category=cmd["category"]))
        except AppError as exc:
            return exc.message, None
        label = cmd["category"].replace("_", " ")
        return f"Noted{sir}. Saved as a {label} memory - you can correct it in the Memory panel.", None
    if kind == "recall":
        items = await run_in_threadpool(memory.list, user_id)
        if cmd["project"]:
            tag = f"[project {cmd['project'].lower()}]"
            items = [m for m in items if m.content.lower().startswith(tag)]
        if not items:
            return f"I don't have anything saved{' for that project' if cmd['project'] else ''} yet{sir}.", None
        return "Here's what I have: " + "; ".join(m.content for m in items[:8]) + ".", None
    if tasks is None:
        return "Background tasks aren't available on this server.", None
    if kind == "list_tasks":
        mine = tasks.list(user_id, 20)
        active = [t for t in mine if t.status in ACTIVE]
        if not mine:
            return f"No background tasks yet{sir}.", None
        if not active:
            last = mine[0]
            return f"Nothing running. The last one, {last.title}, {last.status}.", None
        return f"{len(active)} running: " + "; ".join(f"{t.title} - {t.message}" for t in active[:4]) + ".", None
    if kind == "cancel_task":
        active = [t for t in tasks.list(user_id, 20) if t.status in ACTIVE]
        if not active:
            return f"There's nothing running to cancel{sir}.", None
        t = tasks.cancel(user_id, active[0].id)
        return f"Cancelled {t.title}.", None
    # kind == "task"
    params = cmd["params"]
    title = TITLES.get(cmd["type"], cmd["type"]).format(**{k: str(v)[:80] for k, v in params.items()})
    task = await tasks.submit(user_id, cmd["type"], params, title=title, priority=4)
    return f"On it{sir}. I'll work on that in the background and let you know when it's done.", task.public()
