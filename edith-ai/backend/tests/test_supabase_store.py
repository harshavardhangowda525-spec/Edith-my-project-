"""SupabaseStore against a mocked PostgREST: every query must be scoped to the user."""
import httpx
import pytest
import respx

from app.errors import ConfigurationError
from app.services.storage import SupabaseStore

URL = "https://proj.supabase.test"
ROW = {"id": "m1", "user_id": "u1", "content": "hi", "category": "general",
       "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}


def test_requires_credentials() -> None:
    with pytest.raises(ConfigurationError):
        SupabaseStore(URL, None)


@respx.mock
def test_queries_are_scoped_by_user() -> None:
    lst = respx.get(f"{URL}/rest/v1/memories").mock(return_value=httpx.Response(200, json=[ROW]))
    dele = respx.delete(f"{URL}/rest/v1/memories").mock(return_value=httpx.Response(200, json=[]))
    store = SupabaseStore(URL, "service-key")

    assert store.list_memories("u1")[0].content == "hi"
    assert lst.calls[0].request.url.params["user_id"] == "eq.u1"
    assert lst.calls[0].request.headers["apikey"] == "service-key"

    assert store.delete_memory("u2", "m1") is False  # not owned -> nothing deleted
    params = dele.calls[0].request.url.params
    assert params["user_id"] == "eq.u2" and params["id"] == "eq.m1"


@respx.mock
def test_database_errors_are_generic() -> None:
    respx.get(f"{URL}/rest/v1/memories").mock(return_value=httpx.Response(500, text="secret detail"))
    store = SupabaseStore(URL, "service-key")
    with pytest.raises(Exception) as exc:
        store.list_memories("u1")
    assert "secret detail" not in str(exc.value)


@respx.mock
def test_key_header_formats() -> None:
    route = respx.get(f"{URL}/rest/v1/memories").mock(return_value=httpx.Response(200, json=[]))
    SupabaseStore(URL, "eyJhbGciOi.legacy.jwt").list_memories("u1")
    SupabaseStore(URL, "sb_secret_abc123").list_memories("u1")
    legacy, new = route.calls[0].request.headers, route.calls[1].request.headers
    assert legacy["Authorization"] == "Bearer eyJhbGciOi.legacy.jwt"
    assert new["apikey"] == "sb_secret_abc123" and "Authorization" not in new


def test_url_normalisation() -> None:
    from app.services.storage import normalize_supabase_url as n
    want = "https://abcd1234.supabase.co"
    for pasted in [want, want + "/", want + "/rest/v1", want + "/rest/v1/", "abcd1234.supabase.co",
                   " " + want + "\n", "https://supabase.com/dashboard/project/abcd1234",
                   "https://supabase.com/dashboard/project/abcd1234/settings/api"]:
        assert n(pasted) == want, pasted
    assert n("https://db.example.com/") == "https://db.example.com"


@respx.mock
def test_missing_tables_message() -> None:
    respx.get(f"{URL}/rest/v1/profiles").mock(return_value=httpx.Response(404, json={
        "code": "PGRST205", "message": "Could not find the table 'public.profiles' in the schema cache"}))
    with pytest.raises(Exception) as exc:
        SupabaseStore(URL, "k").get_memory_enabled("u1")
    assert "schema.sql" in str(exc.value)


@respx.mock
def test_wrong_url_message() -> None:
    respx.get(f"{URL}/rest/v1/profiles").mock(return_value=httpx.Response(404, text="<html>Not found</html>"))
    with pytest.raises(Exception) as exc:
        SupabaseStore(URL, "k").get_memory_enabled("u1")
    assert "SUPABASE_URL" in str(exc.value)


@respx.mock
def test_bad_key_and_unknown_owner_messages() -> None:
    respx.get(f"{URL}/rest/v1/memories").mock(return_value=httpx.Response(401, json={"message": "Invalid API key"}))
    respx.post(f"{URL}/rest/v1/memories").mock(return_value=httpx.Response(409, json={
        "code": "23503", "message": "insert or update violates foreign key constraint"}))
    s = SupabaseStore(URL, "k")
    with pytest.raises(Exception) as e1:
        s.list_memories("u1")
    assert "SUPABASE_SERVICE_ROLE_KEY" in str(e1.value) and "k" != str(e1.value)
    with pytest.raises(Exception) as e2:
        s.create_memory("u1", "hi", "general")
    assert "OWNER_USER_ID" in str(e2.value)


@respx.mock
def test_tasks_are_upserted_and_scoped() -> None:
    up = respx.post(f"{URL}/rest/v1/tasks").mock(return_value=httpx.Response(201))
    get = respx.get(f"{URL}/rest/v1/tasks").mock(return_value=httpx.Response(200, json=[]))
    store = SupabaseStore(URL, "service-key")
    store.save_task("u1", {"id": "t1", "user_id": "u1", "type": "research", "title": "x", "params": {"q": 1},
                           "status": "running", "secret_extra": "dropped"})
    req = up.calls[0].request
    assert req.url.params["on_conflict"] == "id" and "merge-duplicates" in req.headers["Prefer"]
    body = __import__("json").loads(req.content)
    assert body["status"] == "running" and "secret_extra" not in body
    assert store.get_task("u2", "t1") is None
    assert get.calls[0].request.url.params["user_id"] == "eq.u2"
