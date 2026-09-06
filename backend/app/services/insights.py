"""
Read-only insight queries over the Snowflake relief tables. Each function is
cached (short TTL) because the underlying data changes slowly and the dashboard
asks for all of them at once.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.core.cache import cached
from app.db import get_cursor
from app.schemas import (
    RESOURCE_TYPES,
    RecentDelivery,
    ResourceBreakdown,
    ResponseTrendPoint,
    ZoneGap,
)

log = logging.getLogger("relieftrace.insights")

# Insight rollups: bumped from 120s. The data moves slowly and a contribution
# explicitly invalidates these keys, so a longer TTL is safe and keeps cold
# Snowflake queries off the request path.
_INSIGHT_TTL = 300
_DELIVERIES_TTL = 30


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


@cached(ttl=_INSIGHT_TTL)
def zone_gaps() -> list[ZoneGap]:
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
        for row in run_query(sql)
    ]


@cached(ttl=_INSIGHT_TTL)
def response_trend() -> list[ResponseTrendPoint]:
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
    return [
        ResponseTrendPoint(
            day=row["DAY"],
            requests_count=row["REQUESTS_COUNT"],
            quantity_requested=row["QUANTITY_REQUESTED"],
            deliveries_count=row["DELIVERIES_COUNT"],
            quantity_delivered=row["QUANTITY_DELIVERED"],
        )
        for row in run_query(sql)
    ]


@cached(ttl=_INSIGHT_TTL)
def resource_breakdown() -> list[ResourceBreakdown]:
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
    return [
        ResourceBreakdown(
            resource_type=row["RESOURCE_TYPE"],
            total_needed=row["TOTAL_NEEDED"],
            total_fulfilled=row["TOTAL_FULFILLED"],
            unmet_need=row["UNMET_NEED"],
        )
        for row in run_query(sql)
    ]


@cached(ttl=_DELIVERIES_TTL)
def recent_deliveries(limit: int = 20) -> list[RecentDelivery]:
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
        for row in run_query(sql, {"limit": limit})
    ]


@cached(ttl=60)
def zones() -> list[str]:
    """Known zone names (requests + past deliveries), for the contribution
    form's autocomplete. May be empty - the form accepts any zone as free text."""
    rows = run_query(
        """
        SELECT ZONE_NAME FROM RELIEF_REQUESTS
        UNION
        SELECT ZONE_NAME FROM RELIEF_DELIVERIES
        ORDER BY ZONE_NAME
        """
    )
    return [row["ZONE_NAME"] for row in rows]


@cached(ttl=3600)
def resource_types() -> list[str]:
    return RESOURCE_TYPES
