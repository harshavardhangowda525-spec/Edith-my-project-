"""The kinds of background work EDITH can run. Each handler returns the real result text,
or raises - a task is never marked completed without one."""
from __future__ import annotations

from typing import Any

from app.errors import AppError, NotFoundError, ValidationFailed
from app.services.ai_service import AIService
from app.services.bridge import BridgeHub
from app.services.github_service import GitHubService
from app.services.memory_service import MemoryService
from app.services.tasks import TaskContext, TaskEngine

TASK_TYPES = {
    "research": "Think a question through in depth with the deep model",
    "summarize_document": "Summarise one of your uploaded documents",
    "github_summary": "Summarise a GitHub repository: PRs, issues and CI",
    "pc": "Run an approved job on your PC through the EDITH bridge",
}


def register_handlers(engine: TaskEngine, *, ai: AIService, memory: MemoryService, store: Any,
                      github: GitHubService, bridge: BridgeHub, bridge_timeout_s: float) -> None:

    async def research(ctx: TaskContext) -> str:
        q = str(ctx.task.params.get("question", "")).strip()
        if not q:
            raise ValidationFailed("research needs a question")
        await ctx.progress(10, "Thinking it through")
        mem = memory.for_prompt(ctx.user_id)
        result = await ai.chat(q, [], mode="detailed", route="deep", memories=mem)
        if result.mock:
            raise AppError("No real AI provider is connected (mock mode); research can't run.")
        return result.text

    async def summarize_document(ctx: TaskContext) -> str:
        doc_id = str(ctx.task.params.get("document_id", ""))
        chunks = store.list_chunks(ctx.user_id, [doc_id])
        if not chunks:
            raise NotFoundError("Document not found")
        await ctx.progress(20, f"Reading {chunks[0].title}")
        text = "\n".join(c.content for c in sorted(chunks, key=lambda c: c.chunk_index))[:24000]
        result = await ai.chat("Summarise this document in clear bullet points, then list action items.\n\n"
                               "<document>\n" + text + "\n</document>", [], mode="detailed", route="balanced")
        if result.mock:
            raise AppError("No real AI provider is connected (mock mode); the summary can't be written.")
        return result.text

    async def github_summary(ctx: TaskContext) -> str:
        await ctx.progress(20, "Asking GitHub")
        return await github.summary(ctx.task.params.get("repo"))

    async def pc(ctx: TaskContext) -> str:
        kind = str(ctx.task.params.get("kind", ""))
        await ctx.progress(10, "Waiting for your PC to accept the job")
        ok, output = await bridge.run(ctx.user_id, kind, dict(ctx.task.params.get("args") or {}), bridge_timeout_s)
        if not ok:
            raise AppError(output[:2000] or "The PC job failed", code="pc_job_failed")
        return output

    engine.register("research", research, timeout_s=180)
    engine.register("summarize_document", summarize_document, timeout_s=180)
    engine.register("github_summary", github_summary, timeout_s=60)
    engine.register("pc", pc, timeout_s=bridge_timeout_s + 30)
