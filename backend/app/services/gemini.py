"""
Thin client for the Gemini `generateContent` REST API.

Three call styles used by ReliefTrace:
  - :func:`generate_text`      - plain prompt -> text (legacy briefing fallback);
  - :func:`generate_json`      - prompt + response schema -> parsed dict
                                 (the structured situation briefing);
  - :func:`generate_with_tools`- function-calling loop over caller-supplied
                                 Python tools (the "Ask ReliefTrace" endpoint).

Every entry point raises ``HTTPException(503)`` when ``GEMINI_API_KEY`` is unset
and ``HTTPException(502)`` on an API/parse failure, matching the rest of the API.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

log = logging.getLogger("relieftrace.gemini")

_TIMEOUT = 30.0
_MAX_TOOL_TURNS = 6


def _endpoint() -> str:
    if not settings.gemini_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GEMINI_API_KEY is not configured")
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )


def _post(payload: dict) -> dict:
    url = _endpoint()
    try:
        resp = httpx.post(url, params={"key": settings.gemini_api_key}, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        log.error("gemini HTTP %s: %s", exc.response.status_code, exc.response.text[:300])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gemini API error: {exc.response.text}")
    except httpx.HTTPError as exc:
        log.error("gemini call failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gemini API call failed: {exc}")


def _parts(data: dict) -> list[dict]:
    try:
        return data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        log.error("gemini: unexpected response shape: %s", str(data)[:300])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gemini returned no content: {exc}")


def _text(data: dict) -> str:
    return "".join(p.get("text", "") for p in _parts(data)).strip()


def generate_text(prompt: str, *, system: str | None = None) -> str:
    payload: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}
    return _text(_post(payload))


def generate_json(prompt: str, *, schema: dict, system: str | None = None) -> dict:
    """Prompt Gemini with a response schema and return the parsed JSON object."""
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema},
    }
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}
    raw = _text(_post(payload))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("gemini: JSON parse failed: %s | raw=%s", exc, raw[:300])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gemini returned malformed JSON")


Tool = dict  # a Gemini function_declaration
ToolImpl = Callable[..., Any]


def generate_with_tools(
    question: str,
    *,
    system: str,
    tools: list[Tool],
    impls: dict[str, ToolImpl],
) -> tuple[str, list[str]]:
    """
    Run the function-calling loop: Gemini may call the supplied tools (by name in
    ``impls``); we execute them and feed results back until it produces a final
    text answer. Returns ``(answer, tool_names_called_in_order)``.
    """
    contents: list[dict] = [{"role": "user", "parts": [{"text": question}]}]
    called: list[str] = []

    for _turn in range(_MAX_TOOL_TURNS):
        data = _post(
            {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": contents,
                "tools": [{"function_declarations": tools}],
            }
        )
        parts = _parts(data)
        calls = [p["functionCall"] for p in parts if "functionCall" in p]

        if not calls:
            return _text(data), called

        # record the model's turn, then answer every requested call
        contents.append({"role": "model", "parts": parts})
        response_parts = []
        for call in calls:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            impl = impls.get(name)
            called.append(name)
            if impl is None:
                result: Any = {"error": f"unknown tool {name!r}"}
            else:
                try:
                    result = impl(**args)
                except Exception as exc:  # noqa: BLE001 - surface to the model, not a 500
                    log.warning("tool %s failed: %s", name, exc)
                    result = {"error": str(exc)}
            response_parts.append(
                {"functionResponse": {"name": name, "response": {"result": result}}}
            )
        contents.append({"role": "user", "parts": response_parts})

    # Tool budget exhausted - make one last call with no tools so the model is
    # forced to answer in text rather than loop (or us raising a 502).
    log.warning("gemini: tool budget exhausted after %d turns; forcing a text answer", _MAX_TOOL_TURNS)
    final = _post(
        {"system_instruction": {"parts": [{"text": system}]}, "contents": contents}
    )
    return _text(final), called
