from contextlib import closing

from fastapi import HTTPException

try:
    from ..database import get_db
    from .stg_report import normalize_photo
except ImportError:
    from database import get_db
    from services.stg_report import normalize_photo


MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_SCAN_TOTAL_BYTES = 10 * 1024 * 1024
MAX_SCANS = 10


def scan_filename(scan_id):
    return f"Crompton-scan-{scan_id:03}.jpg"


def _check_approved_job(conn, job_id):
    job = conn.execute("""
        SELECT company_name, total_reports,
            (SELECT COUNT(*) FROM generated_reports WHERE job_id = report_jobs.id) AS actual_count,
            (SELECT COUNT(*) FROM generated_reports WHERE job_id = report_jobs.id
                AND status IN ('Approved', 'Emailed')) AS approved_count
        FROM report_jobs WHERE id = ?
    """, (job_id,)).fetchone()
    if not job or job["company_name"].strip().casefold() != "crompton":
        raise HTTPException(404, "Crompton inspection not found.")
    if not job["actual_count"] or job["actual_count"] != job["approved_count"] or (
        job["total_reports"] and job["actual_count"] != job["total_reports"]
    ):
        raise HTTPException(409, "Approve both Crompton reports before adding email images.")


def list_scans(job_id):
    with closing(get_db()) as conn:
        _check_approved_job(conn, job_id)
        rows = conn.execute(
            "SELECT id FROM crompton_email_scans WHERE job_id = ? ORDER BY id", (job_id,)
        ).fetchall()
    return [{"id": row["id"], "filename": scan_filename(row["id"])} for row in rows]


def add_scan(job_id, content):
    with closing(get_db()) as conn:
        _check_approved_job(conn, job_id)
        try:
            image = normalize_photo(content, max_edge=2400)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            _check_approved_job(conn, job_id)
            totals = conn.execute("""
                SELECT COUNT(*) AS count, COALESCE(SUM(LENGTH(image)), 0) AS bytes
                FROM crompton_email_scans WHERE job_id = ?
            """, (job_id,)).fetchone()
            if totals["count"] >= MAX_SCANS or totals["bytes"] + len(image) > MAX_SCAN_TOTAL_BYTES:
                raise HTTPException(413, "Each inspection can include up to 10 images and 10 MB of scan attachments.")
            scan_id = conn.execute(
                "INSERT INTO crompton_email_scans (job_id, image) VALUES (?, ?)", (job_id, image)
            ).lastrowid
    return {"id": scan_id, "filename": scan_filename(scan_id)}


def get_scan(job_id, scan_id):
    with closing(get_db()) as conn:
        _check_approved_job(conn, job_id)
        scan = conn.execute(
            "SELECT image FROM crompton_email_scans WHERE job_id = ? AND id = ?", (job_id, scan_id)
        ).fetchone()
    if scan is None:
        raise HTTPException(404, "Inspection scan not found.")
    return scan["image"]


def remove_scan(job_id, scan_id):
    with closing(get_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        _check_approved_job(conn, job_id)
        result = conn.execute(
            "DELETE FROM crompton_email_scans WHERE job_id = ? AND id = ?", (job_id, scan_id)
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Inspection scan not found.")
