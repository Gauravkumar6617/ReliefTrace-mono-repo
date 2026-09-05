"""
ReliefTrace API: read-only insights over disaster relief requests/deliveries
tracked in Snowflake, plus an AI situation briefing generated from that data
via Gemini. No accounts, no auth, no payments - this tracks physical aid
(food, water, shelter, medical supplies, clothing) between zones and donor
orgs, not money.

TODO(me, before this touches a real disaster response):
  - swap the per-request Snowflake connection in db.py for a pooled
    connection (or async client) so this doesn't fall over under load.
  - move rate-limit state (slowapi's in-memory store below) to Redis once
    this runs behind more than one process/instance.
  - cache the AI briefing (it's re-summarizing the same data on every call)
    and structured logging / request tracing.
"""

import logging
import os
import uuid
from datetime import date, datetime, timezone

import httpx
import logfire
import snowflake.connector
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# --- logging -------------------------------------------------------------------
# Plain stdout logging always; Logfire tracing only when LOGFIRE_TOKEN is set
# (locally: `logfire auth`; on a host: set the token env var). No token -> no-op.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("relieftrace")

logfire.configure(
    service_name="relieftrace-api",
    send_to_logfire="if-token-present",
    console=False,
)
try:
    logfire.instrument_httpx()  # traces the outbound Gemini call
except Exception as _exc:  # optional extra missing - not fatal
    log.warning("logfire httpx instrumentation unavailable: %s", _exc)

from app.cache import cached, invalidate
from app.db import get_cursor
from app.schemas import (
    RESOURCE_TYPES,
    AiBriefing,
    ContributionInput,
    ContributionResult,
    RecentDelivery,
    ResourceBreakdown,
    ResponseTrendPoint,
    ZoneGap,
)
from app.solana_client import build_memo, ensure_funded, send_memo

SOLANA_CLUSTER = os.getenv("SOLANA_CLUSTER", "devnet")

IS_PRODUCTION = os.getenv("ENVIRONMENT", "development") == "production"
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173,http://localhost:5174").split(",")
    if origin.strip()
]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="ReliefTrace API",
    description="Aid you can actually verify.",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

try:
    logfire.instrument_fastapi(app, capture_headers=False)
except Exception as _exc:  # optional extra missing - not fatal
    log.warning("logfire fastapi instrumentation unavailable: %s", _exc)

log.info(
    "ReliefTrace API starting | env=%s | gemini=%s | gemini_key=%s | cors=%s",
    "production" if IS_PRODUCTION else "development",
    GEMINI_MODEL,
    "set" if GEMINI_API_KEY else "MISSING",
    ",".join(FRONTEND_ORIGINS),
)


@app.on_event("startup")
def _log_startup():
    log.info("startup complete | logfire=%s", "on" if os.getenv("LOGFIRE_TOKEN") else "off (no token)")


@app.exception_handler(snowflake.connector.Error)
def snowflake_error_handler(request: Request, exc: snowflake.connector.Error):
    log.error("snowflake error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The database is temporarily unavailable. Please try again shortly."},
    )


def run_query(sql: str, params: dict | None = None) -> list[dict]:
    try:
        with get_cursor() as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()
    except HTTPException:
        raise
    except Exception as exc:
        log.error("query failed: %s | sql=%s", exc, " ".join(sql.split())[:200])
        raise HTTPException(status_code=500, detail=f"Snowflake query failed: {exc}")


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


@app.get("/api/insights/zone-gaps", response_model=list[ZoneGap])
@cached(ttl=120)
def zone_gaps():
    sql = """
        SELECT
            ZONE_NAME,
            RESOURCE_TYPE,
            SUM(QUANTITY_NEEDED) AS QUANTITY_NEEDED,
            SUM(QUANTITY_FULFILLED) AS QUANTITY_FULFILLED,
            SUM(QUANTITY_NEEDED) - SUM(QUANTITY_FULFILLED) AS UNMET_NEED,
            MAX(CASE URGENCY_LEVEL
                WHEN 'critical' THEN 3
                WHEN 'medium' THEN 2
                ELSE 1
            END) AS URGENCY_RANK
        FROM RELIEF_REQUESTS
        GROUP BY ZONE_NAME, RESOURCE_TYPE
        ORDER BY UNMET_NEED DESC
    """
    rows = run_query(sql)
    rank_to_label = {3: "critical", 2: "medium", 1: "low"}
    return [
        ZoneGap(
            zone_name=row["ZONE_NAME"],
            resource_type=row["RESOURCE_TYPE"],
            quantity_needed=row["QUANTITY_NEEDED"],
            quantity_fulfilled=row["QUANTITY_FULFILLED"],
            unmet_need=row["UNMET_NEED"],
            urgency_level=rank_to_label[row["URGENCY_RANK"]],
        )
        for row in rows
    ]


@app.get("/api/insights/response-trend", response_model=list[ResponseTrendPoint])
@cached(ttl=120)
def response_trend():
    sql = """
        WITH req AS (
            SELECT REQUEST_DATE AS DAY, COUNT(*) AS REQUESTS_COUNT, SUM(QUANTITY_NEEDED) AS QUANTITY_REQUESTED
            FROM RELIEF_REQUESTS
            GROUP BY REQUEST_DATE
        ),
        del AS (
            SELECT DELIVERY_DATE AS DAY, COUNT(*) AS DELIVERIES_COUNT, SUM(QUANTITY_SENT) AS QUANTITY_DELIVERED
            FROM RELIEF_DELIVERIES
            GROUP BY DELIVERY_DATE
        )
        SELECT
            COALESCE(req.DAY, del.DAY) AS DAY,
            COALESCE(REQUESTS_COUNT, 0) AS REQUESTS_COUNT,
            COALESCE(QUANTITY_REQUESTED, 0) AS QUANTITY_REQUESTED,
            COALESCE(DELIVERIES_COUNT, 0) AS DELIVERIES_COUNT,
            COALESCE(QUANTITY_DELIVERED, 0) AS QUANTITY_DELIVERED
        FROM req
        FULL OUTER JOIN del ON req.DAY = del.DAY
        ORDER BY DAY
    """
    rows = run_query(sql)
    return [
        ResponseTrendPoint(
            day=row["DAY"],
            requests_count=row["REQUESTS_COUNT"],
            quantity_requested=row["QUANTITY_REQUESTED"],
            deliveries_count=row["DELIVERIES_COUNT"],
            quantity_delivered=row["QUANTITY_DELIVERED"],
        )
        for row in rows
    ]


@app.get("/api/insights/resource-breakdown", response_model=list[ResourceBreakdown])
@cached(ttl=120)
def resource_breakdown():
    sql = """
        SELECT
            RESOURCE_TYPE,
            SUM(QUANTITY_NEEDED) AS TOTAL_NEEDED,
            SUM(QUANTITY_FULFILLED) AS TOTAL_FULFILLED,
            SUM(QUANTITY_NEEDED) - SUM(QUANTITY_FULFILLED) AS UNMET_NEED
        FROM RELIEF_REQUESTS
        GROUP BY RESOURCE_TYPE
        ORDER BY TOTAL_NEEDED DESC
    """
    rows = run_query(sql)
    return [
        ResourceBreakdown(
            resource_type=row["RESOURCE_TYPE"],
            total_needed=row["TOTAL_NEEDED"],
            total_fulfilled=row["TOTAL_FULFILLED"],
            unmet_need=row["UNMET_NEED"],
        )
        for row in rows
    ]


@app.get("/api/deliveries/recent", response_model=list[RecentDelivery])
@cached(ttl=20)
def recent_deliveries(limit: int = 20):
    limit = max(1, min(limit, 100))
    sql = """
        SELECT
            DELIVERY_ID,
            ZONE_NAME,
            DONOR_ORG,
            DONOR_EMAIL,
            RESOURCE_TYPE,
            QUANTITY_SENT,
            DELIVERY_DATE,
            SOLANA_TX_SIG
        FROM RELIEF_DELIVERIES
        ORDER BY DELIVERY_DATE DESC, SOURCE ASC
        LIMIT %(limit)s
    """
    rows = run_query(sql, {"limit": limit})
    return [
        RecentDelivery(
            delivery_id=row["DELIVERY_ID"],
            zone_name=row["ZONE_NAME"],
            donor_org=row["DONOR_ORG"],
            donor_email=row.get("DONOR_EMAIL") or None,
            resource_type=row["RESOURCE_TYPE"],
            quantity_sent=row["QUANTITY_SENT"],
            delivery_date=row["DELIVERY_DATE"],
            solana_tx_sig=row["SOLANA_TX_SIG"] or None,
        )
        for row in rows
    ]


@app.get("/api/zones", response_model=list[str])
@cached(ttl=60)
def zones():
    """Known zone names (from requests and past deliveries), as autocomplete
    suggestions for the contribution form. May be empty - the form accepts any
    zone as free text."""
    rows = run_query(
        """
        SELECT ZONE_NAME FROM RELIEF_REQUESTS
        UNION
        SELECT ZONE_NAME FROM RELIEF_DELIVERIES
        ORDER BY ZONE_NAME
        """
    )
    return [row["ZONE_NAME"] for row in rows]


@app.get("/api/resource-types", response_model=list[str])
@cached(ttl=3600)
def resource_types():
    return RESOURCE_TYPES


# ---------------------------------------------------------------------------
# Contribute: the one write path. Records a delivery in Snowflake and anchors
# it with a Solana devnet memo transaction, storing the signature back.
# ---------------------------------------------------------------------------


@app.post("/api/contribute", response_model=ContributionResult, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
def contribute(request: Request, payload: ContributionInput):
    if payload.resource_type not in RESOURCE_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"resource_type must be one of {RESOURCE_TYPES}",
        )

    donor = payload.donor_name.strip()
    email = str(payload.donor_email).strip()
    zone = payload.zone_name.strip()
    delivery_id = str(uuid.uuid4())
    today = date.today()

    log.info(
        "contribute: %s %s -> %s by %s (delivery=%s)",
        payload.quantity, payload.resource_type, zone, donor, delivery_id,
    )

    # 1. Anchor on-chain first - if the memo tx fails we don't want a
    #    delivery row claiming to be verified when it isn't.
    #    Note: only the donor name goes on-chain, never the email address.
    try:
        ensure_funded()
        tx_sig = send_memo(
            build_memo(donor=donor, resource=payload.resource_type, zone=zone, quantity=payload.quantity)
        )
        log.info("contribute: on-chain ok delivery=%s sig=%s", delivery_id, tx_sig)
    except Exception as exc:
        log.error("contribute: on-chain FAILED delivery=%s: %s", delivery_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not record the contribution on Solana devnet: {exc}",
        )

    # 2. Persist to Snowflake with the confirmed signature.
    insert = """
        INSERT INTO RELIEF_DELIVERIES
            (DELIVERY_ID, REQUEST_ID, ZONE_NAME, DONOR_ORG, DONOR_EMAIL, RESOURCE_TYPE,
             QUANTITY_SENT, DELIVERY_DATE, SOLANA_TX_SIG, SOURCE)
        VALUES
            (%(id)s, NULL, %(zone)s, %(donor)s, %(email)s, %(resource)s,
             %(qty)s, %(day)s, %(sig)s, 'public')
    """
    try:
        with get_cursor() as cur:
            cur.execute(
                insert,
                {
                    "id": delivery_id,
                    "zone": zone,
                    "donor": donor,
                    "email": email,
                    "resource": payload.resource_type,
                    "qty": payload.quantity,
                    "day": today.isoformat(),
                    "sig": tx_sig,
                },
            )
            cur.connection.commit()
    except Exception as exc:
        log.error(
            "contribute: DB write FAILED after on-chain success delivery=%s sig=%s: %s",
            delivery_id, tx_sig, exc,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"On-chain record {tx_sig} succeeded but the database write failed: {exc}",
        )

    log.info("contribute: persisted delivery=%s", delivery_id)
    # new delivery changes the deliveries table and the gap/trend rollups
    invalidate("recent_deliveries", "response_trend", "zone_gaps", "resource_breakdown")

    return ContributionResult(
        delivery_id=delivery_id,
        donor_name=donor,
        donor_email=email,
        resource_type=payload.resource_type,
        quantity=payload.quantity,
        zone_name=zone,
        delivery_date=today,
        solana_tx_sig=tx_sig,
        explorer_url=f"https://explorer.solana.com/tx/{tx_sig}?cluster={SOLANA_CLUSTER}",
    )


# ---------------------------------------------------------------------------
# AI situation briefing
# ---------------------------------------------------------------------------


def _build_briefing_prompt(gaps: list[ZoneGap], trend: list[ResponseTrendPoint]) -> str:
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


@app.get("/api/insights/ai-briefing", response_model=AiBriefing)
@limiter.limit("10/hour")
def ai_briefing(request: Request):
    if not GEMINI_API_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GEMINI_API_KEY is not configured")

    gaps = zone_gaps()
    trend = response_trend()
    prompt = _build_briefing_prompt(gaps, trend)
    log.info("ai-briefing: calling %s with %d gap rows", GEMINI_MODEL, len(gaps))

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        resp = httpx.post(
            url,
            params={"key": GEMINI_API_KEY},
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
