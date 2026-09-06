"""
"Ask ReliefTrace" - a natural-language question answered by Gemini using
*function calling* over the live Snowflake data. Gemini decides which of the
tools below to call; we run the real queries and feed results back until it
produces an answer. The endpoint also returns which tools were used, so the UI
can show the reasoning trace.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.cache import cached
from app.schemas import AskResult
from app.services import insights
from app.services.gemini import generate_with_tools

log = logging.getLogger("relieftrace.ask")

_ASK_TTL = 300  # identical questions within 5 min reuse the answer

_FALLBACK = "I couldn't find relevant data for that question."

_SYSTEM = (
    "You are ReliefTrace's data assistant. Answer questions about disaster-relief "
    "resource needs and deliveries strictly from the tools provided - call whichever "
    "tools you need, then answer in 1-4 sentences with concrete zone names, resource "
    "types and numbers. Never invent data. All quantities are in generic 'units'. "
    "If the question is unrelated to relief needs or deliveries, or the tool results "
    f"do not contain the answer, reply exactly: {_FALLBACK}"
)

# --- tool implementations (return compact JSON-friendly structures) ----------


def _zone_gaps(limit: int = 25) -> list[dict]:
    return [
        {
            "zone": g.zone_name,
            "resource": g.resource_type,
            "needed": round(g.quantity_needed),
            "fulfilled": round(g.quantity_fulfilled),
            "unmet": round(g.unmet_need),
            "urgency": g.urgency_level,
        }
        for g in insights.zone_gaps()[: max(1, min(limit, 100))]
    ]


def _resource_breakdown() -> list[dict]:
    return [
        {
            "resource": r.resource_type,
            "needed": round(r.total_needed),
            "fulfilled": round(r.total_fulfilled),
            "unmet": round(r.unmet_need),
        }
        for r in insights.resource_breakdown()
    ]


def _response_trend(last_n_days: int = 30) -> list[dict]:
    rows = insights.response_trend()[-max(1, min(last_n_days, 90)):]
    return [
        {
            "day": str(t.day),
            "requests": t.requests_count,
            "requested": round(t.quantity_requested),
            "deliveries": t.deliveries_count,
            "delivered": round(t.quantity_delivered),
        }
        for t in rows
    ]


def _recent_deliveries(limit: int = 15) -> list[dict]:
    return [
        {
            "zone": d.zone_name,
            "donor": d.donor_org,
            "resource": d.resource_type,
            "quantity": round(d.quantity_sent),
            "date": str(d.delivery_date),
            "verified": bool(d.solana_tx_sig),
        }
        for d in insights.recent_deliveries(max(1, min(limit, 50)))
    ]


_IMPLS = {
    "get_zone_gaps": _zone_gaps,
    "get_resource_breakdown": _resource_breakdown,
    "get_response_trend": _response_trend,
    "get_recent_deliveries": _recent_deliveries,
}

_TOOLS = [
    {
        "name": "get_zone_gaps",
        "description": "Per-zone, per-resource unmet need (needed minus fulfilled) with urgency, worst first.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "max rows, default 25"}},
        },
    },
    {
        "name": "get_resource_breakdown",
        "description": "Totals of needed vs fulfilled vs unmet for each resource type (Food, Water, Shelter, Medical, Clothing).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_response_trend",
        "description": "Daily counts and quantities of requests raised vs resource units delivered.",
        "parameters": {
            "type": "object",
            "properties": {"last_n_days": {"type": "integer", "description": "window size, default 30"}},
        },
    },
    {
        "name": "get_recent_deliveries",
        "description": "The most recent relief deliveries: zone, donor, resource, quantity, date, and whether anchored on-chain.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "max rows, default 15"}},
        },
    },
]


@cached(ttl=_ASK_TTL)
def answer_question(question: str) -> AskResult:
    log.info("ask: %r", question[:120])
    answer, tools_used = generate_with_tools(
        question, system=_SYSTEM, tools=_TOOLS, impls=_IMPLS
    )
    answer = answer.strip() or _FALLBACK
    log.info("ask: answered using tools=%s", tools_used)
    return AskResult(
        question=question,
        answer=answer,
        tools_used=tools_used,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
