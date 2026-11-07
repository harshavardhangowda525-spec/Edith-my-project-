"""Deterministic local answers for tiny requests (no AI call, ~0 ms): arithmetic, percentages,
powers and a few unit conversions. Anything unclear returns None and goes to the AI."""
from __future__ import annotations

import math
import re

_NUM = r"(-?\d+(?:\.\d+)?)"
_WORDS = {"plus": "+", "add": "+", "minus": "-", "less": "-", "times": "*", "multiplied by": "*", "x": "*",
          "into": "*", "divided by": "/", "over": "/", "by": "/"}


def _fmt(v: float) -> str:
    if math.isfinite(v) and abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.4f}".rstrip("0").rstrip(".")


def device_answer(text: str, address: str | None, client_time: str | None, battery: int | None) -> str | None:
    """Time, date and battery questions answered from the phone's own data."""
    from datetime import datetime

    t = re.sub(r"[^\w' ]", " ", text.lower())
    t = " ".join(re.sub(r"^(?:hey |ok )?(?:edith )?", "", t).split())
    sir = f", {address}" if address else ""
    now = None
    if client_time:
        try:
            now = datetime.fromisoformat(client_time.replace("Z", "+00:00"))
        except ValueError:
            now = None
    if now and re.fullmatch(r"(?:what(?:'s| is) the |tell me the |what )?time(?: is it)?(?: now)?(?: please)?|"
                            r"what time is it(?: now)?(?: please)?", t):
        return f"It's {now.strftime('%I:%M %p').lstrip('0')}{sir}."
    if now and re.fullmatch(r"(?:what(?:'s| is) )?(?:the |today's )?(?:date|day)(?: today)?(?: is it)?(?: today)?|"
                            r"what day is (?:it|today)|what(?:'s| is) today(?:'s date)?", t):
        return f"It's {now.strftime('%A, %B')} {now.day}{sir}."
    if battery is not None and re.fullmatch(r"(?:what(?:'s| is) (?:my |the )?)?(?:phone )?battery(?: level| percentage| status)?"
                                            r"(?: left)?|how much battery(?: do i have| is left)?(?: left)?", t):
        joke = " Might want a charger soon." if battery <= 20 else ""
        return f"You're at {battery} percent{sir}.{joke}"
    return None


def quick_answer(text: str, address: str | None = None) -> str | None:
    t = text.lower().strip().rstrip("?.! ")
    t = re.sub(r"^(?:hey |ok )?(?:edith[, ]+)?(?:what(?:'s| is)|calculate|compute|how much is|tell me)\s+", "", t)
    sir = f", {address}" if address else ""
    m = re.fullmatch(rf"{_NUM}\s*(?:percent|%)\s+of\s+{_NUM}", t)
    if m:
        return f"That's {_fmt(float(m.group(1)) / 100 * float(m.group(2)))}{sir}."
    m = re.fullmatch(rf"{_NUM}\s+(?:to the power(?: of)?|raised to(?: the power of)?|\^)\s+{_NUM}", t)
    if m and abs(float(m.group(2))) <= 100:
        return f"That's {_fmt(float(m.group(1)) ** float(m.group(2)))}{sir}."
    m = re.fullmatch(rf"(?:the )?square root of {_NUM}", t)
    if m and float(m.group(1)) >= 0:
        return f"That's {_fmt(math.sqrt(float(m.group(1))))}{sir}."
    m = re.fullmatch(rf"{_NUM}\s*(plus|add|minus|less|times|multiplied by|x|into|divided by|over|[-+*/×÷])\s*{_NUM}", t)
    if m:
        a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
        op = {"×": "*", "÷": "/"}.get(op, _WORDS.get(op, op))
        if op == "/" and b == 0:
            return f"Dividing by zero? Nice try{sir}. That's undefined."
        v = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0}[op]
        return f"That's {_fmt(v)}{sir}."
    m = re.fullmatch(rf"(?:convert )?{_NUM}\s*(km|kilometers?|kilometres?|miles?|kg|kilograms?|pounds?|lbs?|"
                     rf"celsius|c|fahrenheit|f)\s+(?:to|in|into)\s+(km|kilometers?|kilometres?|miles?|kg|kilograms?|"
                     rf"pounds?|lbs?|celsius|c|fahrenheit|f)", t)
    if m:
        v, src, dst = float(m.group(1)), m.group(2)[0], m.group(3)[0]
        conv = {("k", "m"): (lambda x: x * 0.621371, "miles"), ("m", "k"): (lambda x: x / 0.621371, "kilometres"),
                ("p", "k"): (lambda x: x * 0.453592, "kilograms"), ("l", "k"): (lambda x: x * 0.453592, "kilograms"),
                ("c", "f"): (lambda x: x * 9 / 5 + 32, "degrees Fahrenheit"),
                ("f", "c"): (lambda x: (x - 32) * 5 / 9, "degrees Celsius")}
        key = (src, dst) if (src, dst) in conv else ("k" if m.group(2).startswith("kg") or m.group(2).startswith("kilog") else src,
                                                    "p" if dst in "pl" else dst)
        if m.group(2).startswith(("kg", "kilog")) and dst in "pl":
            return f"That's {_fmt(v / 0.453592)} pounds{sir}."
        if key in conv:
            fn, unit = conv[key]
            return f"That's {_fmt(round(fn(v), 2))} {unit}{sir}."
    return None
