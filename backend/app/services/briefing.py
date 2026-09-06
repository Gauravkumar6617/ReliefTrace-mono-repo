"""
AI situation briefing. Sends the current zone gaps + response-trend summary to
Gemini and asks it to prioritise zones. The result is cached (it re-summarises
the same slow-moving data on every call) and invalidated when a contribution
lands.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, status

from app.core.cache import cached
from app.core.config import settings
from app.schemas import AiBriefing, ResponseTrendPoint, ZoneGap
from app.services.insights import response_trend, zone_gaps

log = logging.getLogger("relieftrace.briefing")

_BRIEFING_TTL = 3600


def _build_prompt(gaps: list[ZoneGap], trend: list[ResponseTrendPoint]) -> str:
    gap_lines = "\n".join(
        f"- {g.zone_name} / {g.resource_type}: needed {g.quantity_needed:.0f}, "
        f"fulfilled {g.quantity_fulfilled:.0f}, unmet {g.unmet_need:.0f}, urgency={g.urgency_level}"
        for g in gaps[:30]
    )
    trend_summary = (
        f"{len(trend)} days of data; "
        f"total requested {sum(t.quantity_requested for t in trend):.0f}, "
        f"total delivered {sum(t.quantity_delivered for t in trend):.0f}."
    )
    return (
        "You are a disaster relief operations analyst. Given the following zone-level "
        "resource gaps and a summary of the 30-day response trend, identify which zones "
        "need urgent intervention first and why. Be specific about zone names and resource "
        "types, and keep the reasoning brief (a short paragraph plus a prioritized bullet "
        "list of at most 5 zones). Do not invent data not present below.\n\n"
        f"Response trend summary: {trend_summary}\n\n"
        f"Zone resource gaps (sorted by unmet need, most severe first):\n{gap_lines}\n"
    )


@cached(ttl=_BRIEFING_TTL)
def generate_briefing() -> AiBriefing:
    if not settings.gemini_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GEMINI_API_KEY is not configured")

    gaps = zone_gaps()
    trend = response_trend()
    prompt = _build_prompt(gaps, trend)
    log.info("ai-briefing: calling %s with %d gap rows", settings.gemini_model, len(gaps))

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    try:
        resp = httpx.post(
            url,
            params={"key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except httpx.HTTPStatusError as exc:
        log.error("ai-briefing: Gemini HTTP %s: %s", exc.response.status_code, exc.response.text[:300])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gemini API error: {exc.response.text}")
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        log.error("ai-briefing: Gemini call failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gemini API call failed: {exc}")

    log.info("ai-briefing: ok (%d chars)", len(text))
    return AiBriefing(briefing=text, generated_at=datetime.now(timezone.utc).isoformat())
