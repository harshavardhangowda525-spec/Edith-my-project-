"""EDITH AI backend entrypoint.

Run locally:  python -m uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import bridge, chat, documents, email, health, leads, meeting, memory, tasks, voice
from app.config import Settings, get_settings
from app.errors import AppError
from app.security.authentication import personal_mode_problem
from app.security.rate_limit import RateLimiter
from app.services.ai_service import AIService
from app.services.http import close_shared
from app.services.metrics import Metrics
from app.services.bridge import BridgeHub
from app.services.email_service import EmailService
from app.services.github_service import GitHubService
from app.services.task_handlers import register_handlers
from app.services.tasks import TaskEngine
from app.services.leads_service import LeadsService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService
from app.services.speech_service import SpeechService
from app.services.storage import InMemoryStore, Store, SupabaseStore

log = logging.getLogger("edith")


class RedactSecretsFilter(logging.Filter):
    """Belt-and-braces: scrub anything that looks like a credential from log lines."""

    PATTERNS = [
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
        re.compile(r"(sk-[A-Za-z0-9_\-]{8})[A-Za-z0-9_\-]+"),
        re.compile(r"(eyJ[A-Za-z0-9_\-]{6})[A-Za-z0-9._\-]+"),
        re.compile(r"(?i)((?:api[_-]?key|x-api-key|apikey)[\"'=:\s]+)[^\s,\"']+"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in self.PATTERNS:
            msg = p.sub(r"\1[REDACTED]", msg)
        record.msg, record.args = msg, ()
        return True


class JsonFormatter(logging.Formatter):
    """LOG_FORMAT=json: one JSON object per line (ts, level, logger, msg) for log search tools."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        out = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage()}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


class BodySizeLimitMiddleware:
    """Reject bodies larger than the limit, including chunked uploads without Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int, audio_max_bytes: int) -> None:
        self.app, self.max_bytes, self.audio_max = app, max_bytes, audio_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.audio_max + 64 * 1024 if scope["path"].endswith(("/transcribe", "/voice/ask")) else self.max_bytes
        headers = dict(scope.get("headers") or [])
        cl = headers.get(b"content-length")
        if cl is not None:
            try:
                too_big = int(cl) > limit
            except ValueError:
                too_big = True
            if too_big:
                await _send_json(send, 413, "payload_too_large", "Request body is too large")
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _send_json(send, 413, "payload_too_large", "Request body is too large")


class _BodyTooLarge(Exception):
    pass


async def _send_json(send: Send, status: int, code: str, message: str) -> None:
    import json

    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}},
                        headers=headers)


def build_store(settings: Settings) -> Store:
    if settings.storage_backend == "supabase":
        return SupabaseStore(settings.supabase_url, settings.supabase_service_role_key)
    return InMemoryStore()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.log_format == "json":
        for h in logging.getLogger().handlers:
            h.setFormatter(JsonFormatter())
    for h in logging.getLogger().handlers:
        h.addFilter(RedactSecretsFilter())

    is_prod = settings.environment == "production"
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.tasks.start()  # also re-queues tasks left unfinished by a restart (Supabase storage)
        yield
        await _app.state.tasks.shutdown()
        await close_shared()  # close pooled provider connections on shutdown

    app = FastAPI(title="EDITH AI", version="1.1.0", lifespan=lifespan,
                  docs_url=None if is_prod else "/docs", redoc_url=None,
                  openapi_url=None if is_prod else "/openapi.json")

    store = build_store(settings)
    app.state.settings = settings
    app.state.store = store
    app.state.metrics = Metrics()
    app.state.ai = AIService(settings, metrics=app.state.metrics)
    app.state.speech = SpeechService(settings)
    app.state.memory = MemoryService(store)
    app.state.retrieval = RetrievalService(store)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.leads = LeadsService(settings)
    app.state.email = EmailService(settings)
    app.state.github = GitHubService(settings)
    app.state.bridge = BridgeHub()
    app.state.tasks = TaskEngine(store, workers=settings.task_workers)
    register_handlers(app.state.tasks, ai=app.state.ai, memory=app.state.memory, store=store,
                      github=app.state.github, bridge=app.state.bridge,
                      bridge_timeout_s=settings.bridge_job_timeout_s)

    if settings.ai_provider_problem:
        log.error("AI provider misconfigured: %s", settings.ai_provider_problem)
    if settings.is_mock:
        log.warning("AI_PROVIDER=mock - responses are canned and NOT from a real AI model")
    if settings.auth_mode == "personal" and (problem := personal_mode_problem(settings)):
        log.error("AUTH_MODE=personal misconfigured: %s", problem)
    if settings.auth_mode == "local" and not settings.local_token_map:
        log.warning("AUTH_MODE=local but LOCAL_ACCESS_TOKENS is empty - private endpoints will reject all requests")

    # --- middleware (last added runs first) ---
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes,
                       audio_max_bytes=settings.max_audio_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # explicit list - never "*" with credentials
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        t0 = time.perf_counter()
        response = await call_next(request)
        # Time to response headers (for streams: until the first event is ready).
        route = request.scope.get("route")
        app.state.metrics.observe(f"http_ms.{getattr(route, 'path', 'other')}", (time.perf_counter() - t0) * 1000)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
        if is_prod:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    # --- error handling ---
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            log.warning("%s: %s", exc.code, exc.message)
        headers = {"Retry-After": str(exc.retry_after)} if hasattr(exc, "retry_after") else None
        if exc.status_code == 401:
            headers = {**(headers or {}), "WWW-Authenticate": "Bearer"}
        return _error(exc.status_code, exc.code, exc.message, headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = f"{loc}: {first.get('msg', 'invalid value')}" if loc else first.get("msg", "Invalid request")
        return _error(422, "invalid_request", msg)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error: %s", type(exc).__name__)
        return _error(500, "internal_error", "Something went wrong on the server")

    for r in (health.router, chat.router, voice.router, memory.router, documents.router, meeting.router,
              leads.router, email.router, tasks.router, bridge.router):
        app.include_router(r)

    # Serve the built React app from the same origin (single-container deployment).
    # Mounted last so every API route above takes precedence.
    if settings.static_dir:
        static = Path(settings.static_dir)
        if (static / "index.html").is_file():
            app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
            log.info("Serving frontend from %s", static)
        else:
            log.warning("STATIC_DIR=%s has no index.html - frontend not served", static)

    return app


app = create_app()
