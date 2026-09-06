from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import limiter
from app.core.events import publish
from app.core.security import require_api_key
from app.schemas import ContributionInput, ContributionResult
from app.services.contributions import create_contribution
from app.services.email import send_contribution_receipt

log = logging.getLogger("relieftrace.contribute")

router = APIRouter(prefix="/api", tags=["contribute"])


@router.post(
    "/contribute",
    response_model=ContributionResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("20/hour")
async def contribute(request: Request, payload: ContributionInput, background_tasks: BackgroundTasks):
    # Honeypot: only a bot fills the hidden `website` field. Reject before any
    # on-chain / DB work, with a generic message that doesn't name the field.
    if payload.website.strip():
        client = request.client.host if request.client else "?"
        log.warning("honeypot tripped (website=%r) from %s", payload.website[:80], client)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Submission rejected.")

    result = await run_in_threadpool(create_contribution, payload)

    # tell every open dashboard (across replicas) that a delivery landed
    await publish(
        {
            "type": "contribution",
            "delivery": {
                "delivery_id": result.delivery_id,
                "zone_name": result.zone_name,
                "donor_org": result.donor_name,
                "resource_type": result.resource_type,
                "quantity_sent": result.quantity,
                "delivery_date": result.delivery_date.isoformat(),
                "solana_tx_sig": result.solana_tx_sig,
            },
        }
    )

    # donor receipt: after the response is sent, best-effort, never blocks
    background_tasks.add_task(send_contribution_receipt, result)
    return result
