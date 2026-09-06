"""
Batch-anchors any RELIEF_DELIVERIES rows that don't yet have a Solana devnet
memo signature: one Memo-program transaction per delivery, signature written
back to SOLANA_TX_SIG. This is what makes "Verify on-chain" in the dashboard a
real link for the seeded data.

Live contributions submitted through the dashboard are anchored inline by
POST /api/contribute; this script is only for the synthetic backlog.

Run (from backend/): python -m scripts.anchor_deliveries
"""

import time

from app.db import get_cursor
from app.services.solana import build_memo, ensure_funded, get_wallet, send_memo


def fetch_pending_deliveries() -> list[dict]:
    sql = """
        SELECT DELIVERY_ID, ZONE_NAME, RESOURCE_TYPE, QUANTITY_SENT, DONOR_ORG
        FROM RELIEF_DELIVERIES
        WHERE SOLANA_TX_SIG IS NULL OR SOLANA_TX_SIG = ''
        ORDER BY DELIVERY_DATE
    """
    with get_cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def main():
    wallet = get_wallet()
    balance = ensure_funded()
    print(f"Wallet {wallet.pubkey()} balance: {balance / 1e9:.4f} SOL")

    deliveries = fetch_pending_deliveries()
    print(f"{len(deliveries)} deliveries without a Solana tx signature.")

    with get_cursor() as cur:
        for i, row in enumerate(deliveries, start=1):
            memo = build_memo(
                donor=row["DONOR_ORG"],
                resource=row["RESOURCE_TYPE"],
                zone=row["ZONE_NAME"],
                quantity=row["QUANTITY_SENT"],
            )
            try:
                signature = send_memo(memo)
            except Exception as exc:
                print(f"[{i}/{len(deliveries)}] FAILED {row['DELIVERY_ID']}: {exc}")
                continue

            cur.execute(
                "UPDATE RELIEF_DELIVERIES SET SOLANA_TX_SIG = %(sig)s WHERE DELIVERY_ID = %(id)s",
                {"sig": signature, "id": row["DELIVERY_ID"]},
            )
            print(f"[{i}/{len(deliveries)}] {row['DELIVERY_ID']} -> {signature}")
            time.sleep(0.3)  # be gentle with devnet RPC rate limits

        cur.connection.commit()

    print("Done.")


if __name__ == "__main__":
    main()
