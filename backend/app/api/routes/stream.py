"""
Server-Sent Events stream for the live dashboard.

Clients open ``GET /api/stream`` with an ``EventSource``. They receive:
  - ``event: ready`` once on connect;
  - ``event: message`` with a JSON body for every contribution (from any
    replica, fanned out via Redis pub/sub - see app.core.events);
  - a ``: ping`` comment every 20s so proxies and load balancers don't drop
    the idle connection.

EventSource reconnects on its own if the connection drops.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.events import broadcaster

router = APIRouter(prefix="/api", tags=["stream"])

_PING_INTERVAL_S = 20.0


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    queue = await broadcaster.register()

    async def event_source():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_PING_INTERVAL_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"event: message\ndata: {payload}\n\n"
        finally:
            await broadcaster.unregister(queue)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering
        },
    )
