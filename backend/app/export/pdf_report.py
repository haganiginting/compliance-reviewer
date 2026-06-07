from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


SEVERITIES = ("Critical", "Major", "Advisory")


def render_review_pdf(review: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="Compliance Report",
        author="Compliance Reviewer",
    )
    styles = _build_styles()
    story: list[Any] = []

    report = review["report"]
    document = report.get("document", {})
    summary = report.get("summary", {})
    agencies = report.get("agencies", [])

    story.extend(
        [
            Paragraph("Compliance Report", styles["Title"]),
            Spacer(1, 5 * mm),
            _metadata_table(review, report, document, styles),
            Spacer(1, 7 * mm),
            Paragraph("Summary", styles["SectionHeading"]),
            Spacer(1, 2 * mm),
            _summary_table(summary, agencies, styles),
            Spacer(1, 7 * mm),
            Paragraph("Agency Findings", styles["SectionHeading"]),
            Spacer(1, 3 * mm),
        ]
    )

    for index, agency in enumerate(agencies):
        if index > 0:
            story.append(Spacer(1, 5 * mm))
        story.extend(_agency_section(agency, styles))

    if not agencies:
        story.append(Paragraph("No agency reviews were stored for this report.", styles["Body"]))

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()


def _metadata_table(
    review: dict[str, Any],
    report: dict[str, Any],
    document: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> Table:
    rows = [
        [
            Paragraph("<b>Filename</b>", styles["Label"]),
            Paragraph(_paragraph_text(review.get("filename") or document.get("filename")), styles["Body"]),
        ],
        [
            Paragraph("<b>Created</b>", styles["Label"]),
            Paragraph(_format_date(review.get("created_at")), styles["Body"]),
        ],
        [
            Paragraph("<b>Reviewed</b>", styles["Label"]),
            Paragraph(_format_date(report.get("reviewed_at") or review.get("updated_at")), styles["Body"]),
        ],
        [
            Paragraph("<b>Drawing pages</b>", styles["Label"]),
            Paragraph(_paragraph_text(document.get("page_count", "Unknown")), styles["Body"]),
        ],
    ]
    table = Table(rows, colWidths=[33 * mm, 129 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4d4d4")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _summary_table(
    summary: dict[str, Any],
    agencies: list[dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> Table:
    by_agency = summary.get("by_agency", {})
    by_severity = summary.get("by_severity", {})
    agency_summary = ", ".join(
        f"{agency.get('agency', 'Agency')}: {by_agency.get(agency.get('agency'), len(agency.get('issues', [])))}"
        for agency in agencies
    )
    severity_summary = ", ".join(
        f"{severity}: {by_severity.get(severity, 0)}"
        for severity in SEVERITIES
    )
    rows = [
        [
            Paragraph("<b>Total issues</b>", styles["Label"]),
            Paragraph(_paragraph_text(summary.get("total_issues", 0)), styles["Body"]),
        ],
        [
            Paragraph("<b>By agency</b>", styles["Label"]),
            Paragraph(_paragraph_text(agency_summary or "No agencies reviewed."), styles["Body"]),
        ],
        [
            Paragraph("<b>By severity</b>", styles["Label"]),
            Paragraph(_paragraph_text(severity_summary), styles["Body"]),
        ],
    ]
    table = Table(rows, colWidths=[33 * mm, 129 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4d4d4")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _agency_section(
    agency: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    agency_name = _paragraph_text(agency.get("agency", "Agency"))
    issues = agency.get("issues", [])
    elements: list[Any] = [
        CondPageBreak(65 * mm),
        Paragraph(agency_name, styles["AgencyHeading"]),
        Spacer(1, 2 * mm),
    ]

    if not issues:
        elements.append(Paragraph("No issues found for this agency.", styles["Body"]))
        return elements

    for issue in issues:
        elements.append(KeepTogether(_issue_block(issue, styles)))
        elements.append(Spacer(1, 3 * mm))

    return elements


def _issue_block(
    issue: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    metadata = [
        [
            Paragraph("<b>Severity</b>", styles["TinyLabel"]),
            Paragraph(_paragraph_text(issue.get("severity")), styles["SmallBody"]),
            Paragraph("<b>Clause</b>", styles["TinyLabel"]),
            Paragraph(_paragraph_text(issue.get("clause_reference")), styles["SmallBody"]),
        ],
        [
            Paragraph("<b>Drawing location</b>", styles["TinyLabel"]),
            Paragraph(_paragraph_text(issue.get("drawing_location")), styles["SmallBody"]),
            Paragraph("<b>Issue ID</b>", styles["TinyLabel"]),
            Paragraph(_paragraph_text(issue.get("id", "Not stored")), styles["SmallMono"]),
        ],
    ]
    metadata_table = Table(metadata, colWidths=[26 * mm, 54 * mm, 26 * mm, 56 * mm], hAlign="LEFT")
    metadata_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4d4d4")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f5f5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    elements: list[Any] = [
        Paragraph(_paragraph_text(issue.get("title", "Untitled issue")), styles["IssueTitle"]),
        Spacer(1, 2 * mm),
        metadata_table,
        Spacer(1, 2 * mm),
        Paragraph("<b>Description</b>", styles["Label"]),
        Paragraph(_paragraph_text(issue.get("description")), styles["Body"]),
        Spacer(1, 2 * mm),
        Paragraph("<b>Suggested resolution</b>", styles["Label"]),
        Paragraph(_paragraph_text(issue.get("suggested_resolution")), styles["Body"]),
    ]

    note = str(issue.get("note") or "").strip()
    if note:
        elements.extend(
            [
                Spacer(1, 2 * mm),
                Paragraph("<b>Personal note</b>", styles["Label"]),
                Paragraph(_paragraph_text(note), styles["Body"]),
            ]
        )

    elements.append(Spacer(1, 1 * mm))
    return elements


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "ComplianceTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#0a0a0a"),
            spaceAfter=0,
        ),
        "SectionHeading": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=colors.HexColor("#0f766e"),
            spaceAfter=0,
        ),
        "AgencyHeading": ParagraphStyle(
            "AgencyHeading",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#171717"),
            borderColor=colors.HexColor("#d4d4d4"),
            borderWidth=0.25,
            borderPadding=5,
            backColor=colors.HexColor("#f5f5f5"),
            spaceAfter=0,
        ),
        "IssueTitle": ParagraphStyle(
            "IssueTitle",
            parent=base["Heading4"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#171717"),
            spaceAfter=0,
        ),
        "Label": ParagraphStyle(
            "Label",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#404040"),
        ),
        "TinyLabel": ParagraphStyle(
            "TinyLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor("#525252"),
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#262626"),
            spaceAfter=0,
        ),
        "SmallBody": ParagraphStyle(
            "SmallBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#262626"),
        ),
        "SmallMono": ParagraphStyle(
            "SmallMono",
            parent=base["BodyText"],
            fontName="Courier",
            fontSize=6.5,
            leading=8,
            textColor=colors.HexColor("#262626"),
        ),
        "Footer": ParagraphStyle(
            "Footer",
            parent=base["BodyText"],
            alignment=TA_CENTER,
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#737373"),
        ),
    }


def _draw_footer(canvas: Any, doc: SimpleDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#737373"))
    page_width, _ = A4
    canvas.drawCentredString(page_width / 2, 10 * mm, f"Compliance Reviewer - Page {doc.page}")
    canvas.restoreState()


def _format_date(value: Any) -> str:
    if not value:
        return "Unknown"

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return _paragraph_text(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _paragraph_text(value: Any) -> str:
    text = "Not provided" if value is None else str(value)
    escaped = escape(text.strip() or "Not provided")
    return escaped.replace("\n", "<br/>")
