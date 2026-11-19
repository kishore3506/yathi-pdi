from contextlib import closing

from fastapi import APIRouter, Query

try:
    from ..database import get_db
except (ImportError, ValueError):
    from database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("/stats")
async def get_dashboard_stats():
    """Retrieve top-level statistics and recent customers for the dashboard."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM generated_reports")
    total_reports = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM report_jobs WHERE status = 'Completed'")
    completed_jobs = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM report_jobs WHERE status = 'Awaiting Review'")
    awaiting_review = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM report_jobs WHERE status IN ('Approved', 'Awaiting Printing') AND printed_reports < total_reports")
    awaiting_printing = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM report_jobs WHERE printed_reports > 0 AND emailed_reports = 0 AND status != 'Completed'")
    awaiting_email = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT j.*, t.template_name
        FROM report_jobs j
        LEFT JOIN pdi_templates t ON j.template_id = t.id
        ORDER BY j.id DESC
        LIMIT 10
    """)
    recent_jobs = [dict(r) for r in cursor.fetchall()]
    recent_customers = [
        row["company_name"]
        for row in cursor.execute("""
            SELECT company_name FROM report_jobs
            WHERE id IN (
                SELECT MAX(id) FROM report_jobs GROUP BY LOWER(TRIM(company_name))
            )
            ORDER BY id DESC
        """)
    ]
    conn.close()

    return {
        "total_reports_generated": total_reports,
        "completed_jobs": completed_jobs,
        "awaiting_review": awaiting_review,
        "awaiting_printing": awaiting_printing,
        "awaiting_email": awaiting_email,
        "recent_jobs": recent_jobs,
        "recent_customers": recent_customers,
    }


@router.get("/customer-jobs")
def get_customer_jobs(customer: str = Query(min_length=1, max_length=254)):
    with closing(get_db()) as conn:
        jobs = conn.execute("""
            SELECT id, job_code, model_name, product_type, product_number, status,
                   approved_reports, total_reports
            FROM report_jobs
            WHERE LOWER(TRIM(company_name)) = LOWER(TRIM(?))
            ORDER BY id DESC
        """, (customer,))
        return [dict(job) for job in jobs]
