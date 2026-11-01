"""Model-not-found handling: clear message, automatic switch to an available model, URL cleanup."""
import httpx
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import auth, make_settings

BASE = "https://api.groq.com/openai/v1"


def _reply(model: str) -> httpx.Response:
    return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": f"answer from {model}"}}]})


def _missing(model: str) -> httpx.Response:
    return httpx.Response(404, json={"error": {"message": f"The model `{model}` does not exist or you do not have access to it.",
                                               "code": "model_not_found"}})


@respx.mock
def test_switches_to_available_model_and_remembers() -> None:
    def chat(request: httpx.Request) -> httpx.Response:
        import json
        m = json.loads(request.content)["model"]
        return _reply(m) if m == "openai/gpt-oss-120b" else _missing(m)

    chat_route = respx.post(f"{BASE}/chat/completions").mock(side_effect=chat)
    models = respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json={"data": [
        {"id": "whisper-large-v3"}, {"id": "openai/gpt-oss-120b"}, {"id": "llama-3.1-8b-instant"}]}))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_x", ai_model="Llama 3.3 70B")))
    r = c.post("/api/chat", headers=auth(), json={"message": "hi"})
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "answer from openai/gpt-oss-120b"
    assert r.json()["model"] == "openai/gpt-oss-120b"
    # Second question goes straight to the working model.
    c.post("/api/chat", headers=auth(), json={"message": "again"})
    assert models.call_count == 1
    assert chat_route.call_count == 3


@respx.mock
def test_clear_message_when_nothing_works() -> None:
    respx.post(f"{BASE}/chat/completions").mock(return_value=_missing("bad-model"))
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json={"data": []}))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_secretvalue123", ai_model="bad-model")))
    r = c.post("/api/chat", headers=auth(), json={"message": "hi"})
    assert r.status_code == 502
    msg = r.json()["error"]["message"]
    assert "bad-model" in msg and "api.groq.com" in msg and "does not exist" in msg
    assert "gsk_secretvalue123" not in r.text


def test_full_endpoint_pastes_are_cleaned() -> None:
    for pasted in [f"{BASE}/chat/completions", f"{BASE}/", "https://api.groq.com", "https://api.groq.com/openai"]:
        s = make_settings(ai_provider="groq", ai_api_key="k", ai_base_url=pasted)
        assert s.ai_base_url == BASE, pasted
    o = make_settings(ai_provider="openai", ai_api_key="k", ai_base_url="https://api.openai.com/v1/chat/completions")
    assert o.ai_base_url == "https://api.openai.com/v1"


@respx.mock
def test_decommissioned_400_also_switches() -> None:
    def chat(request: httpx.Request) -> httpx.Response:
        import json
        m = json.loads(request.content)["model"]
        if m == "llama-3.3-70b-versatile":
            return _reply(m)
        return httpx.Response(400, json={"error": {"message": f"The model `{m}` has been decommissioned",
                                                   "code": "model_decommissioned"}})

    respx.post(f"{BASE}/chat/completions").mock(side_effect=chat)
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "llama-3.3-70b-versatile"}]}))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="k", ai_model="mixtral-8x7b-32768")))
    r = c.post("/api/chat", headers=auth(), json={"message": "hi"})
    assert r.status_code == 200 and r.json()["model"] == "llama-3.3-70b-versatile"
