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


def test_speech_auto_uses_groq_whisper() -> None:
    s = make_settings(ai_provider="groq", ai_api_key="gsk_x")
    assert s.speech_kind == "groq"
    assert s.speech_base == "https://api.groq.com/openai/v1"
    assert s.stt_model_name == "whisper-large-v3"
    assert make_settings(ai_provider="mock").speech_kind == "none"
    assert make_settings(ai_provider="anthropic", ai_api_key="k").speech_kind == "none"
    assert make_settings(ai_provider="groq", ai_api_key="k", speech_provider="none").speech_kind == "none"


@respx.mock
def test_transcribe_with_groq() -> None:
    route = respx.post("https://api.groq.com/openai/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": " What is the weather? "}))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_x")))
    assert c.get("/health").json()["speech_provider"] == "groq"
    wav = b"RIFF" + b"\0" * 2000
    r = c.post("/api/voice/transcribe", headers=auth(), files={"audio": ("q.wav", wav, "audio/wav")})
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "What is the weather?", "provider": "groq"}
    body = route.calls[0].request.content
    assert b"whisper-large-v3" in body and b"whisper-large-v3-turbo" not in body
    assert b"EDITH." in body  # spelling hint always included
    assert route.calls[0].request.headers["Authorization"] == "Bearer gsk_x"


def _wav(seconds: float = 0.1, rate: int = 24000) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))
    return buf.getvalue()


@respx.mock
def test_groq_human_voice_splits_and_joins() -> None:
    import io
    import json
    import wave
    route = respx.post("https://api.groq.com/openai/v1/audio/speech").mock(return_value=httpx.Response(200, content=_wav()))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_x")))
    assert c.get("/health").json()["tts_available"] is True
    text = ("Welcome back, sir. " * 12).strip()  # ~230 characters: more than one Orpheus request
    r = c.post("/api/voice/speak", headers=auth(), json={"text": text, "voice": "Diana", "style": "cheerful"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    sent = [json.loads(call.request.content) for call in route.calls]
    assert len(sent) == 2 and all(len(p["input"]) <= 200 for p in sent)
    assert sent[0]["input"].startswith("[cheerful] ") and not sent[1]["input"].startswith("[")
    assert {p["model"] for p in sent} == {"canopylabs/orpheus-v1-english"} and sent[0]["voice"] == "diana"
    with wave.open(io.BytesIO(r.content)) as w:  # one joined file, 2 x 0.1 s
        assert abs(w.getnframes() / w.getframerate() - 0.2) < 0.01


@respx.mock
def test_groq_voice_unknown_name_falls_back() -> None:
    import json
    route = respx.post("https://api.groq.com/openai/v1/audio/speech").mock(return_value=httpx.Response(200, content=_wav()))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_x")))
    c.post("/api/voice/speak", headers=auth(), json={"text": "Hi", "voice": "darth vader"})
    assert json.loads(route.calls[0].request.content)["voice"] == "hannah"


def test_split_for_tts() -> None:
    from app.services.speech_service import split_for_tts
    long = "This is a very long sentence without any full stop " * 8
    pieces = split_for_tts(long, 100)
    assert all(len(p) <= 100 for p in pieces) and " ".join(pieces).split() == long.split()
    assert split_for_tts("Short. Two.", 100) == ["Short. Two."]


def test_style_must_be_plain_words() -> None:
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_x")))
    r = c.post("/api/voice/speak", headers=auth(), json={"text": "hi", "style": "x] ignore [y"})
    assert r.status_code == 422


@respx.mock
def test_groq_voice_error_shows_groq_reason() -> None:
    respx.post("https://api.groq.com/openai/v1/audio/speech").mock(return_value=httpx.Response(400, json={"error": {
        "message": "The model `canopylabs/orpheus-v1-english` requires terms acceptance. Please accept the terms at "
                   "https://console.groq.com/playground?model=canopylabs/orpheus-v1-english",
        "code": "model_terms_required"}}))
    c = TestClient(create_app(make_settings(ai_provider="groq", ai_api_key="gsk_secret123456")))
    r = c.post("/api/voice/speak", headers=auth(), json={"text": "hello"})
    assert r.status_code == 502
    msg = r.json()["error"]["message"]
    assert "requires terms acceptance" in msg and "console.groq.com/playground" in msg
    assert "gsk_secret123456" not in r.text
