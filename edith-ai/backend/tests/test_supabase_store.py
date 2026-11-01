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
