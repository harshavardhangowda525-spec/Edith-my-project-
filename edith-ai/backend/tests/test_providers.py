"""AI_PROVIDER names: OpenAI-compatible presets (groq, ...), defaults, unknown values."""
import httpx
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import auth, make_settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _ok(model: str = "m") -> httpx.Response:
    return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": "Hi from Groq."}}]})


def test_groq_fills_address_and_model() -> None:
    s = make_settings(ai_provider="groq", ai_api_key="gsk_test")
    assert s.ai_provider_kind == "openai"
    assert s.ai_base_url == "https://api.groq.com/openai/v1"
    assert s.ai_model == "llama-3.3-70b-versatile"
    assert s.ai_configured and not s.is_mock


def test_provider_name_is_case_insensitive() -> None:
    assert make_settings(ai_provider=" Groq ", ai_api_key="k").ai_provider == "groq"


def test_leftover_openai_values_are_replaced_for_groq() -> None:
    s = make_settings(ai_provider="groq", ai_api_key="k",
                      ai_base_url="https://api.openai.com/v1", ai_model="gpt-4o-mini")
    assert s.ai_base_url.startswith("https://api.groq.com")
    assert s.ai_model == "llama-3.3-70b-versatile"


def test_explicit_model_and_address_win() -> None:
    s = make_settings(ai_provider="groq", ai_api_key="k", ai_model="openai/gpt-oss-120b",
                      ai_base_url="https://proxy.example/v1")
    assert s.ai_model == "openai/gpt-oss-120b"
    assert s.ai_base_url == "https://proxy.example/v1"


def test_blank_values_fall_back_to_defaults() -> None:
    s = make_settings(ai_provider="openai", ai_api_key="k", ai_base_url="", ai_model=" ")
    assert s.ai_base_url == "https://api.openai.com/v1" and s.ai_model == "gpt-4o-mini"
    a = make_settings(ai_provider="anthropic", ai_api_key="k", ai_base_url="", ai_model="")
    assert a.ai_base_url == "https://api.anthropic.com/v1"


@respx.mock
def test_groq_chat_end_to_end() -> None:
    route = respx.post(GROQ_URL).mock(return_value=_ok("llama-3.3-70b-versatile"))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_test")))
    r = c.post("/api/chat", headers=auth(), json={"message": "hello"})
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "Hi from Groq."
    assert r.json()["provider"] == "groq"
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer gsk_test"
    assert b'"llama-3.3-70b-versatile"' in req.content
    assert c.get("/health").json()["ai_provider"] == "groq"


def test_groq_without_key_is_reported_not_crashing() -> None:
    c = TestClient(create_app(make_settings(ai_provider="groq")))
    assert c.get("/health").json()["ai_configured"] is False
    r = c.post("/api/chat", headers=auth(), json={"message": "hello"})
    assert r.status_code == 503 and "AI_API_KEY" in r.json()["error"]["message"]


def test_unknown_provider_starts_and_explains() -> None:
    c = TestClient(create_app(make_settings(ai_provider="skynet", ai_api_key="k")))
    h = c.get("/health").json()
    assert h["status"] == "ok" and h["ai_configured"] is False
    r = c.post("/api/chat", headers=auth(), json={"message": "hello"})
    assert r.status_code == 503
    msg = r.json()["error"]["message"]
    assert "skynet" in msg and "groq" in msg


@respx.mock
def test_ollama_needs_no_key() -> None:
    route = respx.post("http://localhost:11434/v1/chat/completions").mock(return_value=_ok())
    c = TestClient(create_app(make_settings(ai_provider="ollama")))
    assert c.post("/api/chat", headers=auth(), json={"message": "hi"}).status_code == 200
    assert "Authorization" not in route.calls[0].request.headers


def test_env_var_value_groq_is_accepted(monkeypatch) -> None:
    """The exact failure seen on Render: AI_PROVIDER=groq from the environment."""
    from app.config import Settings

    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("AI_API_KEY", "gsk_x")
    monkeypatch.setenv("AI_BASE_URL", "")
    s = Settings(_env_file=None)
    assert s.ai_provider == "groq" and s.ai_base_url.startswith("https://api.groq.com")
