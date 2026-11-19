import html
import json
import logging
import os
import re
import smtplib
import ssl
import base64
from datetime import datetime
from email.message import EmailMessage
from typing import Dict, Any, List, Optional

try:
    from ..database import get_db
    from .crompton_email_scans import scan_filename
    from .report_generator import ReportGenerator
    from .stg_report import DOCX_MIME_TYPE
except (ImportError, ValueError):
    from database import get_db
    from services.crompton_email_scans import scan_filename
    from services.report_generator import ReportGenerator
    from services.stg_report import DOCX_MIME_TYPE

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SMTP_TIMEOUT_SECONDS = 300


def _smtp_failure_reason(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "SMTP server disconnected"
    if isinstance(exc, smtplib.SMTPResponseException):
        response = exc.smtp_error
        if isinstance(response, bytes):
            response = response.decode("utf-8", errors="replace")
        response = " ".join(str(response).split())[:200]
        detail = f"SMTP server returned {exc.smtp_code}"
        return f"{detail}: {response}" if response else detail
    if isinstance(exc, TimeoutError):
        return "SMTP connection timed out"
    if isinstance(exc, ConnectionRefusedError):
        return "SMTP connection was refused"
    return f"SMTP transport error ({type(exc).__name__})"


class EmailService:
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: Optional[str] = None,
        allowed_from_emails: Optional[List[str]] = None,
        n8n_webhook_url: Optional[str] = None,
        n8n_webhook_token: Optional[str] = None,
        n8n_from_email: Optional[str] = None,
    ):
        self.smtp_host = smtp_host or os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(
            smtp_port if smtp_port is not None else os.getenv("GMAIL_SMTP_PORT", "587")
        )
        self.smtp_use_ssl = self.smtp_port == 465
        self.smtp_username = (
            smtp_username if smtp_username is not None else os.getenv("GMAIL_SMTP_USERNAME", "")
        ).strip()
        self.smtp_password = (
            smtp_password if smtp_password is not None else os.getenv("GMAIL_APP_PASSWORD", "")
        ).replace(" ", "")
        self.n8n_webhook_url = (
            n8n_webhook_url if n8n_webhook_url is not None else os.getenv("N8N_WEBHOOK_URL", "")
        ).strip()
        self.n8n_webhook_token = (
            n8n_webhook_token if n8n_webhook_token is not None else os.getenv("N8N_WEBHOOK_TOKEN", "")
        ).strip()
        configured_n8n_from = n8n_from_email or os.getenv("N8N_FROM_EMAIL", "")
        self.default_from_email = (
            from_email or configured_n8n_from or os.getenv("GMAIL_FROM_EMAIL") or self.smtp_username
        ).strip()
        configured_aliases = allowed_from_emails or os.getenv(
            "GMAIL_ALLOWED_FROM_EMAILS", ""
        ).split(",")
        self.allowed_from_emails = {
            address.strip().lower()
            for address in [self.smtp_username, self.default_from_email, *configured_aliases]
            if address and address.strip()
        }
        self.smtp_endpoint = f"smtp://{self.smtp_host}:{self.smtp_port}"

    @property
    def is_configured(self) -> bool:
        if self.n8n_webhook_url:
            return bool(
                self.n8n_webhook_token
                and self.default_from_email
                and self.n8n_webhook_url.startswith("https://")
            )
        return bool(self.smtp_username and self.smtp_password and self.default_from_email)

    @property
    def provider(self) -> str:
        return "n8n" if self.n8n_webhook_url else "Gmail SMTP"

    @property
    def delivery_endpoint(self) -> str:
        return "n8n webhook" if self.n8n_webhook_url else self.smtp_endpoint

    def send_customer_email(
        self,
        job_id: int,
        customer_email: Optional[str] = None,
        customer_name: Optional[str] = None,
        from_email: Optional[str] = None,
        to_email: Optional[str] = None,
        subject: Optional[str] = None,
        message: Optional[str] = None,
        report_ids: Optional[List[int]] = None,
        skip: bool = False
    ) -> Dict[str, Any]:
        """
        Sends approved PDI reports through the configured email provider.
        Records job state and audit log in SQLite.
        """
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM report_jobs WHERE id = ?", (job_id,))
        job = cursor.fetchone()
        if not job:
            conn.close()
            raise ValueError(f"Job ID {job_id} not found")
        job = dict(job)
        if job["requirement_id"] is not None:
            cursor.execute(
                "SELECT * FROM report_jobs WHERE requirement_id = ? ORDER BY id",
                (job["requirement_id"],),
            )
            batch_jobs = [dict(row) for row in cursor.fetchall()]
        else:
            batch_jobs = [job]

        target_email = to_email or customer_email or job["customer_email"]
        sender_email = (from_email or self.default_from_email).strip()
        target_name = customer_name or job["customer_name"] or "Valued Customer"
        model_count = len(batch_jobs)
        email_subject = subject or (
            f"PDI Reports - {model_count} Models - {job['job_code']}"
            if model_count > 1
            else f"PDI Reports - Job {job['job_code']}"
        )
        model_summary = "\n".join(
            f"- {model_job['model_name'] or model_job['product_type']} "
            f"(SKU {model_job['product_number'] or '-'}, PO {model_job['po_number'] or '-'}, "
            f"Lot {model_job['lot_size']})"
            for model_job in batch_jobs
        )
        batch_label = "all models in this inspection" if model_count > 1 else f"job {job['job_code']}"
        email_message = message or (
            f"Dear {target_name},\n\n"
            f"Please find attached the approved PDI reports"
            f"{' and agreed J1 legal checklists' if str(job['company_name']).strip().casefold() == 'havells' else ''} "
            f"for {batch_label}.\n\n"
            f"Models included:\n{model_summary}"
        )
        now_str = datetime.now().isoformat()

        if skip:
            for model_job in batch_jobs:
                cursor.execute("""
                    INSERT INTO email_jobs (job_id, customer_email, customer_name, webhook_url, status, response_data, sent_at)
                    VALUES (?, ?, ?, ?, 'Skipped', 'Skipped by employee request', ?)
                """, (model_job["id"], target_email or "N/A", target_name, self.delivery_endpoint, now_str))

                cursor.execute("""
                    UPDATE report_jobs
                    SET status = CASE WHEN printed_reports > 0 THEN 'Completed' ELSE 'Awaiting Printing' END,
                        updated_at = ?
                    WHERE id = ?
                """, (now_str, model_job["id"]))

                cursor.execute("""
                    INSERT INTO audit_logs (job_id, action, performed_by, details_json, created_at)
                    VALUES (?, 'SKIP_EMAIL', 'Employee', 'Email step explicitly skipped', ?)
                """, (model_job["id"], now_str))

            conn.commit()
            conn.close()
            return {
                "success": True,
                "status": "Skipped",
                "message": "Email step skipped. Job status updated accordingly."
            }

        if not target_email:
            conn.close()
            return {
                "success": False,
                "status": "Failed",
                "message": "Customer email is required to send reports. Please enter a valid recipient email."
            }

        if not self.is_configured:
            conn.close()
            setup_message = (
                "Configure an HTTPS N8N_WEBHOOK_URL, N8N_WEBHOOK_TOKEN, and N8N_FROM_EMAIL."
                if self.n8n_webhook_url
                else "Configure GMAIL_SMTP_USERNAME and GMAIL_APP_PASSWORD."
            )
            return {
                "success": False,
                "status": "Failed",
                "message": f"Email delivery is not configured. {setup_message}",
            }

        if not EMAIL_PATTERN.fullmatch(sender_email) or not EMAIL_PATTERN.fullmatch(target_email):
            conn.close()
            return {
                "success": False,
                "status": "Failed",
                "message": "Please provide valid From and To email addresses."
            }

        if sender_email.lower() not in self.allowed_from_emails:
            conn.close()
            return {
                "success": False,
                "status": "Failed",
                "message": (
                    "The From address must be the configured company sender or a verified alias."
                )
            }

        is_havells_job = str(job["company_name"]).strip().casefold() == "havells"
        is_crompton_job = str(job["company_name"]).strip().casefold() == "crompton"
        customer_names = {
            str(model_job["company_name"]).strip().casefold()
            for model_job in batch_jobs
        }
        if len(customer_names) > 1:
            conn.close()
            return {
                "success": False,
                "status": "Failed",
                "message": "Reports from different customers cannot be sent in the same email.",
            }

        model_job_ids = [model_job["id"] for model_job in batch_jobs]
        placeholders = ",".join(["?"] * len(model_job_ids))
        if is_crompton_job or len(batch_jobs) > 1 or not report_ids:
            cursor.execute(
                f"SELECT * FROM generated_reports WHERE job_id IN ({placeholders}) ORDER BY job_id, unit_index",
                model_job_ids,
            )
        else:
            report_placeholders = ",".join(["?"] * len(report_ids))
            cursor.execute(
                f"SELECT * FROM generated_reports WHERE job_id = ? AND id IN ({report_placeholders})",
                [job_id] + report_ids,
            )
        reports = cursor.fetchall()
        if not reports:
            conn.close()
            return {
                "success": False,
                "status": "Failed",
                "message": "No generated reports were found to attach."
            }

        requires_approval = is_havells_job or is_crompton_job or len(batch_jobs) > 1
        if requires_approval:
            for model_job in batch_jobs:
                cursor.execute("""
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN status IN ('Approved', 'Emailed') THEN 1 ELSE 0 END) AS approved
                    FROM generated_reports
                    WHERE job_id = ?
                """, (model_job["id"],))
                report_counts = cursor.fetchone()
                total_reports = int(report_counts["total"] or 0)
                approved_reports = int(report_counts["approved"] or 0)
                expected_reports = int(model_job["total_reports"] or total_reports)
                if (
                    total_reports == 0
                    or total_reports != expected_reports
                    or approved_reports != total_reports
                ):
                    conn.close()
                    message = (
                        "Approve every PDI report for this model before agreeing to the J1 legal checklist and emailing."
                        if is_havells_job and len(batch_jobs) == 1
                        else "Approve every PDI report for every model before emailing the inspection batch."
                    )
                    return {
                        "success": False,
                        "status": "Failed",
                        "message": message,
                    }

        if is_havells_job:
            for model_job in batch_jobs:
                if model_job["legal_status"] != "Agreed":
                    conn.close()
                    message = (
                        "Agree to the J1 legal checklist for every model before emailing the inspection batch."
                        if len(batch_jobs) > 1
                        else "The J1 legal checklist must be agreed before emailing Havells reports."
                    )
                    return {
                        "success": False,
                        "status": "Failed",
                        "message": message,
                    }
                if not model_job["legal_pdf_path"] or not os.path.isfile(model_job["legal_pdf_path"]):
                    conn.close()
                    return {
                        "success": False,
                        "status": "Failed",
                        "message": (
                            f"The agreed J1 legal checklist PDF is missing for "
                            f"{model_job['model_name'] or model_job['product_number']}. Review and agree to the checklist again."
                        ),
                    }

        scans = cursor.execute(
            "SELECT id, image FROM crompton_email_scans WHERE job_id = ? ORDER BY id", (job_id,)
        ).fetchall() if is_crompton_job else []
        conn.close()
        report_counts_by_job: Dict[int, int] = {model_job_id: 0 for model_job_id in model_job_ids}
        for report in reports:
            report_counts_by_job[report["job_id"]] += 1
        report_generator = ReportGenerator()
        attachments = []
        for rep in reports:
            is_stg_document = rep["excel_path"].lower().endswith(".docx")
            attachment_path = rep["excel_path"] if is_stg_document else report_generator.convert_to_pdf(rep["id"])
            if not os.path.isfile(attachment_path):
                raise FileNotFoundError(f"The attachment is unavailable for report {rep['report_code']}.")
            with open(attachment_path, "rb") as report_file:
                content = report_file.read()
            attachments.append({
                "filename": os.path.basename(attachment_path),
                "content_type": DOCX_MIME_TYPE if is_stg_document else "application/pdf",
                "content": content,
            })

        if is_havells_job:
            for model_job in batch_jobs:
                with open(model_job["legal_pdf_path"], "rb") as legal_pdf:
                    attachments.append({
                        "filename": os.path.basename(model_job["legal_pdf_path"]),
                        "content_type": "application/pdf",
                        "content": legal_pdf.read(),
                    })
        attachments.extend({
            "filename": scan_filename(scan["id"]),
            "content_type": "image/jpeg",
            "content": scan["image"],
        } for scan in scans)

        email_status = "Failed"
        resp_data_str = ""
        success = False

        smtp_stage = "connection"
        if self.n8n_webhook_url:
            payload = {
                "from": sender_email,
                "to": target_email,
                "customer_name": target_name,
                "subject": email_subject,
                "message": email_message,
                "attachments": [
                    {
                        "fileName": attachment["filename"],
                        "mimeType": attachment["content_type"],
                        "base64": base64.b64encode(attachment["content"]).decode("ascii"),
                    }
                    for attachment in attachments
                ],
            }
            try:
                import requests

                response = requests.post(
                    self.n8n_webhook_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.n8n_webhook_token}"},
                    timeout=90,
                )
                if response.ok:
                    email_status = "Sent"
                    success = True
                    resp_data_str = "Email workflow accepted the request."
                else:
                    resp_data_str = f"n8n email workflow returned HTTP {response.status_code}."
            except requests.RequestException as exc:
                logger.warning("n8n email webhook failed (%s)", type(exc).__name__)
                resp_data_str = "Could not reach the configured n8n email workflow."
        else:
            try:
                outgoing = EmailMessage()
                outgoing["From"] = sender_email
                outgoing["To"] = target_email
                outgoing["Subject"] = email_subject
                outgoing.set_content(email_message)
                html_message = (
                    '<div style="font-family: Arial, sans-serif; color: #333;">'
                    + html.escape(email_message).replace("\r\n", "\n").replace("\n", "<br>")
                    + "</div>"
                )
                outgoing.add_alternative(html_message, subtype="html")
                for attachment in attachments:
                    maintype, subtype = attachment["content_type"].split("/", 1)
                    outgoing.add_attachment(
                        attachment["content"],
                        maintype=maintype,
                        subtype=subtype,
                        filename=attachment["filename"],
                    )

                if self.smtp_use_ssl:
                    smtp_stage = "TLS connection"
                    smtp_client = smtplib.SMTP_SSL(
                        self.smtp_host,
                        self.smtp_port,
                        timeout=SMTP_TIMEOUT_SECONDS,
                        context=ssl.create_default_context(),
                    )
                else:
                    smtp_client = smtplib.SMTP(
                        self.smtp_host,
                        self.smtp_port,
                        timeout=SMTP_TIMEOUT_SECONDS,
                    )
                with smtp_client as smtp:
                    if not self.smtp_use_ssl:
                        smtp.ehlo()
                        smtp_stage = "TLS negotiation"
                        smtp.starttls(context=ssl.create_default_context())
                        smtp.ehlo()
                    smtp_stage = "authentication"
                    smtp.login(self.smtp_username, self.smtp_password)
                    smtp_stage = "message submission"
                    smtp.send_message(outgoing)

                email_status = "Sent"
                success = True
                resp_data_str = "Email sent through Gmail SMTP."
            except smtplib.SMTPAuthenticationError as e:
                logger.warning("Gmail SMTP authentication failed (%s)", type(e).__name__)
                resp_data_str = (
                    "Google rejected SMTP authentication. Check GMAIL_SMTP_USERNAME and use a "
                    "Google App Password in GMAIL_APP_PASSWORD."
                )
            except smtplib.SMTPRecipientsRefused as e:
                logger.warning("Gmail SMTP rejected the recipient (%s)", type(e).__name__)
                resp_data_str = "Gmail rejected the recipient address. Verify the To email and try again."
            except (smtplib.SMTPException, OSError) as e:
                failure_reason = _smtp_failure_reason(e)
                logger.warning("Gmail SMTP delivery failed during %s: %s", smtp_stage, failure_reason)
                delivery_note = ""
                if isinstance(e, smtplib.SMTPServerDisconnected):
                    if smtp_stage == "message submission":
                        delivery_note = (
                            " The email may already have been accepted; check the sender's Sent folder "
                            "before retrying to avoid a duplicate."
                        )
                resp_data_str = (
                    f"Gmail SMTP delivery failed: {failure_reason} during {smtp_stage}."
                    f"{delivery_note} Check the SMTP settings, internet connection, "
                    "and Google account's sending limits."
                )

        conn = get_db()
        cursor = conn.cursor()
        for model_job in batch_jobs:
            cursor.execute("""
                INSERT INTO email_jobs (job_id, customer_email, customer_name, webhook_url, status, response_data, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                model_job["id"],
                target_email,
                target_name,
                self.delivery_endpoint,
                email_status,
                resp_data_str,
                now_str,
            ))

            if success:
                cursor.execute("""
                    UPDATE report_jobs
                    SET emailed_reports = ?, status = 'Completed', updated_at = ?
                    WHERE id = ?
                """, (report_counts_by_job[model_job["id"]], now_str, model_job["id"]))
                cursor.execute(
                    "UPDATE generated_reports SET status = 'Emailed', updated_at = ? WHERE job_id = ?",
                    (now_str, model_job["id"]),
                )

            cursor.execute("""
                INSERT INTO audit_logs (job_id, action, performed_by, details_json, created_at)
                VALUES (?, 'SEND_EMAIL', 'Employee', ?, ?)
            """, (
                model_job["id"],
                json.dumps({
                    "recipient": target_email,
                    "status": email_status,
                    "batch_job_ids": model_job_ids,
                    "scan_ids": [scan["id"] for scan in scans],
                }),
                now_str,
            ))

        conn.commit()
        conn.close()

        return {
            "success": success,
            "status": email_status,
            "message": (
                "Reports for all models sent successfully."
                if success and model_count > 1
                else "Reports sent successfully." if success else resp_data_str
            ),
            "from_email": sender_email,
            "customer_email": target_email,
            "subject": email_subject,
            "attachments_count": len(attachments),
            "scan_count": len(scans),
            "model_count": model_count,
            "response": resp_data_str,
            "provider": self.provider
        }
