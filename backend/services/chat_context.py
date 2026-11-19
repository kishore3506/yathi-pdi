from datetime import date
from typing import Any, Dict
import re

try:
    from ..database import CUSTOMER_CATALOG, get_db
    from .email_service import EmailService
    from .report_summary import build_daily_comparison_summary
except (ImportError, ValueError):
    from database import CUSTOMER_CATALOG, get_db
    from services.email_service import EmailService
    from services.report_summary import build_daily_comparison_summary


APPLICATION_REFERENCE = {
    "application_name": "Yathi Pumps PDI Operations Dashboard",
    "purpose": "Create, review, print, and email pre-dispatch inspection reports for Yathi Pumps OEM customers.",
    "supported_customers": [customer["name"] for customer in CUSTOMER_CATALOG],
    "customer_model_catalog": CUSTOMER_CATALOG,
    "screens": [
        "Dashboard: inspect job/report counts and recent inspection batches.",
        "New Inspection: upload a requirement, extract and edit order details, select templates, and generate reports.",
        "Templates: administrators manage registered report workbooks and field mappings. A customer can be listed in New Inspection before a template is registered.",
        "Generated Reports: select a model, download its native report where offered, or open Review.",
        "Report Editor: review model data and observations, approve reports, print, and email.",
        "Local app: the dashboard opens directly without signing in. Backups offers an automatically updated Excel copy of business records and a full ZIP backup with original files. Employee accounts are available in hosted deployments.",
        "Hosted app Employees: administrators add staff, set roles or deactivate accounts, and access data backup controls.",
    ],
    "document_extraction": {
        "new_inspection_file_types": ["JPG", "PNG", "PDF", "XLSX"],
        "assistant_report_analysis_formats": ["PDF", "XLSX", "DOCX"],
        "extracted_fields": [
            "OEM customer",
            "model name for each order line",
            "SKU/product number",
            "PO number",
            "lot size for each model",
        ],
        "review_required": "Extracted values must be reviewed before report generation; unreadable required values are not guessed.",
    },
    "workflow": [
        "Upload a purchase order or requirement, then extract and review customer, model, SKU, PO, and lot details.",
        "Review each extracted model and its lot size; each model gets its own report batch.",
        "Generate the reports, edit inspection readings, and approve each PDI report.",
        "Print approved reports or email the batch to the customer.",
        "For Havells, review and agree to the J1 legal checklist for every model before emailing.",
    ],
    "report_generation": {
        "lot_size_rules_customer": "Havells",
        "other_customers": "Generate one report per model for the full lot quantity.",
        "lot_size_rules": [
            {"minimum_lot_size": 1, "maximum_lot_size": 100, "reports": 1},
            {"minimum_lot_size": 101, "maximum_lot_size": 1200, "reports": 2},
            {"minimum_lot_size": 1201, "maximum_lot_size": 2500, "reports": 3},
            {"minimum_lot_size": 2501, "maximum_lot_size": 4000, "reports": 4},
            {"minimum_lot_size": 4001, "maximum_lot_size": None, "reports": 5},
        ],
        "quantity_allocation": "Split each Havells model's lot evenly across its reports; earlier reports receive any remainder.",
        "observation_columns": "Havells uses five sample columns G-K, numbered sequentially across reports and restarted for each model.",
        "havells_inspection_checkpoints": 56,
    },
    "template_selection": {
        "havells": "All Havells models use the revised Surface Pump workbook with existing preset observations. Choose Download Excel report for the source layout.",
        "ksb": "KSB uses its own Excel format with 22 checkpoints, 14 pump serial and observation columns, remarks, and an Accept or Reject lot decision. Choose Download Excel report for the source layout.",
        "falcon": "Falcon uses its OEM checklist with 18 OK / NOT OK entries including the conclusion. The PDF export uses the customer's supplied layout.",
        "crompton": "Crompton uses its two-page MBD R4 PDF with 16 checks, ten sample serial numbers, per-check remarks, and four possible lot decisions.",
        "stg": "STG uses the Sterling Sites Word report. Its 46 photo slots cover product, label, inner box, outer carton and four measurement groups. Open Review, use Upload or Camera in a specific cell, and choose Download Word report for the original layout.",
        "other_customers": "Use the active registered template matched to the customer and product type.",
    },
    "havells_j1_checklist": {
        "required_before_email": True,
        "default_status": "OK except the MRP row, which remains blank until reviewed.",
        "default_remarks": "-",
        "image_evidence_slots": ["Carton with label", "Product nameplate", "Technical specifications"],
    },
    "havells_surface_pump_observation_defaults": [
        "S.N. 56 defaults to OK.",
        "S.N. 52 defaults to > 50 Mic.",
        "S.N. 42 defaults to >30%.",
        "S.N. 36 RPM observation defaults to 2739 - - - 2740.",
        "S.N. 33 RPM: 2952 - - - 2981; Power: 163 - - - 162 W; Current: 0.84 - - - 0.81 A.",
        "S.N. 36 Discharge: 2711/720 - - - 2716/700; Maximum Current: 2.3 - - - 2.4 A; Maximum Power: 524 - - - 528 W.",
        "S.N. 36 Overall Efficiency readings default to N/A. Preset readings should be reviewed against the actual lot.",
    ],
    "email_delivery": "The batch email requires all selected reports to be approved. It attaches STG reports as Word files and other PDI reports as PDFs. Havells also attaches each model's agreed J1 checklist PDF.",
    "roles": {
        "inspector": "Generate and edit inspection drafts.",
        "approver": "Review and edit reports, approve them, agree Havells J1 checklists, and send approved batch email.",
        "administrator": "Perform inspection and approval tasks, manage templates and employees, and handle backups.",
        "local operator": "Create and approve inspections, manage templates, and handle backups without an employee account.",
    },
    "integrations": {
        "document_extraction_and_chat": "Google Gemini API, configured with GEMINI_API_KEY.",
        "email_delivery": "Gmail SMTP with a Google App Password or an approved n8n webhook, configured on the host.",
        "printing": "Use Open PDFs to print and print through the device viewer. Download the STG Word report to print it in Word.",
        "daily_summary": "The assistant can create a PDF comparing today's and yesterday's generated report totals.",
    },
    "assistant_permissions": "The chat can create new PDI report drafts only through the user's review-and-confirm workflow and can provide downloadable report analyses. Existing reports remain read-only; the chatbot cannot edit, approve, print, email, or delete them.",
    "troubleshooting": [
        "Chat requires GEMINI_API_KEY and a reachable supported Gemini model.",
        "A Gemini HTTP 503 usually means temporary model demand; retry after a short wait.",
        "Gmail email requires valid Gmail SMTP settings and a Google App Password.",
        "Havells email is blocked until every PDI report is approved and every model's J1 checklist is agreed.",
        "If the STG camera preview is unavailable, use localhost or HTTPS, grant camera access in the browser, or upload a JPEG, PNG or WebP up to 8 MB.",
        "When extraction omits a detail or misreads it, correct the fields before generating. The lot quantity is separate from the PO total quantity.",
        "When the app says an inspection changed after it was opened, reload it before making further edits.",
    ],
    "privacy_boundary": "Standard chat context excludes credentials, customer contact details, uploaded document contents, and full inspection readings. Uploaded requirements or selected report data are sent to Gemini only for a user-requested extraction or analysis.",
}


def build_chat_context(*, screen=None, role=None, job_id=None, report_id=None, question="") -> Dict[str, Any]:
    today = date.today().isoformat()
    conn = get_db()
    try:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) AS count FROM generated_reports"
        )
        total_reports = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM report_jobs")
        total_jobs = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM report_jobs
            GROUP BY status
            ORDER BY status
        """)
        jobs_by_status = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM generated_reports
            GROUP BY status
            ORDER BY status
        """)
        reports_by_status = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT COALESCE(legal_status, 'Not Applicable') AS status, COUNT(*) AS count
            FROM report_jobs
            GROUP BY COALESCE(legal_status, 'Not Applicable')
            ORDER BY status
        """)
        legal_checklists_by_status = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM print_jobs
            GROUP BY status
            ORDER BY status
        """)
        print_jobs_by_status = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM email_jobs
            GROUP BY status
            ORDER BY status
        """)
        email_jobs_by_status = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT c.name AS company_name, t.product_type, t.product_model,
                   t.template_name, t.primary_sheet
            FROM pdi_templates t
            JOIN companies c ON c.id = t.company_id
            WHERE t.is_active = 1
            ORDER BY c.name, t.product_type, t.template_name
        """)
        active_templates = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT c.name AS company_name, t.template_name, m.field_key,
                   m.field_label, m.target_sheet, m.target_cell,
                   m.is_required, m.validation_rule
            FROM template_field_mappings m
            JOIN pdi_templates t ON t.id = m.template_id
            JOIN companies c ON c.id = t.company_id
            WHERE t.is_active = 1
            ORDER BY c.name, t.template_name, m.field_key
        """)
        active_field_mappings = [dict(row) for row in cursor.fetchall()]

        comparison = build_daily_comparison_summary(as_of_date=date.fromisoformat(today), connection=conn)
        mailer = EmailService()
        reports_today_by_customer = [
            {"company_name": row["customer"], "reports_generated": row["today"]}
            for row in comparison["customer_breakdown"]
            if row["today"]
        ]
        reports_today_by_model = [
            {
                "company_name": row["customer"],
                "model_name": row["model"],
                "reports_generated": row["today"],
            }
            for row in comparison["model_breakdown"]
            if row["today"]
        ]

        result = {
            "as_of_local_date": today,
            "viewer": {"screen": screen, "role": role},
            "email_provider": {"configured": mailer.is_configured, "provider": mailer.provider},
            "reports_generated_today": comparison["reports_today"],
            "reports_generated_yesterday": comparison["reports_yesterday"],
            "difference_from_yesterday": comparison["report_difference"],
            "jobs_created_today": comparison["jobs_today"],
            "jobs_created_yesterday": comparison["jobs_yesterday"],
            "reports_generated_all_time": total_reports,
            "jobs_created_all_time": total_jobs,
            "jobs_by_status": jobs_by_status,
            "reports_by_status": reports_by_status,
            "legal_checklists_by_status": legal_checklists_by_status,
            "print_jobs_by_status": print_jobs_by_status,
            "email_jobs_by_status": email_jobs_by_status,
            "reports_today_by_customer": reports_today_by_customer,
            "reports_today_by_model": reports_today_by_model,
            "daily_report_comparison": comparison,
            "application_reference": {
                **APPLICATION_REFERENCE,
                "active_templates": active_templates,
                "active_template_field_mappings": active_field_mappings,
            },
        }
        if job_id or report_id or re.search(r"\b(?:JOB-YATHI-|[A-Z0-9]+_PDI_)", question, re.I):
            result["inspection_lookup"] = _inspection_context(cursor, job_id, report_id, question)
        return result
    finally:
        conn.close()


def _inspection_context(cursor, job_id, report_id, question):
    job_codes = re.findall(r"\bJOB-YATHI-[A-Z0-9-]+\b", question, re.I)
    report_codes = re.findall(r"\b[A-Z0-9]+_PDI_[\w-]+\b", question, re.I)
    rows = cursor.execute(
        """
        SELECT j.job_code, j.company_name, j.model_name, j.lot_size, j.status AS job_status,
               j.legal_status, r.report_code, r.status AS report_status
        FROM report_jobs j JOIN generated_reports r ON r.job_id = j.id
        WHERE j.id = ? OR r.id = ? OR UPPER(j.job_code) = ? OR UPPER(r.report_code) = ?
        ORDER BY r.id DESC LIMIT 12
        """,
        (job_id, report_id, job_codes[-1].upper() if job_codes else None,
         report_codes[-1].upper() if report_codes else None),
    ).fetchall()
    return [dict(row) for row in rows]
