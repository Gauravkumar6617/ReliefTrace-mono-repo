from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from app.api.deps import limiter
from app.schemas import AiBriefing
from app.services.briefing import generate_briefing

router = APIRouter(prefix="/api", tags=["briefing"])


@router.get("/insights/ai-briefing", response_model=AiBriefing)
@limiter.limit("10/hour")
async def ai_briefing(request: Request):
    return await run_in_threadpool(generate_briefing)
