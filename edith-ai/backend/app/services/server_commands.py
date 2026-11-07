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
import time
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
_LAPTOP = r"(?:laptop|pc|computer|desktop)"
_LAPTOP_PREFIX = re.compile(rf"^(?:(?:please\s+)?(?:turn on|switch on|wake(?: up)?|start(?: up)?|power on)\s+(?:my\s+|the\s+)?"
                            rf"{_LAPTOP}(?:\s+up)?\s*,?\s*(?:and|then|and then)?\s+|on my {_LAPTOP}\s*,?\s+)", re.I)
_LAPTOP_SUFFIX = re.compile(rf"\s+on my {_LAPTOP}$", re.I)
_P = r"(?:the\s+|my\s+)?(?:project\s+)?(?P<p>[\w-]+)(?:\s+project)?"
_AGENT = [
    re.compile(rf"^(?:start working on|work on|code on|continue (?:working )?on)\s+{_P}\s*[,:-]?\s*"
               rf"(?:and\s+|to\s+|then\s+|so that\s+)?(?P<task>.{{6,}})$", re.I),
    re.compile(rf"^(?:in|for)\s+(?:the\s+)?project\s+(?P<p>[\w-]+)\s*,?\s*(?P<task>.{{6,}})$", re.I),
    re.compile(rf"^(?:use|ask|have|let)\s+claude(?:\s+code)?\s+(?:to\s+)?(?P<task>.{{6,}}?)\s+(?:in|on|for)\s+"
               rf"(?:the\s+)?(?:project\s+)?(?P<p>[\w-]+)$", re.I),
]
_OPEN = [
    re.compile(r"^open (?:up )?(?:my |the )?project (?P<p>[\w-]+)(?: in vs ?code)?$", re.I),
    re.compile(r"^open (?:up )?(?:my |the )?(?P<p>[\w-]+)(?: project)? in vs ?code$", re.I),
]
_OPEN_ON_LAPTOP = re.compile(r"^open (?:up )?(?:my |the )?(?:project )?(?P<p>[\w-]+)(?: project)?(?: in vs ?code)?$", re.I)
_RUN = re.compile(r"^run (?:the |my )?(?P<cmd>[\w -]{2,30}?)(?: command| script)? (?:for|in|on) (?:the )?(?:project )?"
                  r"(?P<p>[\w-]+)$", re.I)
_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|go|go ahead|do it|start|start it|confirm|please do|yes please|"
                  r"go for it|yes go ahead|yes start|absolutely)(?: please)?(?: edith| sir)?$", re.I)
_NO = re.compile(r"^(?:no|nope|cancel|don'?t|do not|stop|wait|not now|never ?mind|no thanks|leave it)(?: edith| sir)?$", re.I)
CONFIRM_TTL_S = 90
_pending: dict[str, tuple[dict[str, Any], float]] = {}

_TASKS = re.compile(r"^(?:what are|list|show)(?: me)? my (?:background )?tasks\??$|^(?:task|tasks) status\??$", re.I)
_CANCEL = re.compile(r"^(?:cancel|stop) (?:the |my )?(?:last |latest |current )?(?:background |laptop |coding |pc )?"
                     r"(?:task|job|work)\.?$|^stop (?:working on|the work on) (?:my )?(?:laptop|project)\b.*$", re.I)


def _clean(text: str) -> str:
    return " ".join(text.strip().split()).strip(" .!")


def guess_category(fact: str, project: str | None) -> str:
    low = fact.lower()
    for name, pattern in _CATEGORY_HINTS:
        if pattern.search(low):
            return name
    return "project" if project else "general"


def _laptop(t: str) -> dict[str, Any] | None:
    """Laptop commands. 'turn on my laptop and ...' / '... on my laptop' also ask the phone to wake it."""
    explicit = False
    if m := _LAPTOP_PREFIX.match(t):
        t, explicit = t[m.end():].strip(), True
    if m := _LAPTOP_SUFFIX.search(t):
        t, explicit = t[:m.start()].strip(), True
    for pattern in _AGENT:
        if m := pattern.match(t):
            task = m.group("task").strip(" .")
            return {"kind": "confirm", "wake": explicit, "type": "pc", "project": m.group("p"),
                    "params": {"kind": "agent", "args": {"project": m.group("p"), "task": task}},
                    "title": f"Laptop: {task[:80]} ({m.group('p')})"}
    for pattern in _OPEN + ([_OPEN_ON_LAPTOP] if explicit else []):
        if m := pattern.match(t):
            return {"kind": "task", "wake": explicit, "type": "pc", "title": f"Laptop: open {m.group('p')}",
                    "params": {"kind": "open_project", "args": {"project": m.group("p")}}}
    if (m := _RUN.match(t)) and not re.match(r"^(?:the |my )?tests?$", m.group("cmd"), re.I):
        cmd = m.group("cmd").strip()
        return {"kind": "task", "wake": explicit, "type": "pc", "title": f"Laptop: {cmd} in {m.group('p')}",
                "params": {"kind": "run_command", "args": {"project": m.group("p"), "command": cmd}}}
    return None


def take_confirmation(user_id: str, text: str) -> tuple[str, dict[str, Any] | None]:
    """When EDITH asked 'Should I start?': ('yes', cmd) | ('no', None) | ('none', None)."""
    item = _pending.pop(user_id, None)
    if not item or item[1] < time.time():
        return "none", None
    t = re.sub(r"\bedith\b", "", _clean(text).lower().replace(",", "")).strip()
    t = " ".join(t.split())
    if _YES.match(t):
        return "yes", item[0]
    if _NO.match(t):
        return "no", None
    return "none", None  # something else: drop the question rather than act on a later "yes"


def parse(text: str) -> dict[str, Any] | None:
    t = _clean(text)
    if cmd := _laptop(t):
        return cmd
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
    rest = _LAPTOP_PREFIX.sub("", t)
    for kind, pattern in _PC:
        if m := pattern.match(rest):
            args = {"project": (m.group("p") or "").strip() or None}
            return {"kind": "task", "type": "pc", "params": {"kind": kind, "args": args}, "wake": rest != t}
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
    if kind == "confirm":
        # Writing code on the laptop is high-impact: read it back and wait for a clear yes.
        _pending[user_id] = ({**cmd, "kind": "task"}, time.time() + CONFIRM_TTL_S)
        task_text = cmd["params"]["args"]["task"]
        return (f"Should I start Claude Code on {cmd['project']} to {task_text}? It works on a new branch and "
                f"pushes nothing. Say yes to start."), None
    # kind == "task"
    params = cmd["params"]
    title = cmd.get("title") or TITLES.get(cmd["type"], cmd["type"]).format(
        **{k: str(v)[:80] for k, v in params.items()})
    bridge = getattr(tasks, "bridge", None)
    wake = cmd["type"] == "pc" and (cmd.get("wake") or (bridge is not None and not bridge.online(user_id)))
    task = await tasks.submit(user_id, cmd["type"], params, title=title, priority=4)
    info = {**task.public(), "wake_pc": bool(wake)}
    if cmd["type"] == "pc" and params.get("kind") == "agent":
        say = (f"Starting{sir}. {'Waking your laptop first. ' if wake else ''}I'll tell you when the code is "
               "written and tested.")
    elif cmd["type"] == "pc":
        say = f"{'Waking your laptop. ' if wake else ''}On it{sir}."
    else:
        say = f"On it{sir}. I'll work on that in the background and let you know when it's done."
    return say, info
