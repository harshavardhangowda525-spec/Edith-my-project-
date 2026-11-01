from fastapi.testclient import TestClient

from app.services.retrieval_service import chunk_text
from tests.conftest import ALICE_ID, BOB, auth


def test_memory_crud(client: TestClient) -> None:
    r = client.post("/api/memory", headers=auth(), json={"content": "Prefers metric units", "category": "preference"})
    assert r.status_code == 201
    m = r.json()
    assert m["user_id"] == ALICE_ID

    listed = client.get("/api/memory", headers=auth()).json()
    assert [x["id"] for x in listed] == [m["id"]]

    u = client.patch(f"/api/memory/{m['id']}", headers=auth(), json={"content": "Prefers SI units"})
    assert u.status_code == 200 and u.json()["content"] == "Prefers SI units"

    assert client.delete(f"/api/memory/{m['id']}", headers=auth()).status_code == 204
    assert client.get("/api/memory", headers=auth()).json() == []


def test_memory_requires_auth(client: TestClient) -> None:
    assert client.get("/api/memory").status_code == 401
    assert client.post("/api/memory", json={"content": "x"}).status_code == 401
    assert client.delete("/api/memory/abc").status_code == 401


def test_memory_ownership_isolation(client: TestClient) -> None:
    mid = client.post("/api/memory", headers=auth(), json={"content": "Alice private fact"}).json()["id"]

    # Bob cannot see, edit or delete Alice's memory.
    assert client.get("/api/memory", headers=auth(BOB)).json() == []
    assert client.patch(f"/api/memory/{mid}", headers=auth(BOB), json={"content": "hacked"}).status_code == 404
    assert client.delete(f"/api/memory/{mid}", headers=auth(BOB)).status_code == 404

    # Still intact for Alice.
    items = client.get("/api/memory", headers=auth()).json()
    assert items[0]["content"] == "Alice private fact"


def test_delete_missing_memory(client: TestClient) -> None:
    r = client.delete("/api/memory/does-not-exist", headers=auth())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_memory_validation(client: TestClient) -> None:
    assert client.post("/api/memory", headers=auth(), json={"content": "  "}).status_code == 422
    assert client.post("/api/memory", headers=auth(), json={"content": "x" * 1001}).status_code == 422


def test_disable_persistent_memory(client: TestClient) -> None:
    client.post("/api/memory", headers=auth(), json={"content": "Favourite colour is blue"})
    r = client.put("/api/memory/settings", headers=auth(), json={"memory_enabled": False})
    assert r.json() == {"memory_enabled": False}

    blocked = client.post("/api/memory", headers=auth(), json={"content": "new"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "memory_disabled"

    chat = client.post("/api/chat", headers=auth(), json={"message": "colour?"})
    assert chat.json()["memories_used"] == 0

    # Other users unaffected
    assert client.get("/api/memory/settings", headers=auth(BOB)).json() == {"memory_enabled": True}


def test_chat_never_auto_stores_memory(client: TestClient) -> None:
    client.post("/api/chat", headers=auth(), json={"message": "My bank PIN is 9999"})
    assert client.get("/api/memory", headers=auth()).json() == []


def test_document_ownership(client: TestClient) -> None:
    d = client.post("/api/documents", headers=auth(), json={"title": "Notes", "content": "hello world"}).json()
    assert client.get("/api/documents", headers=auth(BOB)).json() == []
    assert client.delete(f"/api/documents/{d['id']}", headers=auth(BOB)).status_code == 404
    assert client.delete(f"/api/documents/{d['id']}", headers=auth()).status_code == 204


def test_chunking() -> None:
    text = ("Sentence number one. " * 200).strip()
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= 900 for c in chunks)
    assert chunk_text("short") == ["short"]
    assert chunk_text("   ") == []


def test_profile_memories_always_first(client: TestClient) -> None:
    client.post("/api/memory", headers=auth(), json={"content": "I'm Harsha, founder of a web agency", "category": "profile"})
    for i in range(20):
        client.post("/api/memory", headers=auth(), json={"content": f"fact {i}"})
    svc = client.app.state.memory
    lines = svc.for_prompt(ALICE_ID)
    assert lines[0] == "About the user: I'm Harsha, founder of a web agency"
    assert len(lines) == 15
