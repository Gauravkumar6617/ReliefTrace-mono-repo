from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.api.deps import limiter
from app.core.security import require_api_key
from app.schemas import AiBriefing
from app.services.briefing import generate_briefing
from app.services.pdf import build_briefing_pdf

router = APIRouter(prefix="/api", tags=["briefing"])


@router.get(
    "/insights/ai-briefing",
    response_model=AiBriefing,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("10/hour")
async def ai_briefing(request: Request):
    return await run_in_threadpool(generate_briefing)


@router.get(
    "/insights/ai-briefing.pdf",
    dependencies=[Depends(require_api_key)],
    responses={200: {"content": {"application/pdf": {}}}},
)
@limiter.limit("10/hour")
async def ai_briefing_pdf(request: Request):
    pdf = await run_in_threadpool(build_briefing_pdf)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="relieftrace-briefing.pdf"'},
    )
