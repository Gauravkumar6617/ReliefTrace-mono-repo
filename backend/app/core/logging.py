"""Logging + optional Logfire tracing. Call :func:`setup_logging` once at import
time of the app package."""

import logging

import logfire

from app.core.config import settings

log = logging.getLogger("relieftrace")

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )

    logfire.configure(
        service_name="relieftrace-api",
        send_to_logfire="if-token-present",
        console=False,
    )
    try:
        logfire.instrument_httpx()  # traces the outbound Gemini call
    except Exception as exc:  # optional extra missing - not fatal
        log.warning("logfire httpx instrumentation unavailable: %s", exc)
