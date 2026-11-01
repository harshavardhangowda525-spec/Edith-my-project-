from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_health_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mock_mode"] is True
    assert body["ai_configured"] is True


def test_health_never_exposes_secrets() -> None:
    s = make_settings(ai_provider="openai", ai_api_key="sk-supersecretvalue123",
                      supabase_service_role_key="service-role-secret")
    r = TestClient(create_app(s)).get("/health")
    assert r.status_code == 200
    assert "sk-supersecret" not in r.text
    assert "service-role-secret" not in r.text
    assert r.json()["ai_configured"] is True


def test_health_reports_missing_key() -> None:
    s = make_settings(ai_provider="openai", ai_api_key=None)
    r = TestClient(create_app(s)).get("/health")
    assert r.json()["ai_configured"] is False


def test_security_headers(client: TestClient) -> None:
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    ok = client.options("/api/chat", headers={"Origin": "http://localhost:5173",
                                              "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/chat", headers={"Origin": "https://evil.example",
                                               "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_unknown_route_structured_error(client: TestClient) -> None:
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "http_error"
