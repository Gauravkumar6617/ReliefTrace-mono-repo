"""
Best-effort transactional email: a confirmation receipt to the donor after a
contribution is recorded and anchored on-chain.

Deliberately fire-and-forget - it runs in a FastAPI BackgroundTask *after* the
response is sent, and any failure (or no SMTP config at all) is logged and
swallowed. A contribution is never blocked or failed by email.

Uses stdlib smtplib, so any SMTP provider works (a Gmail App Password, Brevo,
Mailgun SMTP, Resend SMTP, ...). Set SMTP_HOST to enable.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from app.core.config import settings
from app.schemas import ContributionResult

log = logging.getLogger("relieftrace.email")


def _build_message(result: ContributionResult) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"ReliefTrace: {result.resource_type} for {result.zone_name} recorded"
    msg["From"] = settings.smtp_from
    # greet with the donor org/name only - never the cause note
    greeting = result.donor_org or "there"
    msg["To"] = formataddr((result.donor_org, result.donor_email))

    qty = f"{result.quantity:g}"
    note_line = f"  Cause/note: {result.cause_note}\n" if result.cause_note else ""
    text = (
        f"Hi {greeting},\n\n"
        f"Your contribution has been recorded and anchored on the Solana devnet.\n\n"
        f"  Resource:   {qty} {result.resource_type}\n"
        f"  Zone:       {result.zone_name}\n"
        f"{note_line}"
        f"  Date:       {result.delivery_date.isoformat()}\n"
        f"  Delivery ID:{result.delivery_id}\n"
        f"  On-chain:   {result.solana_tx_sig}\n\n"
        f"Verify it yourself on Solana Explorer:\n{result.explorer_url}\n\n"
        f"A current situation briefing is attached as a PDF.\n\n"
        f"Thank you.\n— ReliefTrace\n"
    )
    msg.set_content(text)

    note_row = (
        f'<tr><td style="padding:4px 12px 4px 0;color:#6b6459">Cause / note</td>'
        f"<td>{result.cause_note}</td></tr>"
        if result.cause_note
        else ""
    )
    msg.add_alternative(
        f"""\
<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#2f2a24;max-width:520px">
  <p>Hi {greeting},</p>
  <p>Your contribution has been recorded and <strong>anchored on the Solana devnet</strong>.</p>
  <table style="border-collapse:collapse;font-size:14px">
    <tr><td style="padding:4px 12px 4px 0;color:#6b6459">Resource</td><td><strong>{qty} {result.resource_type}</strong></td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#6b6459">Zone</td><td>{result.zone_name}</td></tr>
    {note_row}
    <tr><td style="padding:4px 12px 4px 0;color:#6b6459">Date</td><td>{result.delivery_date.isoformat()}</td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#6b6459">Delivery ID</td><td style="font-family:ui-monospace,Menlo,monospace">{result.delivery_id}</td></tr>
  </table>
  <p style="margin-top:16px">
    <a href="{result.explorer_url}"
       style="background:#2f6f62;color:#fff;text-decoration:none;padding:9px 16px;border-radius:8px;display:inline-block">
       Verify on-chain &#8599;
    </a>
  </p>
  <p style="color:#6b6459;font-size:13px">Transaction: {result.solana_tx_sig}</p>
  <p style="color:#6b6459;font-size:13px">A current situation briefing is attached as a PDF.</p>
  <p>Thank you.<br/>&mdash; ReliefTrace</p>
</div>
""",
        subtype="html",
    )

    # attach the situation briefing PDF - best effort, never fatal
    try:
        from app.services.pdf import build_briefing_pdf

        msg.add_attachment(
            build_briefing_pdf(),
            maintype="application",
            subtype="pdf",
            filename="relieftrace-briefing.pdf",
        )
    except Exception as exc:  # noqa: BLE001 - e.g. no GEMINI_API_KEY; send without it
        log.info("email: skipping PDF attachment for %s: %s", result.delivery_id, exc)

    return msg


def send_contribution_receipt(result: ContributionResult) -> bool:
    """Send the donor their receipt. Returns True on success, False otherwise.
    Never raises."""
    if not settings.email_enabled:
        log.debug("email disabled (no SMTP_HOST); skipping receipt for %s", result.delivery_id)
        return False

    _, to_addr = parseaddr(result.donor_email)
    if not to_addr or "@" not in to_addr:
        log.warning("email: bad recipient %r for delivery %s", result.donor_email, result.delivery_id)
        return False

    try:
        msg = _build_message(result)
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                smtp.ehlo()
                if settings.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(msg)
        log.info("email: receipt sent for delivery %s to %s", result.delivery_id, to_addr)
        return True
    except Exception as exc:  # noqa: BLE001 - fire-and-forget
        log.warning("email: failed to send receipt for delivery %s: %s", result.delivery_id, exc)
        return False
