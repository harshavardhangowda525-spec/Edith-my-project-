"""Server-sent events helper: every event is one `data: {json}` line; errors become an error event."""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi.responses import StreamingResponse

from app.errors import AppError

log = logging.getLogger("edith.sse")


def sse(events: AsyncIterator[dict], first: list[dict] | None = None) -> StreamingResponse:
    async def gen():
        try:
            for ev in first or []:
                yield f"data: {json.dumps(ev)}\n\n"
            async for ev in events:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except AppError as exc:
            yield f"data: {json.dumps({'type': 'error', 'code': exc.code, 'message': exc.message})}\n\n"
        except Exception as exc:  # never leak internals; keep the stream well-formed
            log.exception("stream failed: %s", type(exc).__name__)
            yield f"data: {json.dumps({'type': 'error', 'code': 'internal_error', 'message': 'Something went wrong on the server'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
