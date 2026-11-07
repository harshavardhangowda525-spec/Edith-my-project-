"""Intelligent model routing: classify each request and pick the cheapest model that fits.

fast     greetings, small talk, short facts, quick commands      -> low-latency small model
balanced everyday coding / project questions, grounded answers   -> AI_MODEL
deep     architecture, multi-step debugging, in-depth analysis   -> reasoning model

Classification is deterministic and local (microseconds), so it never adds latency.
A circuit breaker skips models that keep failing; fallbacks keep answers flowing during
rate limits or outages.
"""
from __future__ import annotations

import re
import threading
import time

ROUTES = ("fast", "balanced", "deep")

_DEEP = re.compile(
    r"\b(architect(?:ure)?|system design|design (?:a|an|the)\b|in depth|in-depth|in detail|detailed (?:plan|"
    r"analysis|explanation)|step[- ]by[- ]step|trade-?offs?|compare .{0,40}\b(?:in detail|thoroughly)|"
    r"refactor|investigat\w*|root cause|memory leak|race condition|deadlock|prove|optimi[sz]e .{0,30}"
    r"(?:architecture|system|performance)|scal(?:e|able|ability)|threat model|migration plan|"
    r"walk (?:me )?through)\b", re.I)
_TECH = re.compile(
    r"\b(code|coding|function|class|method|bug|debug|error|exception|traceback|stack ?trace|compile|"
    r"python|javascript|typescript|java|kotlin|dart|flutter|react|next\.?js|node|sql|database|query|api|"
    r"endpoint|deploy|docker|kubernetes|git|github|supabase|firebase|aws|vercel|regex|algorithm|"
    r"async|await|promise|widget|component|hook|test|pytest|npm|pip|package|library|framework|server|"
    r"cors|jwt|auth|schema|json|yaml|css|html|lambda|cache|thread)\b", re.I)


def classify(message: str, history_len: int = 0, has_sources: bool = False) -> str:
    text = message.strip()
    lines = text.count("\n")
    if _DEEP.search(text) or len(text) > 400 or lines > 15:
        return "deep"
    if _TECH.search(text) or has_sources or len(text) > 160 or "```" in text:
        return "balanced"
    return "fast"


def fallback_order(route: str) -> list[str]:
    return {"fast": ["fast", "balanced"], "balanced": ["balanced", "fast"],
            "deep": ["deep", "balanced", "fast"]}.get(route, ["balanced", "fast"])


class CircuitBreaker:
    """Opens for `cooldown_s` after `threshold` consecutive failures of a model."""

    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0) -> None:
        self.threshold, self.cooldown = threshold, cooldown_s
        self._fail: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def available(self, model: str) -> bool:
        with self._lock:
            return time.monotonic() >= self._open_until.get(model, 0.0)

    def success(self, model: str) -> None:
        with self._lock:
            self._fail[model] = 0
            self._open_until.pop(model, None)

    def failure(self, model: str, rate_limited: bool = False) -> None:
        with self._lock:
            n = self._fail.get(model, 0) + 1
            self._fail[model] = n
            if rate_limited or n >= self.threshold:
                # A rate limit opens immediately: retrying the same model right away only fails again.
                self._open_until[model] = time.monotonic() + (self.cooldown if not rate_limited else 20.0)

    def state(self) -> dict[str, dict]:
        now = time.monotonic()
        with self._lock:
            return {m: {"consecutive_failures": self._fail.get(m, 0),
                        "open_for_s": round(max(0.0, self._open_until.get(m, 0) - now), 1)}
                    for m in set(self._fail) | set(self._open_until)}
