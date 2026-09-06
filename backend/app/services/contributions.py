"""
The one write path: record a relief delivery in Snowflake and anchor it with a
Solana devnet memo transaction.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import HTTPException, status

from app.core.cache import invalidate
from app.core.config import settings
from app.db import get_cursor
from app.schemas import ContributionInput, ContributionResult
from app.services.solana import build_memo, ensure_funded, send_memo

log = logging.getLogger("relieftrace.contribute")

_INSERT = """
    INSERT INTO RELIEF_DELIVERIES
        (DELIVERY_ID, REQUEST_ID, ZONE_NAME, DONOR_ORG, DONOR_EMAIL, RESOURCE_TYPE,
         QUANTITY_SENT, DELIVERY_DATE, SOLANA_TX_SIG, SOURCE)
    VALUES
        (%(id)s, NULL, %(zone)s, %(donor)s, %(email)s, %(resource)s,
         %(qty)s, %(day)s, %(sig)s, 'public')
"""


def create_contribution(payload: ContributionInput) -> ContributionResult:
    donor = payload.donor_name.strip()
    email = str(payload.donor_email).strip()
    zone = payload.zone_name.strip()
    delivery_id = str(uuid.uuid4())
    today = date.today()

    log.info(
        "contribute: %s %s -> %s by %s (delivery=%s)",
        payload.quantity, payload.resource_type, zone, donor, delivery_id,
    )

    # 1. Anchor on-chain first - if the memo tx fails we don't want a delivery
    #    row claiming to be verified when it isn't. Only the donor name goes
    #    on-chain, never the email address.
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
    try:
        with get_cursor() as cur:
            cur.execute(
                _INSERT,
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
    # a new delivery changes the deliveries table and the gap/trend rollups
    invalidate(
        "recent_deliveries",
        "response_trend",
        "zone_gaps",
        "resource_breakdown",
        "generate_briefing",
    )

    return ContributionResult(
        delivery_id=delivery_id,
        donor_name=donor,
        donor_email=email,
        resource_type=payload.resource_type,
        quantity=payload.quantity,
        zone_name=zone,
        delivery_date=today,
        solana_tx_sig=tx_sig,
        explorer_url=f"https://explorer.solana.com/tx/{tx_sig}?cluster={settings.solana_cluster}",
    )
