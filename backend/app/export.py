"""
app/export.py – report export helpers (CSV and PDF via reportlab).

Owned by M4.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import ClaimRecord, VerdictRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(
    claims: list["ClaimRecord"],
    verdicts: list["VerdictRecord"],
) -> bytes:
    """
    Build a UTF-8 CSV report for a document.

    Returns raw bytes suitable for a StreamingResponse.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "claim_id",
        "claim_text",
        "page",
        "section",
        "claim_type",
        "reference_id",
        "verdict",
        "confidence",
        "needs_human_review",
        "flags",
        "explanation",
    ])

    # Build a quick verdict lookup: (claim_id, reference_id) -> VerdictRecord
    verdict_map: dict[tuple[str, str], "VerdictRecord"] = {
        (v.claim_id, v.reference_id): v for v in verdicts
    }

    for claim in claims:
        ref_ids: list[str] = claim.reference_ids or []
        if not ref_ids:
            # Claim with no citations: one row, empty verdict columns
            writer.writerow([
                claim.id,
                claim.text,
                claim.page or "",
                claim.section or "",
                claim.claim_type,
                "",
                "",
                "",
                "",
                " | ".join(claim.flags or []),
                "",
            ])
        else:
            for rid in ref_ids:
                v = verdict_map.get((claim.id, rid))
                writer.writerow([
                    claim.id,
                    claim.text,
                    claim.page or "",
                    claim.section or "",
                    claim.claim_type,
                    rid,
                    v.verdict if v else "",
                    f"{v.confidence:.3f}" if v else "",
                    str(v.needs_human_review) if v else "",
                    " | ".join((v.flags or []) + (claim.flags or [])),
                    v.explanation if v else "",
                ])

    return buf.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def export_pdf(
    doc_id: str,
    claims: list["ClaimRecord"],
    verdicts: list["VerdictRecord"],
) -> bytes:
    """
    Build a PDF report using reportlab.

    Returns raw bytes suitable for a StreamingResponse.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
            HRFlowable,
        )
    except ImportError as exc:
        logger.error("reportlab not installed; cannot generate PDF: %s", exc)
        return b""

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"CiteVerify Report – {doc_id}",
        author="CiteVerify (research assistant; not a final academic judgment)",
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    small = ParagraphStyle("small", parent=normal, fontSize=8, leading=10)
    disclaimer_style = ParagraphStyle(
        "disclaimer",
        parent=normal,
        fontSize=9,
        textColor=colors.HexColor("#b45309"),
        leading=13,
    )

    # Verdict colour map
    VERDICT_COLORS = {
        "supported": colors.HexColor("#16a34a"),
        "partly_supported": colors.HexColor("#ca8a04"),
        "unsupported": colors.HexColor("#dc2626"),
        "contradictory": colors.HexColor("#9333ea"),
        "possibly_outdated": colors.HexColor("#ea580c"),
        "needs_review": colors.HexColor("#64748b"),
    }

    verdict_map: dict[tuple[str, str], "VerdictRecord"] = {
        (v.claim_id, v.reference_id): v for v in verdicts
    }

    story = []

    # Title
    story.append(Paragraph(f"CiteVerify Verification Report", h1))
    story.append(Paragraph(f"Document ID: <b>{doc_id}</b>", normal))
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        Paragraph(
            "⚠ This report is produced by an automated research assistant. "
            "It must NOT be treated as a final academic judgment. "
            "All verdicts with needs_human_review=True must be checked by a qualified reviewer.",
            disclaimer_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
    story.append(Spacer(1, 0.5 * cm))

    for claim in claims:
        ref_ids: list[str] = claim.reference_ids or []
        story.append(
            Paragraph(
                f"<b>Claim</b> <font size='8' color='grey'>{claim.id}</font>",
                h2,
            )
        )
        story.append(Paragraph(claim.text, normal))

        meta_parts = []
        if claim.page:
            meta_parts.append(f"Page {claim.page}")
        if claim.section:
            meta_parts.append(f"§ {claim.section}")
        meta_parts.append(f"Type: {claim.claim_type}")
        if claim.flags:
            meta_parts.append(f"Flags: {', '.join(claim.flags)}")
        story.append(Paragraph("  |  ".join(meta_parts), small))
        story.append(Spacer(1, 0.2 * cm))

        if not ref_ids:
            story.append(Paragraph("<i>No citations found for this claim.</i>", small))
        else:
            for rid in ref_ids:
                v = verdict_map.get((claim.id, rid))
                if v is None:
                    story.append(Paragraph(f"Reference {rid}: verdict not available.", small))
                    continue

                v_color = VERDICT_COLORS.get(v.verdict, colors.black)
                story.append(
                    Paragraph(
                        f"<b>Ref:</b> {rid}  "
                        f"<font color='#{v_color.hexval()[1:] if hasattr(v_color,'hexval') else '000000'}'>"
                        f"<b>{v.verdict.upper()}</b></font>  "
                        f"confidence={v.confidence:.2f}  "
                        f"review={'YES' if v.needs_human_review else 'no'}",
                        normal,
                    )
                )
                story.append(Paragraph(v.explanation or "", small))
                if v.flags:
                    story.append(Paragraph(f"Flags: {', '.join(v.flags)}", small))
                story.append(Spacer(1, 0.15 * cm))

        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
        story.append(Spacer(1, 0.3 * cm))

    doc.build(story)
    return buf.getvalue()
