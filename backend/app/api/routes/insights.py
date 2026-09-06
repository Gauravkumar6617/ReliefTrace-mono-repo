"""Read-only insight endpoints, plus a combined /api/dashboard that returns
everything the dashboard's initial load needs in one round trip."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.schemas import (
    RecentDelivery,
    ResourceBreakdown,
    ResponseTrendPoint,
    ZoneGap,
)
from app.services import insights

router = APIRouter(prefix="/api", tags=["insights"])


class DashboardSnapshot(BaseModel):
    zone_gaps: list[ZoneGap]
    resource_breakdown: list[ResourceBreakdown]
    response_trend: list[ResponseTrendPoint]
    recent_deliveries: list[RecentDelivery]
    affected_population: int


@router.get("/dashboard", response_model=DashboardSnapshot)
async def dashboard(deliveries_limit: int = 25):
    """One call for the whole dashboard. The queries run concurrently on the
    connection pool (or are served from cache)."""
    gaps, breakdown, trend, deliveries, population = await asyncio.gather(
        run_in_threadpool(insights.zone_gaps),
        run_in_threadpool(insights.resource_breakdown),
        run_in_threadpool(insights.response_trend),
        run_in_threadpool(insights.recent_deliveries, deliveries_limit),
        run_in_threadpool(insights.affected_population),
    )
    return DashboardSnapshot(
        zone_gaps=gaps,
        resource_breakdown=breakdown,
        response_trend=trend,
        recent_deliveries=deliveries,
        affected_population=population,
    )


@router.get("/insights/zone-gaps", response_model=list[ZoneGap])
async def zone_gaps():
    return await run_in_threadpool(insights.zone_gaps)


@router.get("/insights/response-trend", response_model=list[ResponseTrendPoint])
async def response_trend():
    return await run_in_threadpool(insights.response_trend)


@router.get("/insights/resource-breakdown", response_model=list[ResourceBreakdown])
async def resource_breakdown():
    return await run_in_threadpool(insights.resource_breakdown)


@router.get("/deliveries/recent", response_model=list[RecentDelivery])
async def recent_deliveries(limit: int = 20):
    return await run_in_threadpool(insights.recent_deliveries, limit)


@router.get("/zones", response_model=list[str])
async def zones():
    return await run_in_threadpool(insights.zones)


@router.get("/resource-types", response_model=list[str])
async def resource_types():
    return await run_in_threadpool(insights.resource_types)
