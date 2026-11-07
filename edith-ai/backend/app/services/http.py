"""One persistent, pooled HTTP client per event loop.

Re-using connections to the AI/speech providers skips a TCP + TLS handshake on every request
(typically 100-300 ms each over the internet). Timeouts are set per request by callers.
"""
from __future__ import annotations

import asyncio
import weakref

import httpx

_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()


def shared_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=120),
        )
        _clients[loop] = client
    return client


async def close_shared() -> None:
    loop = asyncio.get_running_loop()
    client = _clients.pop(loop, None)
    if client is not None:
        await client.aclose()
