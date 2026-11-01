"""Authentication for private endpoints.

Two modes:

* ``supabase`` - verifies the Supabase access token the frontend obtained via
  Supabase Auth. HS256 tokens are verified with ``SUPABASE_JWT_SECRET``; projects
  using asymmetric signing keys are verified against the project's JWKS.
* ``local``    - development only. Static bearer tokens mapped to user ids via
  ``LOCAL_ACCESS_TOKENS``. Refused when ``ENVIRONMENT=production``.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from functools import lru_cache

import jwt

from app.config import Settings
from app.errors import AuthError, ConfigurationError


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def _verify_supabase(token: str, settings: Settings) -> AuthenticatedUser:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("Malformed access token") from exc

    alg = header.get("alg", "")
    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise ConfigurationError("SUPABASE_JWT_SECRET is not configured on the server")
            claims = jwt.decode(
                token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
            )
        elif alg in {"RS256", "ES256"}:
            if not settings.supabase_url:
                raise ConfigurationError("SUPABASE_URL is not configured on the server")
            jwks_url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
            key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=[alg], audience="authenticated")
        else:
            raise AuthError("Unsupported token algorithm")
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Access token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid access token") from exc

    sub = claims.get("sub")
    if not sub:
        raise AuthError("Token has no subject")
    return AuthenticatedUser(id=str(sub), email=claims.get("email"))


def _verify_local(token: str, settings: Settings) -> AuthenticatedUser:
    if settings.environment == "production":
        raise ConfigurationError("Local token auth is disabled in production; use AUTH_MODE=supabase")
    for known, user_id in settings.local_token_map.items():
        if hmac.compare_digest(known.encode(), token.encode()):
            return AuthenticatedUser(id=user_id)
    raise AuthError("Invalid access token")


def authenticate(authorization: str | None, settings: Settings) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise AuthError("Missing bearer token")
    if settings.auth_mode == "supabase":
        return _verify_supabase(token, settings)
    return _verify_local(token, settings)
