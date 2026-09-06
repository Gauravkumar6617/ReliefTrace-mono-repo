from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool

from app.api.deps import limiter
from app.core.security import require_api_key
from app.schemas import AskInput, AskResult
from app.services.ask import answer_question

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask", response_model=AskResult, dependencies=[Depends(require_api_key)])
@limiter.limit("30/hour")
async def ask(request: Request, payload: AskInput):
    """Natural-language question answered by Gemini via function calling over
    the live Snowflake data."""
    return await run_in_threadpool(answer_question, payload.question)
