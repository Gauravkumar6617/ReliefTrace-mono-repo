"""
One-page situation-briefing PDF: the ReliefTrace header, the current Gemini
narrative + priorities, and a table of the 10 highest-urgency zone gaps.

Pure-Python (reportlab) so it works on hosts without cairo/pango. Used by the
"Download as PDF" button and attached to the donor receipt email.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.briefing import generate_briefing
from app.services.insights import zone_gaps

log = logging.getLogger("relieftrace.pdf")

_URGENCY_RANK = {"critical": 3, "medium": 2, "low": 1}
_BRAND = colors.HexColor("#2f6f62")
_INK = colors.HexColor("#2f2a24")


def _top_gaps(limit: int = 10):
    return sorted(
        zone_gaps(),
        key=lambda g: (_URGENCY_RANK.get(g.urgency_level, 0), g.unmet_need),
        reverse=True,
    )[:limit]


def build_briefing_pdf() -> bytes:
    briefing = generate_briefing()  # cached; raises 503/502 like the endpoint
    gaps = _top_gaps()

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14, textColor=_INK)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, textColor=_BRAND, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=_INK, spaceBefore=14)
    meta = ParagraphStyle("meta", parent=body, fontSize=8, textColor=colors.HexColor("#6b6459"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="ReliefTrace — Situation Briefing",
    )

    story = [
        Paragraph("ReliefTrace", h1),
        Paragraph("Situation Briefing — aid you can actually verify", meta),
        Paragraph(
            "Generated " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), meta
        ),
        Spacer(1, 10),
    ]

    if briefing.briefing:
        story += [Paragraph("Overview", h2), Paragraph(briefing.briefing, body)]

    if briefing.priorities:
        story.append(Paragraph("Priority zones", h2))
        for p in briefing.priorities:
            story.append(
                Paragraph(
                    f"<b>{p.rank}. {p.zone}</b> &nbsp;({p.urgency}, {p.confidence} confidence)<br/>"
                    f"{p.reason}<br/><i>Action:</i> {p.recommended_action}",
                    body,
                )
            )
            story.append(Spacer(1, 4))

    story.append(Paragraph("Top 10 highest-urgency zone gaps", h2))
    rows = [["Zone", "Resource", "Needed", "Fulfilled", "Unmet", "Urgency"]]
    for g in gaps:
        rows.append([
            g.zone_name,
            g.resource_type,
            f"{g.quantity_needed:,.0f}",
            f"{g.quantity_fulfilled:,.0f}",
            f"{g.unmet_need:,.0f}",
            g.urgency_level.title(),
        ])
    table = Table(rows, hAlign="LEFT", colWidths=[46 * mm, 24 * mm, 20 * mm, 22 * mm, 20 * mm, 20 * mm])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (5, 0), (5, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#faf8f3")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d4c9")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(table)
    if not gaps:
        story.append(Paragraph("No zone gap data available yet.", body))

    doc.build(story)
    log.info("pdf: built briefing (%d gap rows, %d priorities)", len(gaps), len(briefing.priorities))
    return buf.getvalue()
