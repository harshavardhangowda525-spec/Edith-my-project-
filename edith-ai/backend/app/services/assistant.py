"""The EDITH request pipeline, shared by the streaming and non-streaming endpoints.

Order (fastest first):
1. conversation-mode quick decisions (end / ignore / bare "Edith")        ~0 ms
2. phone commands from patterns (call, open, play...)                      ~0 ms
3. deterministic local answers (arithmetic, conversions)                   ~0 ms
4. memories + documents, fetched in parallel (cached)                      ~0-50 ms
5. response cache for repeated stateless questions                         ~0 ms
6. routed, streamed model answer with fallbacks                            first token ASAP
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from typing import AsyncIterator

from starlette.concurrency import run_in_threadpool

from app.models.schemas import ChatRequest
from app.services import command_service
from app.services.ai_service import AIService
from app.services.cache import TTLCache
from app.services.memory_service import MemoryService
from app.services.quick import device_answer, quick_answer
from app.services.retrieval_service import RetrievalService

# Questions whose answers change: never served from cache.
_TIME_SENSITIVE = re.compile(r"\b(now|today|tonight|tomorrow|yesterday|time|date|weather|news|latest|current|"
                             r"score|price|stock|this week|remind|my|me|i|i'm|i've)\b", re.I)
response_cache = TTLCache(ttl_s=600, max_items=500)


def _cache_key(message: str, route: str, address: str | None, language: str | None, memories: list[str]) -> str:
    norm = " ".join(re.sub(r"[^\w ]", " ", message.lower()).split())
    mem = hashlib.sha256("\n".join(memories).encode()).hexdigest()[:12]
    return f"{route}|{address}|{language}|{mem}|{norm}"


async def assistant_events(body: ChatRequest, user_id: str, ai: AIService, memory: MemoryService,
                           retrieval: RetrievalService) -> AsyncIterator[dict]:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def done(**extra) -> dict:
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        ai.metrics.observe("assistant_total_ms", timings["total_ms"])
        return {"type": "done", "timings": timings, **extra}

    message = body.message
    directed = True
    if body.followup:
        quick = command_service.followup_kind(message)
        if quick == "end":
            yield {"type": "end", "say": "Okay."}
            yield done(route="local")
            return
        if quick == "ignore":
            yield {"type": "ignore"}
            yield done(route="local")
            return
        if quick == "wake":
            yield {"type": "token", "t": f"Yes{', ' + body.address if body.address else ''}?"}
            yield done(route="local")
            return
        directed = command_service.addressed_to_edith(message)
        if directed:
            message = command_service.strip_wake_word(message)

    action = await command_service.understand(message, ai, allow_ai=directed)
    if action:
        timings["understand_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        yield {"type": "action", "action": action, "say": command_service.describe(action)}
        yield done(route="command")
        return

    if directed:
        local = device_answer(message, body.address, body.client_time, body.battery) or quick_answer(message, body.address)
        if local:
            ai.metrics.count("local_answers")
            yield {"type": "meta", "route": "local", "model": "local"}
            yield {"type": "token", "t": local}
            yield done(route="local")
            return

    tc = time.perf_counter()
    memories, sources = await asyncio.gather(
        run_in_threadpool(memory.for_prompt, user_id) if body.use_memory else _none(),
        run_in_threadpool(retrieval.search, user_id, message) if body.use_documents else _none(),
    )
    memories, sources = memories or [], sources or []
    timings["context_ms"] = round((time.perf_counter() - tc) * 1000, 1)
    ai.metrics.observe("context_ms", timings["context_ms"])

    route = ai.pick_route(message, body.route, len(body.history), bool(sources))
    cacheable = (directed and not body.history and not sources and not body.model and route == "fast"
                 and not _TIME_SENSITIVE.search(message))
    key = _cache_key(message, route, body.address, body.language, memories) if cacheable else None
    if key:
        hit = response_cache.get(key)
        if hit:
            ai.metrics.count("cache_hit")
            yield {"type": "meta", "route": route, "model": hit["model"], "cached": True}
            yield {"type": "token", "t": hit["text"]}
            yield done(route=route, model=hit["model"], cached=True)
            return
        ai.metrics.count("cache_miss")

    prompt = message if directed else message + command_service.FOLLOWUP_NOTE
    if body.client_time:
        prompt += f"\n\n(User's local time: {body.client_time})"
    if sources:
        yield {"type": "sources", "sources": [s.model_dump() for s in sources]}
    held: list[str] = []          # undirected follow-ups: hold the first characters to catch NOT_FOR_ME
    released = directed
    parts: list[str] = []
    final: dict = {}
    async for ev in ai.stream_chat(prompt, body.history, mode=body.mode, route=route, model=body.model,
                                   memories=memories, sources=sources, language=body.language,
                                   address=body.address):
        if ev["type"] == "token":
            parts.append(ev["t"])
            if not released:
                held.append(ev["t"])
                so_far = "".join(held).lstrip()
                if command_service.NOT_FOR_ME in so_far.upper().replace(" ", "_"):
                    yield {"type": "ignore"}
                    yield done(route=route)
                    return
                norm = so_far.upper().replace(" ", "_")
                if command_service.NOT_FOR_ME.startswith(norm):
                    continue  # could still become NOT_FOR_ME: keep holding (at most ~10 characters)
                released = True
                ev = {**ev, "t": "".join(held)}
            if "first_token_ms" not in timings:
                timings["first_token_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                ai.metrics.observe("assistant_first_token_ms", timings["first_token_ms"])
            yield ev
        elif ev["type"] == "meta":
            yield ev
        elif ev["type"] == "done":
            final = ev
    if not released:  # short undirected reply that never reached the hold limit
        so_far = "".join(held)
        if command_service.NOT_FOR_ME in so_far.upper().replace(" ", "_"):
            yield {"type": "ignore"}
            yield done(route=route)
            return
        yield {"type": "token", "t": so_far}
    text = "".join(parts).strip()
    if key and text:
        response_cache.set(key, {"text": text, "model": final.get("model", "")})
    yield done(route=final.get("route", route), model=final.get("model"), usage=final.get("usage", {}),
               model_first_token_ms=final.get("first_token_ms"))


async def _none():
    return None
