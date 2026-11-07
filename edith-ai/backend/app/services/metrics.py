"""In-process performance metrics: latency percentiles, counters, token usage and cost.

Keeps the most recent samples per metric (no external dependency). Exposed at GET /api/metrics.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque

WINDOW = 2000


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=WINDOW))
        self._counters: dict[str, int] = defaultdict(int)
        self._tokens: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # model -> [in, out]
        self.started = time.time()
        try:
            # Optional USD prices per 1M tokens: {"model": [input, output]}. No prices are assumed.
            self._prices: dict[str, list[float]] = json.loads(os.getenv("AI_PRICES_PER_MTOK", "") or "{}")
        except ValueError:
            self._prices = {}

    def observe(self, name: str, ms: float) -> None:
        with self._lock:
            self._samples[name].append(ms)

    def count(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counters[name] += n

    def tokens(self, model: str, prompt: int, completion: int) -> None:
        with self._lock:
            t = self._tokens[model]
            t[0] += int(prompt or 0)
            t[1] += int(completion or 0)

    def snapshot(self) -> dict:
        with self._lock:
            lat = {}
            for name, vals in self._samples.items():
                vs = list(vals)
                lat[name] = {"count": len(vs), "p50_ms": _r(percentile(vs, .5)), "p95_ms": _r(percentile(vs, .95)),
                             "p99_ms": _r(percentile(vs, .99))}
            counters = dict(self._counters)
            tokens = {m: {"prompt": t[0], "completion": t[1]} for m, t in self._tokens.items()}
        cost = {}
        for m, t in tokens.items():
            if m in self._prices:
                pin, pout = self._prices[m]
                cost[m] = round((t["prompt"] * pin + t["completion"] * pout) / 1_000_000, 6)
        hits, misses = counters.get("cache_hit", 0), counters.get("cache_miss", 0)
        reqs, fails = counters.get("ai_requests", 0), counters.get("ai_failures", 0)
        return {
            "uptime_s": round(time.time() - self.started),
            "latency": lat,
            "counters": counters,
            "cache_hit_rate": round(hits / (hits + misses), 3) if hits + misses else None,
            "ai_failure_rate": round(fails / reqs, 3) if reqs else None,
            "tokens": tokens,
            "cost_usd": cost or "set AI_PRICES_PER_MTOK to estimate costs",
        }


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


class Timer:
    """with Timer(metrics, "stage"): ...  -> records milliseconds."""

    def __init__(self, metrics: Metrics | None, name: str, sink: dict | None = None) -> None:
        self.m, self.name, self.sink = metrics, name, sink

    def __enter__(self) -> "Timer":
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        ms = (time.perf_counter() - self.t0) * 1000
        if self.m:
            self.m.observe(self.name, ms)
        if self.sink is not None:
            self.sink[self.name] = round(ms, 1)
