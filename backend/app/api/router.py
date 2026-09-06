"""Aggregates every route module into one router mounted by the app factory."""

from fastapi import APIRouter

from app.api.routes import briefing, contribute, health, insights, stream

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(insights.router)
api_router.include_router(contribute.router)
api_router.include_router(briefing.router)
api_router.include_router(stream.router)
