"""Personal (single-owner) auth mode and single-container static serving."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import auth, make_settings

OWNER = "a-very-long-random-owner-password-123456"
OWNER_ID = "11111111-2222-3333-4444-555555555555"


def personal(**kw):
    return make_settings(auth_mode="personal", environment="production",
                         owner_access_token=OWNER, owner_user_id=OWNER_ID, **kw)


def test_personal_mode_accepts_owner_password_in_production() -> None:
    c = TestClient(create_app(personal()))
    r = c.post("/api/memory", headers=auth(OWNER), json={"content": "I live in Bengaluru"})
    assert r.status_code == 201
    assert r.json()["user_id"] == OWNER_ID
    assert c.post("/api/chat", headers=auth(OWNER), json={"message": "hi"}).status_code == 200


def test_personal_mode_rejects_wrong_or_missing_password() -> None:
    c = TestClient(create_app(personal()))
    r = c.get("/api/memory", headers=auth("a-very-long-random-owner-password-WRONG!"))
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Wrong EDITH password"
    assert c.get("/api/memory").status_code == 401


def test_personal_mode_refuses_short_password() -> None:
    c = TestClient(create_app(personal().model_copy(update={"owner_access_token": "short"})))
    r = c.get("/api/memory", headers=auth("short"))
    assert r.status_code == 503
    assert "OWNER_ACCESS_TOKEN" in r.json()["error"]["message"]


def test_personal_mode_with_supabase_requires_uuid_owner() -> None:
    s = personal().model_copy(update={"storage_backend": "supabase", "owner_user_id": "harsha",
                                      "supabase_url": "https://x.supabase.co",
                                      "supabase_service_role_key": "k"})
    c = TestClient(create_app(s))
    r = c.get("/api/memory", headers=auth(OWNER))
    assert r.status_code == 503
    assert "OWNER_USER_ID" in r.json()["error"]["message"]


def test_production_hides_api_docs_and_sends_hsts() -> None:
    c = TestClient(create_app(personal()))
    assert c.get("/docs").status_code == 404
    h = c.get("/health").headers
    assert "Strict-Transport-Security" in h
    assert "microphone=(self)" in h["Permissions-Policy"]


def test_serves_frontend_and_keeps_api_routes(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>EDITH UI</html>")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    c = TestClient(create_app(personal(static_dir=str(tmp_path))))
    assert "EDITH UI" in c.get("/").text
    assert c.get("/manifest.webmanifest").status_code == 200
    assert c.get("/health").json()["status"] == "ok"
    assert c.get("/api/memory").status_code == 401  # API still protected


def test_missing_static_dir_is_ignored(tmp_path: Path) -> None:
    c = TestClient(create_app(personal(static_dir=str(tmp_path / "nope"))))
    assert c.get("/health").status_code == 200
