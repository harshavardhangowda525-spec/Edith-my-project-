"""Fake OpenAI-compatible AI + speech provider with realistic, configurable delays.

Used only by the benchmark (no real API keys needed). Simulated costs:
- NEW_CONN_MS: first request on a new TCP connection (stands in for TLS handshake + extra RTT)
- TTFT_MS: model time to first token;  TOKENS_PER_S: generation speed
- STT_MS: speech-to-text time
Numbers are assumptions, documented in the benchmark report - not measurements of Groq.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

NEW_CONN_MS = float(os.getenv("NEW_CONN_MS", "150"))
TTFT_MS = {"small": float(os.getenv("TTFT_SMALL_MS", "150")), "large": float(os.getenv("TTFT_LARGE_MS", "450")),
           "reasoning": float(os.getenv("TTFT_REASONING_MS", "900"))}
TOKENS_PER_S = {"small": 900.0, "large": 300.0, "reasoning": 250.0}
STT_MS = float(os.getenv("STT_MS", "250"))
_seen: set[tuple[str, int]] = set()


def size_of(model: str) -> str:
    if "8b" in model or "instant" in model:
        return "small"
    if "oss-120b" in model or "reason" in model:
        return "reasoning"
    return "large"


async def conn_cost(request: Request) -> None:
    key = (request.client.host, request.client.port) if request.client else ("?", 0)
    if key not in _seen:
        _seen.add(key)
        await asyncio.sleep(NEW_CONN_MS / 1000)


def answer_for(prompt: str) -> str:
    words = 25 if len(prompt) < 60 else 70
    return " ".join(["Sure, here is a clear answer."] + ["word"] * words)


async def chat(request: Request):
    await conn_cost(request)
    body = await request.json()
    model = body.get("model", "large")
    size = size_of(model)
    prompt = body["messages"][-1]["content"]
    text = answer_for(prompt)
    tokens = text.split(" ")
    await asyncio.sleep(TTFT_MS[size] / 1000)
    if not body.get("stream"):
        await asyncio.sleep(len(tokens) / TOKENS_PER_S[size])
        return JSONResponse({"model": model, "choices": [{"message": {"role": "assistant", "content": text}}],
                             "usage": {"prompt_tokens": 50, "completion_tokens": len(tokens)}})

    async def gen():
        for i, tok in enumerate(tokens):
            piece = tok if i == 0 else " " + tok
            yield f"data: {json.dumps({'model': model, 'choices': [{'delta': {'content': piece}}]})}\n\n"
            await asyncio.sleep(1 / TOKENS_PER_S[size])
        yield f"data: {json.dumps({'model': model, 'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'x_groq': {'usage': {'prompt_tokens': 50, 'completion_tokens': len(tokens)}}})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def transcribe(request: Request):
    await conn_cost(request)
    await request.form()
    await asyncio.sleep(STT_MS / 1000)
    return JSONResponse({"text": "What is the capital of Japan?"})


async def models(request: Request):
    await conn_cost(request)
    return JSONResponse({"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "llama-3.1-8b-instant"}]})


app = Starlette(routes=[Route("/v1/chat/completions", chat, methods=["POST"]),
                        Route("/v1/audio/transcriptions", transcribe, methods=["POST"]),
                        Route("/v1/models", models)])
