import os
import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool
from typing import Optional, List, Dict, Any
from openpyxl import load_workbook

try:
    from ..database import CUSTOMER_CATALOG, get_db
    from ..schemas import (
        ReportGenerateRequest,
        ReportUpdateRequest,
        ReportApprovalRequest,
        LegalChecklistAgreementRequest,
        EmailRequest,
    )
    from ..services.report_generator import ReportGenerator
    from ..services.email_service import EmailService
    from ..services.excel_filler import ExcelFiller
    from ..services.excel_reader import ExcelReader
    from ..services import crompton_email_scans, crompton_report
    from ..services.template_matcher import TemplateMatcher
    from ..services.stg_report import (
        DOCX_MIME_TYPE, MAX_PHOTO_BYTES, PHOTO_SLOTS, normalize_photo, read_photo, write_report as write_stg_report,
    )
    from ..settings import REPORTS_DIR
except (ImportError, ValueError):
    from database import CUSTOMER_CATALOG, get_db
    from schemas import (
        ReportGenerateRequest,
        ReportUpdateRequest,
        ReportApprovalRequest,
        LegalChecklistAgreementRequest,
        EmailRequest,
    )
    from services.report_generator import ReportGenerator
    from services.email_service import EmailService
    from services.excel_filler import ExcelFiller
    from services.excel_reader import ExcelReader
    from services import crompton_email_scans, crompton_report
    from services.template_matcher import TemplateMatcher
    from services.stg_report import (
        DOCX_MIME_TYPE, MAX_PHOTO_BYTES, PHOTO_SLOTS, normalize_photo, read_photo, write_report as write_stg_report,
    )
    from settings import REPORTS_DIR

router = APIRouter(prefix="/api/reports", tags=["Reports"])

os.makedirs(REPORTS_DIR, exist_ok=True)

generator = ReportGenerator()
emailer = EmailService()
filler = ExcelFiller()
reader = ExcelReader()
_report_write_lock = threading.Lock()

@router.post("/generate")
async def generate_reports(req: ReportGenerateRequest):
    """Generate PDI reports for a model according to the customer's lot-size rules."""
    min_lot = 0 if req.company_name.strip().casefold() == "crompton" else 1
    if not min_lot <= req.lot_size <= 1_000_000:
        raise HTTPException(status_code=400, detail=f"Lot size must be an integer from {min_lot} to 1,000,000.")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM companies WHERE LOWER(name) = LOWER(?)", (req.company_name.strip(),))
    comp = cursor.fetchone()
    conn.close()

    if not comp:
        raise HTTPException(status_code=400, detail=f"Customer '{req.company_name}' is missing from the PDI customer catalog.")

    job_data = req.dict()
    if min_lot == 0 and req.requirement_id is None:
        models = next(customer["models"] for customer in CUSTOMER_CATALOG if customer["name"] == "Crompton")
        if not any(model["name"] == req.model_name and model["type"] == req.product_type for model in models):
            raise HTTPException(status_code=400, detail="Select a model and type from the Crompton catalog.")
        match = TemplateMatcher().match_template("Crompton", req.product_type, req.model_name)
        if match["template_id"] != req.template_id or match["primary_sheet"] != crompton_report.SHEET_NAME:
            raise HTTPException(status_code=400, detail="The Crompton inspection report template is required.")

    try:
        result = generator.generate_batch_reports(job_data, REPORTS_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result

@router.get("")
async def list_report_jobs():
    """List all report generation jobs."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT j.*, t.template_name
        FROM report_jobs j
        LEFT JOIN pdi_templates t ON j.template_id = t.id
        ORDER BY j.id DESC
    """)
    jobs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jobs

@router.get("/jobs/{job_id}")
async def get_job_details(job_id: int):
    """Get full details of a specific job including all generated reports."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT j.*, t.template_name
        FROM report_jobs j
        LEFT JOIN pdi_templates t ON j.template_id = t.id
        WHERE j.id = ?
    """, (job_id,))
    job = cursor.fetchone()
    if not job:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found")

    job_dict = dict(job)
    if job_dict.get("requirement_id") is not None:
        cursor.execute("""
            SELECT id, job_code, model_name, product_number, po_number, lot_size,
                   total_reports, approved_reports, status, legal_status
            FROM report_jobs
            WHERE requirement_id = ?
            ORDER BY id ASC
        """, (job_dict["requirement_id"],))
        job_dict["model_jobs"] = [dict(row) for row in cursor.fetchall()]
    else:
        job_dict["model_jobs"] = [{
            key: job_dict.get(key)
            for key in (
                "id", "job_code", "model_name", "product_number", "po_number",
                "lot_size", "total_reports", "approved_reports", "status", "legal_status",
            )
        }]

    cursor.execute("SELECT * FROM generated_reports WHERE job_id = ? ORDER BY unit_index ASC", (job_id,))
    reports = []
    for r in cursor.fetchall():
        rd = dict(r)
        try:
            rd["report_data"] = json.loads(rd["report_data_json"])
        except Exception:
            rd["report_data"] = {}
        reports.append(rd)

    job_dict["reports"] = reports
    conn.close()
    if (
        str(job_dict["company_name"]).strip().casefold() == "havells"
        and not job_dict.get("legal_excel_path")
        and reports
    ):
        report_path = reports[0]["excel_path"]
        if not os.path.isfile(report_path):
            raise HTTPException(status_code=404, detail="A PDI workbook is missing; the J1 legal checklist cannot be created.")
        legal_excel_path = os.path.join(
            os.path.dirname(report_path),
            f"{job_dict['job_code']}_Legal_J1.xlsx",
        )
        legal_pdf_path = os.path.splitext(legal_excel_path)[0] + ".pdf"
        generator.legal_checklist.generate_workbook(job_dict, legal_excel_path)
        pdi_reports_complete = all(
            report["status"] in {"Approved", "Emailed"}
            for report in reports
        )
        legal_status = "Awaiting Review"
        job_status = "Awaiting Legal Review" if pdi_reports_complete else job_dict["status"]

        conn = get_db()
        conn.execute("""
            UPDATE report_jobs
            SET legal_excel_path = ?, legal_pdf_path = ?, legal_status = ?, status = ?, updated_at = ?
            WHERE id = ?
        """, (
            legal_excel_path,
            legal_pdf_path,
            legal_status,
            job_status,
            datetime.now().isoformat(),
            job_id,
        ))
        conn.commit()
        conn.close()

        job_dict.update({
            "legal_excel_path": legal_excel_path,
            "legal_pdf_path": legal_pdf_path,
            "legal_status": legal_status,
            "status": job_status,
        })
        for model_job in job_dict["model_jobs"]:
            if model_job["id"] == job_id:
                model_job["legal_status"] = legal_status
                model_job["status"] = job_status

    if job_dict.get("legal_excel_path"):
        job_dict["legal_checklist"] = generator.legal_checklist.read_checklist(
            job_dict["legal_excel_path"]
        )
    return job_dict

@router.post("/jobs/{job_id}/legal/agree")
async def agree_legal_checklist(job_id: int, req: LegalChecklistAgreementRequest):
    """Saves and agrees to the J1 legal checklist for a Havells model job."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM report_jobs WHERE id = ?", (job_id,))
    job = cursor.fetchone()
    if not job:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found")
    job = dict(job)
    if str(job["company_name"]).strip().casefold() != "havells" or not job["legal_excel_path"]:
        conn.close()
        raise HTTPException(status_code=400, detail="This job has no Havells J1 legal checklist.")
    if not req.agreed:
        conn.close()
        raise HTTPException(status_code=400, detail="Confirm agreement with the legal checklist before continuing.")
    if not os.path.isfile(job["legal_excel_path"]):
        conn.close()
        raise HTTPException(status_code=404, detail="J1 legal checklist workbook was not found.")
    cursor.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status IN ('Approved', 'Emailed') THEN 1 ELSE 0 END) AS approved
        FROM generated_reports WHERE job_id = ?
    """, (job_id,))
    report_counts = cursor.fetchone()
    conn.close()
    if not report_counts["total"] or report_counts["approved"] != report_counts["total"]:
        raise HTTPException(status_code=409, detail="Approve every PDI report for this model before reviewing its legal checklist.")

    try:
        decision = generator.legal_checklist.save_review(
            job["legal_excel_path"],
            [item.model_dump() for item in req.items],
            req.mrp_value,
            req.images.model_dump() if req.images else None,
        )
        legal_pdf_path = job["legal_pdf_path"] or os.path.splitext(job["legal_excel_path"])[0] + ".pdf"
        generator.legal_checklist.create_pdf(job["legal_excel_path"], legal_pdf_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now_str = datetime.now().isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE report_jobs
        SET legal_pdf_path = ?, legal_status = 'Agreed', status = 'Approved', updated_at = ?
        WHERE id = ?
    """, (legal_pdf_path, now_str, job_id))
    cursor.execute("""
        INSERT INTO audit_logs (job_id, action, performed_by, details_json, created_at)
        VALUES (?, 'AGREE_LEGAL_CHECKLIST', 'Employee', ?, ?)
    """, (job_id, json.dumps({"decision": decision}), now_str))
    conn.commit()
    conn.close()

    return {
        "job_id": job_id,
        "legal_status": "Agreed",
        "decision": decision,
        "legal_checklist": generator.legal_checklist.read_checklist(job["legal_excel_path"]),
    }

@router.get("/{report_id}")
async def get_single_report(report_id: int):
    """Get detailed inspection content and status for a single report."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, j.job_code, j.company_name, j.product_type, j.model_name, j.product_number, j.po_number, j.lot_size, j.customer_name
        FROM generated_reports r
        JOIN report_jobs j ON r.job_id = j.id
        WHERE r.id = ?
    """, (report_id,))
    rep = cursor.fetchone()
    conn.close()
    if not rep:
        raise HTTPException(status_code=404, detail="Report not found")

    rep_dict = dict(rep)
    try:
        rep_dict["report_data"] = json.loads(rep_dict["report_data_json"])
    except Exception:
        rep_dict["report_data"] = {}

    return rep_dict

@router.patch("/{report_id}")
async def update_report(report_id: int, req: ReportUpdateRequest):
    """Save editable report fields and inspection readings."""
    return await run_in_threadpool(save_report_update, report_id, req)


@router.patch("/{report_id}/photos/{slot}")
async def update_report_photo(
    report_id: int,
    slot: str,
    expected_revision: int = Form(..., ge=1),
    photo: Optional[UploadFile] = File(None),
):
    if slot not in PHOTO_SLOTS:
        raise HTTPException(status_code=404, detail="Photo slot not found.")
    content = None
    if photo is not None:
        try:
            raw = await photo.read(MAX_PHOTO_BYTES + 1)
        finally:
            await photo.close()
        if len(raw) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Choose a photo of 8 MB or less.")
        try:
            content = await run_in_threadpool(normalize_photo, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await run_in_threadpool(
        save_report_update, report_id, ReportUpdateRequest(expected_revision=expected_revision),
        photo_change=(slot, content),
    )


@router.get("/{report_id}/photos/{slot}")
def get_report_photo(report_id: int, slot: str):
    if slot not in PHOTO_SLOTS:
        raise HTTPException(status_code=404, detail="Photo slot not found.")
    conn = get_db()
    try:
        report = conn.execute("SELECT excel_path FROM generated_reports WHERE id = ?", (report_id,)).fetchone()
    finally:
        conn.close()
    if not report or not os.path.isfile(report["excel_path"]) or not report["excel_path"].lower().endswith(".docx"):
        raise HTTPException(status_code=404, detail="STG report not found.")
    content = read_photo(report["excel_path"], slot)
    if content is None:
        raise HTTPException(status_code=404, detail="No photo is saved in this slot.")
    return Response(content=content, media_type="image/jpeg")


def save_report_update(report_id, req, *, photo_change=None):
    with _report_write_lock:
        conn = get_db()
        temporary_path = None
        backup_path = None
        replaced_original = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM generated_reports WHERE id = ?", (report_id,))
            rep = cursor.fetchone()
            if not rep:
                raise HTTPException(status_code=404, detail="Report not found")
            if rep["revision"] != req.expected_revision:
                raise HTTPException(
                    status_code=409,
                    detail="This inspection changed after you opened it. Reload it and review the latest saved values.",
                )

            excel_path = rep["excel_path"]
            if not os.path.isfile(excel_path):
                raise HTTPException(status_code=404, detail="The inspection file is unavailable.")
            is_stg_document = excel_path.lower().endswith(".docx")
            if photo_change is not None and not is_stg_document:
                raise HTTPException(status_code=404, detail="Photo slots are available for STG reports.")
            if is_stg_document and rep["status"] in {"Approved", "Emailed"}:
                raise HTTPException(status_code=409, detail="This STG report has already been approved.")
            job_id = rep["job_id"]
            job = cursor.execute(
                "SELECT * FROM report_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            existing_data = json.loads(rep["report_data_json"])
            header_data = existing_data.get("header_data", {})
            if req.header_data:
                for key, value in req.header_data.items():
                    if value is not None:
                        header_data[key] = value

            final_judgment = req.final_judgment or header_data.get("final_judgment") or ""
            reject_reason = req.reject_reason or header_data.get("reject_reason") or ""
            update_dict = {
                "company_name": job["company_name"],
                "supplier_name": header_data.get("supplier_name"),
                "supplier_location": header_data.get("supplier_location"),
                "product_number": header_data.get("sku_no") or job["product_number"],
                "model_name": header_data.get("model_name") or job["model_name"] or job["product_type"],
                "po_number": header_data.get("po_number") or job["po_number"],
                "lot_size": header_data.get("lot_qty") or job["lot_size"],
                "po_total_qty": header_data.get("po_total_qty"),
                "inspected_by": header_data.get("inspected_by"),
                "approved_by": header_data.get("approved_by"),
                "inspection_date": header_data.get("inspection_date"),
                "lot_dispatch_date": header_data.get("lot_dispatch_date"),
                "final_judgment": final_judgment,
                "reject_reason": reject_reason,
                "total_dispatched_qty": header_data.get("total_dispatched_qty"),
            }
            for field in ("prepared_by", "power_rating", "incoming_date", "invoice_number", "special_remarks"):
                if field in header_data:
                    update_dict[field] = header_data[field]
            if existing_data.get("sample_columns"):
                update_dict["final_judgment"] = req.final_judgment

            temporary_path = f"{excel_path}.{uuid.uuid4().hex}.tmp"
            backup_path = f"{excel_path}.{uuid.uuid4().hex}.bak"
            shutil.copy2(excel_path, backup_path)
            if is_stg_document:
                fresh_data = write_stg_report(excel_path, temporary_path, req.header_data or {}, photo_change=photo_change)
            elif existing_data.get("primary_sheet") == crompton_report.SHEET_NAME:
                temporary_path += ".xlsx"
                values = dict(req.header_data or {})
                if "lot_qty" in values:
                    lot = str(values["lot_qty"]).strip()
                    if not re.fullmatch(r"[0-9]{1,7}", lot) or int(lot) > 1_000_000:
                        raise HTTPException(status_code=400, detail="Lot size must be an integer from 0 to 1,000,000.")
                    values["lot_qty"] = int(lot)
                if req.final_judgment is not None:
                    values["final_judgment"] = req.final_judgment
                if all(sheet in existing_data.get("sheet_names", []) for sheet in crompton_report.NATIVE_SHEETS):
                    crompton_report.write_native_workbook(
                        excel_path, temporary_path, values, req.observation_readings
                    )
                else:
                    crompton_report.write_workbook(
                        load_workbook(excel_path), temporary_path, values, req.observation_readings
                    )
                fresh_data = reader.read_report(temporary_path)
                fresh_data["header_data"].setdefault("sku_no", header_data.get("sku_no", job["product_number"]))
                fresh_data["header_data"].setdefault("po_number", header_data.get("po_number", job["po_number"]))
            else:
                temporary_path += ".xlsx"
                filler.populate_template(
                    template_file_path=excel_path,
                    output_file_path=temporary_path,
                    template_id=job["template_id"],
                    data=update_dict,
                    observation_overrides=req.observation_readings,
                    unit_index=rep["unit_index"],
                    serial_number=rep["serial_number"],
                )
                fresh_data = reader.read_report(temporary_path)
            now_str = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE generated_reports
                SET report_data_json = ?, updated_at = ?, revision = revision + 1
                WHERE id = ? AND revision = ?
                """,
                (json.dumps(fresh_data), now_str, report_id, req.expected_revision),
            )
            if cursor.rowcount != 1:
                raise HTTPException(
                    status_code=409,
                    detail="This inspection changed after you opened it. Reload it and review the latest saved values.",
                )
            cursor.execute(
                """
                INSERT INTO audit_logs (job_id, report_id, action, performed_by, details_json, created_at)
                VALUES (?, ?, 'EDIT_REPORT', 'Employee', ?, ?)
                """,
                (
                    job_id, report_id,
                    json.dumps({"photo_slot": photo_change[0], "saved": photo_change[1] is not None}
                               if photo_change else {"judgment": final_judgment}),
                    now_str,
                ),
            )
            os.replace(temporary_path, excel_path)
            replaced_original = True
            conn.commit()
        except Exception:
            conn.rollback()
            if replaced_original and backup_path and os.path.exists(backup_path):
                os.replace(backup_path, excel_path)
            raise
        finally:
            conn.close()
            for path in (temporary_path, backup_path):
                if path and os.path.exists(path):
                    os.remove(path)

    return {
        "report_id": report_id,
        "status": "Updated",
        "revision": req.expected_revision + 1,
        "report_data": fresh_data
    }

@router.post("/{report_id}/approve")
async def approve_report(report_id: int, req: ReportApprovalRequest):
    """Approves a generated report."""
    conn = get_db()
    cursor = conn.cursor()
    conn.execute("BEGIN IMMEDIATE")
    cursor.execute("SELECT * FROM generated_reports WHERE id = ?", (report_id,))
    rep = cursor.fetchone()
    if not rep:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=404, detail="Report not found")
    if rep["revision"] != req.expected_revision:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=409, detail="This inspection changed after you opened it. Reload it before approving.")

    now_str = datetime.now().isoformat()
    cursor.execute(
        "UPDATE generated_reports SET status = 'Approved', updated_at = ?, revision = revision + 1 WHERE id = ? AND revision = ?",
        (now_str, report_id, req.expected_revision),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=409, detail="This inspection changed after you opened it. Reload it before approving.")
    
    job_id = rep["job_id"]
    cursor.execute("SELECT company_name, legal_status FROM report_jobs WHERE id = ?", (job_id,))
    job = cursor.fetchone()
    cursor.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status IN ('Approved', 'Emailed') THEN 1 ELSE 0 END) AS approved
        FROM generated_reports WHERE job_id = ?
    """, (job_id,))
    st = cursor.fetchone()
    if st["approved"] == st["total"]:
        needs_legal_review = (
            str(job["company_name"]).strip().casefold() == "havells"
            and job["legal_status"] != "Agreed"
        )
        new_job_status = "Awaiting Legal Review" if needs_legal_review else "Approved"
    else:
        new_job_status = "Awaiting Review"
    cursor.execute("UPDATE report_jobs SET approved_reports = ?, status = ?, updated_at = ? WHERE id = ?", (st["approved"], new_job_status, now_str, job_id))

    cursor.execute("""
        INSERT INTO audit_logs (job_id, report_id, action, performed_by, details_json, created_at)
        VALUES (?, ?, 'APPROVE_REPORT', 'Employee', 'Approved inspection findings', ?)
    """, (job_id, report_id, now_str))

    conn.commit()
    conn.close()

    return {
        "report_id": report_id,
        "status": "Approved",
        "job_status": new_job_status,
        "revision": req.expected_revision + 1,
    }

@router.get("/{report_id}/download/excel")
@router.get("/{report_id}/download/document")
async def download_excel(report_id: int):
    """Download the report in its editable format."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT excel_path, report_code FROM generated_reports WHERE id = ?", (report_id,))
    rep = cursor.fetchone()
    conn.close()
    if not rep or not os.path.exists(rep["excel_path"]):
        raise HTTPException(status_code=404, detail="Report file not found.")

    is_stg_document = rep["excel_path"].lower().endswith(".docx")
    extension, media_type = (
        ("docx", DOCX_MIME_TYPE) if is_stg_document
        else ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    )
    return FileResponse(
        rep["excel_path"],
        filename=f"{rep['report_code']}.{extension}",
        media_type=media_type,
    )

@router.get("/{report_id}/download/pdf")
async def download_pdf(report_id: int):
    """Download individual PDF report copy."""
    try:
        pdf_path = await run_in_threadpool(generator.convert_to_pdf, report_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=500, detail="Failed to generate PDF copy")

    return FileResponse(
        pdf_path,
        filename=os.path.basename(pdf_path),
        media_type="application/pdf"
    )

@router.get("/{report_id}/open/pdf")
async def open_pdf(report_id: int):
    """Open a generated PDF in the user's browser for device-side printing."""
    try:
        pdf_path = await run_in_threadpool(generator.convert_to_pdf, report_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF report file not found.")
    response = FileResponse(pdf_path, media_type="application/pdf")
    response.headers["Content-Disposition"] = "inline"
    response.headers["Cache-Control"] = "private, no-store"
    return response

@router.get("/jobs/{job_id}/download/zip")
async def download_job_zip(job_id: int):
    """Download all reports for a job bundled in a ZIP file."""
    zip_path = generator.create_zip_archive(job_id)
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=500, detail="Failed to create ZIP package")

    return FileResponse(
        zip_path,
        filename=os.path.basename(zip_path),
        media_type="application/zip"
    )

@router.get("/printers/list")
async def list_printers():
    """Cloud hosts cannot enumerate printers connected to an employee device."""
    raise HTTPException(
        status_code=410,
        detail="Cloud printing is unavailable. Open or download the PDF and print from your device.",
    )

@router.post("/jobs/{job_id}/print")
async def print_job(job_id: int):
    """Physical printing is an action taken by the employee's device, not this host."""
    raise HTTPException(
        status_code=410,
        detail="Cloud printing is unavailable. Open or download the PDF and print from your device.",
    )

@router.get("/jobs/{job_id}/email-scans")
def list_email_scans(job_id: int):
    return crompton_email_scans.list_scans(job_id)


@router.post("/jobs/{job_id}/email-scans", status_code=201)
async def upload_email_scan(job_id: int, image: UploadFile = File(...)):
    try:
        content = await image.read(crompton_email_scans.MAX_SCAN_BYTES + 1)
    finally:
        await image.close()
    if len(content) > crompton_email_scans.MAX_SCAN_BYTES:
        raise HTTPException(413, "Choose an image of 8 MB or less.")
    return await run_in_threadpool(crompton_email_scans.add_scan, job_id, content)


@router.get("/jobs/{job_id}/email-scans/{scan_id}")
def open_email_scan(job_id: int, scan_id: int):
    return Response(crompton_email_scans.get_scan(job_id, scan_id), media_type="image/jpeg")


@router.delete("/jobs/{job_id}/email-scans/{scan_id}", status_code=204)
def delete_email_scan(job_id: int, scan_id: int):
    crompton_email_scans.remove_scan(job_id, scan_id)
    return Response(status_code=204)


@router.post("/email")
async def send_reports_email(req: EmailRequest):
    """Sends reports through Gmail SMTP or skips email."""
    result = await run_in_threadpool(
        emailer.send_customer_email,
        job_id=req.job_id,
        customer_email=req.customer_email,
        customer_name=req.customer_name,
        from_email=req.from_email,
        to_email=req.to_email,
        subject=req.subject,
        message=req.message,
        report_ids=req.report_ids,
        skip=req.skip,
    )
    return result

@router.get("/email/config")
async def get_email_config():
    """Returns non-secret Gmail sender configuration for the email dialog."""
    return {
        "from_email": emailer.default_from_email,
        "configured": emailer.is_configured,
        "provider": emailer.provider,
    }
