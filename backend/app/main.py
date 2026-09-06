"""
ReliefTrace API: read-only insights over disaster-relief requests/deliveries in
Snowflake, a live SSE feed of new contributions, and an AI situation briefing
from Gemini. No accounts, no auth, no payments - this tracks physical aid
(food, water, shelter, medical, clothing) between zones and donor orgs.

Structure:
  app/core      - config, logging, cache, realtime event bus
  app/db        - Snowflake connection pool
  app/services  - query + business logic (insights, contributions, briefing, solana)
  app/api       - FastAPI routers (thin; they call services)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import snowflake.connector
from fastapi import FastAPI, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.deps import limiter
from app.api.router import api_router
from app.core.config import settings
from app.core.events import redis_relay
from app.core.logging import setup_logging
from app.db import prewarm

setup_logging()
log = logging.getLogger("relieftrace")

try:
    import logfire
except Exception:  # pragma: no cover
    logfire = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "ReliefTrace API starting | env=%s | gemini=%s | gemini_key=%s | cors=%s",
        settings.environment,
        settings.gemini_model,
        "set" if settings.gemini_api_key else "MISSING",
        ",".join(settings.frontend_origins),
    )
    # warm the Snowflake pool off the request path
    asyncio.create_task(run_in_threadpool(prewarm))
    # forward contribution events from other replicas into local SSE clients
    relay_task = asyncio.create_task(redis_relay())
    log.info("startup complete | logfire=%s", "on" if settings.logfire_token else "off (no token)")
    try:
        yield
    finally:
        relay_task.cancel()


app = FastAPI(
    title="ReliefTrace API",
    description="Aid you can actually verify.",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

if logfire is not None:
    try:
        logfire.instrument_fastapi(app, capture_headers=False)
    except Exception as exc:  # optional extra missing - not fatal
        log.warning("logfire fastapi instrumentation unavailable: %s", exc)


@app.exception_handler(snowflake.connector.Error)
def snowflake_error_handler(request: Request, exc: snowflake.connector.Error):
    log.error("snowflake error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The database is temporarily unavailable. Please try again shortly."},
    )


app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
