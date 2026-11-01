"""Structured application errors.

Every error leaves the API as ``{"error": {"code": ..., "message": ...}}`` so the
frontend can show a useful message without ever receiving stack traces or secrets.
"""
from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConfigurationError(AppError):
    """A required credential or setting is missing."""

    status_code = 503
    code = "not_configured"


class ProviderError(AppError):
    """The upstream AI / speech provider failed."""

    status_code = 502
    code = "provider_error"


class ProviderTimeout(ProviderError):
    status_code = 504
    code = "provider_timeout"


class ValidationFailed(AppError):
    status_code = 422
    code = "invalid_request"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
