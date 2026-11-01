from __future__ import annotations

import os

# Make sure a developer's local .env can never leak into tests.
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("STORAGE_BACKEND", "memory")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ALICE = "alice-token"
BOB = "bob-token"
ALICE_ID = "00000000-0000-0000-0000-00000000000a"
BOB_ID = "00000000-0000-0000-0000-00000000000b"


def make_settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        environment="test",
        ai_provider="mock",
        auth_mode="local",
        storage_backend="memory",
        local_access_tokens=f"{ALICE}:{ALICE_ID},{BOB}:{BOB_ID}",
        rate_limit_per_minute=1000,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def auth(token: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
