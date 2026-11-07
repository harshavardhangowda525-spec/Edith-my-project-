"""Streaming, routing/fallback, caching, local answers and metrics."""
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.quick import quick_answer
from app.services.router import CircuitBreaker, classify
from tests.conftest import auth, make_settings

BASE = "https://api.groq.com/openai/v1"


def events(resp) -> list[dict]:
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def sse_chunks(words, model="m"):
    body = "".join(f"data: {json.dumps({'model': model, 'choices': [{'delta': {'content': w}}]})}\n\n" for w in words)
    body += f"data: {json.dumps({'model': model, 'choices': [], 'x_groq': {'usage': {'prompt_tokens': 7, 'completion_tokens': 3}}})}\n\n"
    return body + "data: [DONE]\n\n"


def groq_client(**kw):
    return TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_x", **kw)))


@pytest.mark.parametrize("text, route", [
    ("Hello Edith", "fast"), ("What is the capital of Japan?", "fast"), ("Tell me a joke", "fast"),
    ("How do I fix a CORS error in my React app?", "balanced"), ("Explain Python decorators", "balanced"),
    ("Design a scalable architecture for a chat app with millions of users", "deep"),
    ("Walk me through debugging a memory leak in Node", "deep"),
])
def test_classify(text, route):
    assert classify(text) == route


@respx.mock
def test_stream_routes_simple_question_to_fast_model():
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, text=sse_chunks(["Tokyo", ", sir", "."]), headers={"content-type": "text/event-stream"}))
    c = groq_client()
    r = c.post("/api/assistant/stream", headers=auth(), json={"message": "What is the capital of Japan?", "address": "sir"})
    ev = events(r)
    assert ev[0] == {"type": "meta", "route": "fast", "model": "llama-3.1-8b-instant", "requested_route": "fast"}
    assert "".join(e["t"] for e in ev if e["type"] == "token") == "Tokyo, sir."
    done = ev[-1]
    assert done["type"] == "done" and done["model"] == "m" and "first_token_ms" in done["timings"]
    sent = json.loads(route.calls[0].request.content)
    assert sent["stream"] is True and sent["model"] == "llama-3.1-8b-instant"


@respx.mock
def test_deep_route_uses_reasoning_model_and_effort():
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, text=sse_chunks(["Plan"]), headers={"content-type": "text/event-stream"}))
    c = groq_client()
    c.post("/api/assistant/stream", headers=auth(), json={"message": "Design a scalable architecture for payments"})
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "openai/gpt-oss-120b" and sent["reasoning_effort"] == "medium" and sent["max_tokens"] == 2000


@respx.mock
def test_rate_limited_model_falls_back_and_breaker_opens():
    def handler(request):
        model = json.loads(request.content)["model"]
        if model == "llama-3.1-8b-instant":
            return httpx.Response(429, json={"error": {"message": "Rate limit reached"}})
        return httpx.Response(200, text=sse_chunks(["Fallback answer"], model=model), headers={"content-type": "text/event-stream"})

    respx.post(f"{BASE}/chat/completions").mock(side_effect=handler)
    c = groq_client()
    ev = events(c.post("/api/assistant/stream", headers=auth(), json={"message": "Hello Edith"}))
    metas = [e for e in ev if e["type"] == "meta"]
    assert [m["model"] for m in metas] == ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]
    assert "".join(e["t"] for e in ev if e["type"] == "token") == "Fallback answer"
    # The rate-limited model is skipped (circuit open) on the next request.
    ev2 = events(c.post("/api/assistant/stream", headers=auth(), json={"message": "Hi again"}))
    assert [e for e in ev2 if e["type"] == "meta"][0]["model"] == "llama-3.3-70b-versatile"
    m = c.get("/api/metrics", headers=auth()).json()
    assert m["counters"]["ai_fallbacks"] >= 1 and "llama-3.1-8b-instant" in m["circuit_breakers"]


@respx.mock
def test_bad_key_does_not_fall_back():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401, json={"error": {"message": "bad key"}}))
    c = groq_client()
    ev = events(c.post("/api/assistant/stream", headers=auth(), json={"message": "Hello"}))
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "provider_auth"
    assert route.call_count == 1


def test_manual_route_override():
    c = groq_client()
    ai = c.app.state.ai
    assert ai.pick_route("hi", "deep", 0, False) == "deep"
    assert ai.candidates("deep", None)[0] == ("deep", "openai/gpt-oss-120b")


@respx.mock
def test_response_cache_for_repeated_simple_question():
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, text=sse_chunks(["Seven", "."]), headers={"content-type": "text/event-stream"}))
    c = groq_client()
    body = {"message": "How many continents are there?"}
    a = events(c.post("/api/assistant/stream", headers=auth(), json=body))
    b = events(c.post("/api/assistant/stream", headers=auth(), json=body))
    assert route.call_count == 1 and b[0].get("cached") is True
    assert "".join(e["t"] for e in b if e["type"] == "token") == "Seven."
    # time-sensitive / personal questions are never cached
    from app.services.assistant import _TIME_SENSITIVE
    assert _TIME_SENSITIVE.search("what's the weather today") and _TIME_SENSITIVE.search("what is my name")


def test_local_answers_without_ai():
    assert quick_answer("What's 12 times 8?", "sir") == "That's 96, sir."
    assert quick_answer("what is 15 percent of 200") == "That's 30."
    assert quick_answer("2 to the power 10") == "That's 1,024."
    assert quick_answer("convert 10 km to miles") == "That's 6.21 miles."
    assert quick_answer("100 c to f") == "That's 212 degrees Fahrenheit."
    assert quick_answer("what is 5 divided by 0").startswith("Dividing by zero")
    assert quick_answer("what is love") is None
    c = TestClient(create_app(make_settings()))
    ev = events(c.post("/api/assistant/stream", headers=auth(), json={"message": "What's 99 plus 1?"}))
    assert ev[0]["route"] == "local" and ev[1]["t"] == "That's 100."


@respx.mock
def test_voice_ask_single_round_trip():
    respx.post(f"{BASE}/audio/transcriptions").mock(return_value=httpx.Response(200, json={"text": "Call mom"}))
    c = groq_client()
    r = c.post("/api/voice/ask", headers=auth(), files={"audio": ("q.wav", b"RIFF" + b"\0" * 2000, "audio/wav")},
               data={"address": "sir", "history": "[]"})
    ev = events(r)
    assert ev[0]["type"] == "transcript" and ev[0]["text"] == "Call mom"
    assert any(e["type"] == "action" and e["action"]["type"] == "call" for e in ev)


@respx.mock
def test_voice_ask_followup_side_talk_ignored():
    respx.post(f"{BASE}/audio/transcriptions").mock(return_value=httpx.Response(200, json={"text": "Let's grab lunch later"}))
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(
        200, text=sse_chunks(["NOT", "_FOR", "_ME"]), headers={"content-type": "text/event-stream"}))
    c = groq_client()
    ev = events(c.post("/api/voice/ask", headers=auth(), data={"followup": "true"},
                       files={"audio": ("q.wav", b"RIFF" + b"\0" * 2000, "audio/wav")}))
    assert any(e["type"] == "ignore" for e in ev) and not any(e["type"] == "token" for e in ev)


def test_followup_answer_is_released_not_swallowed():
    c = TestClient(create_app(make_settings()))
    from tests.test_commands import ScriptedProvider
    c.app.state.ai._provider = ScriptedProvider(["Docker packs apps into containers."])
    r = c.post("/api/assistant", headers=auth(), json={"message": "and what is docker used for", "followup": True})
    assert r.json()["kind"] == "answer" and r.json()["reply"] == "Docker packs apps into containers."


def test_breaker_unit():
    b = CircuitBreaker(threshold=2, cooldown_s=60)
    b.failure("m")
    assert b.available("m")
    b.failure("m")
    assert not b.available("m")
    b.success("m")
    assert b.available("m")


def test_metrics_requires_auth():
    c = TestClient(create_app(make_settings()))
    assert c.get("/api/metrics").status_code == 401
    assert "latency" in c.get("/api/metrics", headers=auth()).json()


def test_device_answers_use_phone_time_and_battery():
    from app.services.quick import device_answer
    t = "2026-11-07T21:05:00+05:30"
    assert device_answer("What time is it?", "sir", t, None) == "It's 9:05 PM, sir."
    assert device_answer("what's the date today", None, t, None) == "It's Saturday, November 7."
    assert device_answer("Battery level?", "sir", None, 15) == "You're at 15 percent, sir. Might want a charger soon."
    assert device_answer("what time does the shop close", "sir", t, 50) is None
    c = TestClient(create_app(make_settings()))
    ev = events(c.post("/api/assistant/stream", headers=auth(),
                       json={"message": "Edith what time is it", "client_time": t, "address": "sir"}))
    assert ev[1]["t"] == "It's 9:05 PM, sir."
