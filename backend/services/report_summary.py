from datetime import date, timedelta
from io import BytesIO
from typing import Any, Dict, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    from ..database import get_db
except (ImportError, ValueError):
    from database import get_db


def build_daily_comparison_summary(
    as_of_date: Optional[date] = None,
    connection=None,
) -> Dict[str, Any]:
    today = as_of_date or date.today()
    yesterday = today - timedelta(days=1)
    today_text = today.isoformat()
    yesterday_text = yesterday.isoformat()
    owns_connection = connection is None
    conn = connection or get_db()

    try:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                date(r.created_at) AS report_date,
                j.company_name AS customer,
                COALESCE(NULLIF(j.model_name, ''), j.product_type) AS model,
                COUNT(r.id) AS report_count
            FROM generated_reports r
            JOIN report_jobs j ON j.id = r.job_id
            WHERE date(r.created_at) IN (?, ?)
            GROUP BY
                date(r.created_at),
                j.company_name,
                COALESCE(NULLIF(j.model_name, ''), j.product_type)
            ORDER BY j.company_name, model
        """, (today_text, yesterday_text))
        rows = cursor.fetchall()

        report_counts = {today_text: 0, yesterday_text: 0}
        customer_counts = {}
        model_counts = {}
        for row in rows:
            row = dict(row)
            report_date = row["report_date"]
            customer = row["customer"] or "Unknown"
            model = row["model"] or "Unknown"
            count = row["report_count"]
            report_counts[report_date] += count
            customer_counts.setdefault(customer, {today_text: 0, yesterday_text: 0})
            customer_counts[customer][report_date] += count
            model_key = (customer, model)
            model_counts.setdefault(model_key, {today_text: 0, yesterday_text: 0})
            model_counts[model_key][report_date] += count

        cursor.execute("""
            SELECT date(created_at) AS job_date, COUNT(*) AS job_count
            FROM report_jobs
            WHERE date(created_at) IN (?, ?)
            GROUP BY date(created_at)
        """, (today_text, yesterday_text))
        job_counts = {today_text: 0, yesterday_text: 0}
        for row in cursor.fetchall():
            job_counts[row["job_date"]] = row["job_count"]

        reports_today = report_counts[today_text]
        reports_yesterday = report_counts[yesterday_text]
        difference = reports_today - reports_yesterday
        percentage_change = (
            round(difference * 100 / reports_yesterday, 1)
            if reports_yesterday
            else None
        )

        return {
            "today": today_text,
            "yesterday": yesterday_text,
            "reports_today": reports_today,
            "reports_yesterday": reports_yesterday,
            "report_difference": difference,
            "report_percentage_change": percentage_change,
            "jobs_today": job_counts[today_text],
            "jobs_yesterday": job_counts[yesterday_text],
            "job_difference": job_counts[today_text] - job_counts[yesterday_text],
            "customer_breakdown": [
                {
                    "customer": customer,
                    "today": counts[today_text],
                    "yesterday": counts[yesterday_text],
                    "difference": counts[today_text] - counts[yesterday_text],
                }
                for customer, counts in sorted(customer_counts.items())
            ],
            "model_breakdown": [
                {
                    "customer": customer,
                    "model": model,
                    "today": counts[today_text],
                    "yesterday": counts[yesterday_text],
                    "difference": counts[today_text] - counts[yesterday_text],
                }
                for (customer, model), counts in sorted(model_counts.items())
            ],
        }
    finally:
        if owns_connection:
            conn.close()


def render_daily_comparison_pdf(summary: Dict[str, Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        title=f"PDI Report Summary {summary['today']} vs {summary['yesterday']}",
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    body_style = styles["BodyText"]
    heading_style = styles["Heading1"]

    def cell(value, bold=False):
        text = escape(str(value))
        if bold:
            text = f"<b>{text}</b>"
        return Paragraph(text, body_style)

    def signed(value):
        return f"+{value}" if value > 0 else str(value)

    story = [
        Paragraph("Daily PDI Report Generation Summary", heading_style),
        Paragraph(
            f"Comparison: {escape(summary['today'])} vs {escape(summary['yesterday'])}",
            body_style,
        ),
        Spacer(1, 14),
    ]

    total_rows = [
        [cell("Metric", True), cell(summary["today"], True), cell(summary["yesterday"], True), cell("Change", True)],
        [cell("Generated reports"), cell(summary["reports_today"]), cell(summary["reports_yesterday"]), cell(signed(summary["report_difference"]))],
        [cell("Inspection jobs"), cell(summary["jobs_today"]), cell(summary["jobs_yesterday"]), cell(signed(summary["job_difference"]))],
    ]
    total_table = Table(total_rows, colWidths=[220, 130, 130, 120], repeatRows=1)
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#eff6ff")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([total_table, Spacer(1, 18), Paragraph("Breakdown by customer and model", styles["Heading2"]), Spacer(1, 8)])

    breakdown_rows = [[
        cell("Customer", True),
        cell("Model", True),
        cell("Today", True),
        cell("Yesterday", True),
        cell("Change", True),
    ]]
    for row in summary["model_breakdown"]:
        breakdown_rows.append([
            cell(row["customer"]),
            cell(row["model"]),
            cell(row["today"]),
            cell(row["yesterday"]),
            cell(signed(row["difference"])),
        ])
    if not summary["model_breakdown"]:
        breakdown_rows.append([cell("No reports generated on either date."), "", "", "", ""])

    breakdown_table = Table(
        breakdown_rows,
        colWidths=[130, 350, 90, 90, 90],
        repeatRows=1,
    )
    breakdown_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(breakdown_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("Source: read-only generated report records in the PDI application.", styles["Italic"]))
    document.build(story)
    return buffer.getvalue()
