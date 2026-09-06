"""
AI situation briefing. Feeds the current zone gaps + 30-day trend to Gemini and
asks for a *structured* prioritisation: a narrative plus ranked zones, each with
a reason, a recommended action, the key resources, and a confidence level.
Cached (it re-summarises slow-moving data) and invalidated on a contribution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core.cache import cached
from app.schemas import AiBriefing, BriefingPriority, ResponseTrendPoint, ZoneGap
from app.services.gemini import generate_json
from app.services.insights import response_trend, zone_gaps

log = logging.getLogger("relieftrace.briefing")

_BRIEFING_TTL = 3600

_SYSTEM = (
    "You are a disaster-relief operations analyst. You reason only from the data "
    "the user provides - never invent zones, resources, or numbers. Keep language "
    "concrete and operational."
)

# Gemini responseSchema (a constrained subset of JSON Schema).
_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {
            "type": "string",
            "description": "One short paragraph summarising the overall situation.",
        },
        "priorities": {
            "type": "array",
            "description": "Up to 5 zones needing intervention first, most urgent first.",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "zone": {"type": "string"},
                    "urgency": {"type": "string", "enum": ["critical", "medium", "low"]},
                    "reason": {"type": "string"},
                    "recommended_action": {"type": "string"},
                    "key_resources": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["rank", "zone", "reason", "recommended_action"],
            },
        },
    },
    "required": ["narrative", "priorities"],
}


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
        "Prioritise which zones need urgent intervention first, and why.\n\n"
        f"Response trend summary: {trend_summary}\n\n"
        f"Zone resource gaps (sorted by unmet need, most severe first):\n{gap_lines}\n"
    )


@cached(ttl=_BRIEFING_TTL)
def generate_briefing() -> AiBriefing:
    gaps = zone_gaps()
    trend = response_trend()
    log.info("ai-briefing: calling gemini with %d gap rows", len(gaps))

    data = generate_json(_build_prompt(gaps, trend), schema=_SCHEMA, system=_SYSTEM)

    narrative = str(data.get("narrative", "")).strip()
    priorities: list[BriefingPriority] = []
    for item in data.get("priorities", []) or []:
        try:
            priorities.append(BriefingPriority(**item))
        except Exception as exc:  # noqa: BLE001 - skip a malformed row, keep the rest
            log.warning("ai-briefing: dropping malformed priority %s (%s)", item, exc)

    if not narrative and not priorities:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gemini returned an empty briefing")

    priorities.sort(key=lambda p: p.rank)
    return AiBriefing(
        briefing=narrative,
        priorities=priorities,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
