"""
Lightweight API-key auth for the mutating / paid endpoints.

A single shared secret (``API_KEY``) sent in the ``X-API-Key`` header. Declaring
:data:`api_key_header` as a dependency is what makes Swagger render the padlock
and the "Authorize" button.

If ``API_KEY`` is unset the dependency is a no-op, so local development and a
contest reviewer poking at ``/docs`` aren't blocked.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided: str | None = Depends(api_key_header)) -> None:
    if not settings.api_key:
        return  # auth disabled
    if not provided or not secrets.compare_digest(provided, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key (send it in the X-API-Key header).",
        )
