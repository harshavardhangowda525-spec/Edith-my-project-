"""EDITH latency benchmark.

Starts a fake provider (bench/fake_upstream.py) on localhost and drives the EDITH app in-process.
Measures, per request: time to first useful text (TTFT) and total time, for the endpoints the
phone uses. Run:  python -m bench.run_bench [--label before|after] [--out results.json]
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import socket
import statistics
import sys
import threading
import time
import wave

import httpx
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_upstream(port: int) -> None:
    from bench.fake_upstream import app
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    threading.Thread(target=uvicorn.Server(cfg).run, daemon=True).start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.05)


def tiny_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * 16000)
    return buf.getvalue()


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


async def run(label: str) -> dict:
    port = free_port()
    start_upstream(port)
    os.environ.update({"AI_PROVIDER": "groq", "AI_API_KEY": "bench", "AI_BASE_URL": f"http://127.0.0.1:{port}/v1",
                       "SPEECH_BASE_URL": f"http://127.0.0.1:{port}/v1", "AUTH_MODE": "local",
                       "LOCAL_ACCESS_TOKENS": "bench-token:00000000-0000-0000-0000-0000000000be",
                       "RATE_LIMIT_PER_MINUTE": "100000", "STORAGE_BACKEND": "memory", "ENVIRONMENT": "test"})
    from app.config import Settings
    from app.main import create_app
    from bench.requests import ALL

    app = create_app(Settings(_env_file=None))
    has_stream = any(getattr(r, "path", "") == "/api/assistant/stream" for r in app.routes)
    has_voice_ask = any(getattr(r, "path", "") == "/api/voice/ask" for r in app.routes)
    headers = {"Authorization": "Bearer bench-token"}
    # Run EDITH behind a real HTTP server so streamed events arrive as they are produced.
    eport = free_port()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=eport, log_level="error")
    threading.Thread(target=uvicorn.Server(cfg).run, daemon=True).start()
    for _ in range(200):
        try:
            httpx.get(f"http://127.0.0.1:{eport}/health", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    results: list[dict] = []
    wav = tiny_wav()
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{eport}", headers=headers, timeout=60) as c:
        for kind, text in ALL:
            t0 = time.perf_counter()
            first = None
            if kind == "voice":
                if has_voice_ask:
                    async with c.stream("POST", "/api/voice/ask", files={"audio": ("q.wav", wav, "audio/wav")},
                                        data={"address": "sir"}) as r:
                        async for line in r.aiter_lines():
                            if first is None and line.startswith("data:") and '"token"' in line:
                                first = time.perf_counter()
                else:  # before: two sequential requests, as the phone did
                    r1 = await c.post("/api/voice/transcribe", files={"audio": ("q.wav", wav, "audio/wav")})
                    q = r1.json()["text"]
                    await c.post("/api/assistant", json={"message": q, "address": "sir"})
                    first = time.perf_counter()
            elif has_stream:
                async with c.stream("POST", "/api/assistant/stream", json={"message": text, "address": "sir"}) as r:
                    async for line in r.aiter_lines():
                        if first is None and line.startswith("data:") and ('"token"' in line or '"action"' in line):
                            first = time.perf_counter()
            else:
                await c.post("/api/assistant", json={"message": text, "address": "sir"})
                first = time.perf_counter()
            total = time.perf_counter() - t0  # after the full response/stream was read
            results.append({"kind": kind, "text": text, "ttft": (first or time.perf_counter()) - t0, "total": total})
    summary = {}
    for kind in ["simple", "coding", "command", "voice", "all"]:
        rows = [r for r in results if kind == "all" or r["kind"] == kind]
        summary[kind] = {m: {"p50": round(pct([r[m] for r in rows], .5) * 1000),
                             "p95": round(pct([r[m] for r in rows], .95) * 1000),
                             "p99": round(pct([r[m] for r in rows], .99) * 1000)} for m in ("ttft", "total")}
        summary[kind]["n"] = len(rows)
    return {"label": label, "requests": len(results), "summary": summary,
            "assumptions": {"NEW_CONN_MS": os.getenv("NEW_CONN_MS", "150"), "TTFT_MS": "small 150 / large 450 / reasoning 900",
                            "tokens_per_s": "small 900 / large 300 / reasoning 250", "STT_MS": os.getenv("STT_MS", "250")}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    res = asyncio.run(run(a.label))
    print(json.dumps(res["summary"], indent=1))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
