import os
import smtplib
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from services import crompton_email_scans
from services.email_service import EmailService


class EmailServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = database.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        database.init_db()

        self.report_excel_path = os.path.join(self.temp_dir.name, "generated_report.xlsx")
        self.report_pdf_path = os.path.join(self.temp_dir.name, "generated_report.pdf")
        with open(self.report_excel_path, "wb") as report_file:
            report_file.write(b"generated workbook")
        with open(self.report_pdf_path, "wb") as report_file:
            report_file.write(b"generated report PDF")

        conn = database.get_db()
        now = "2026-01-01T00:00:00"
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO report_jobs (
                job_code, company_name, product_type, lot_size, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("JOB-TEST", "Crompton", "Pump", 1, "Approved", now, now),
        )
        self.job_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO generated_reports (
                job_id, report_code, unit_index, excel_path, pdf_path, status,
                report_data_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.job_id, "REPORT-TEST", 1, self.report_excel_path, None,
                "Approved", "{}", now, now,
            ),
        )
        self.report_id = cursor.lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def create_service(self, **overrides):
        config = {
            "smtp_host": "smtp.gmail.test",
            "smtp_port": 587,
            "smtp_username": "sender@example.com",
            "smtp_password": "test-app-password",
            "from_email": "sender@example.com",
        }
        config.update(overrides)
        return EmailService(**config)

    def create_havells_batch(self, second_report_status="Approved", second_legal_status="Agreed"):
        now = "2026-01-01T00:00:00"
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO uploaded_requirements (
                filename, original_name, file_type, file_path, uploaded_at, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("requirement.pdf", "requirement.pdf", "pdf", "requirement.pdf", now, "Processed"),
        )
        requirement_id = cursor.lastrowid

        legal_pdf_paths = []
        for model_name in ("Model A", "Model B"):
            legal_pdf_path = os.path.join(self.temp_dir.name, f"{model_name.replace(' ', '-')}-legal.pdf")
            with open(legal_pdf_path, "wb") as legal_pdf:
                legal_pdf.write(f"{model_name} J1 PDF".encode())
            legal_pdf_paths.append(legal_pdf_path)

        cursor.execute("""
            UPDATE report_jobs
            SET requirement_id = ?, company_name = 'Havells', model_name = 'Model A',
                product_number = 'SKU-A', po_number = 'PO-A', total_reports = 1,
                approved_reports = 1, legal_status = 'Agreed', legal_pdf_path = ?
            WHERE id = ?
        """, (requirement_id, legal_pdf_paths[0], self.job_id))
        cursor.execute("""
            INSERT INTO report_jobs (
                job_code, requirement_id, company_name, product_type, model_name,
                product_number, po_number, lot_size, customer_name, customer_email,
                status, total_reports, approved_reports, legal_status, legal_pdf_path,
                created_at, updated_at
            ) VALUES (?, ?, 'Havells', 'Pump', 'Model B', 'SKU-B', 'PO-B', 1,
                      'Test Customer', 'customer@example.com', 'Approved', 1, ?, ?, ?, ?, ?)
        """, (
            "JOB-TEST-B", requirement_id,
            int(second_report_status in {"Approved", "Emailed"}),
            second_legal_status, legal_pdf_paths[1], now, now,
        ))
        second_job_id = cursor.lastrowid
        cursor.execute(
            "UPDATE generated_reports SET status = 'Approved' WHERE id = ?",
            (self.report_id,),
        )
        second_excel_path = os.path.join(self.temp_dir.name, "generated_report_b.xlsx")
        with open(second_excel_path, "wb") as workbook:
            workbook.write(b"generated workbook B")
        cursor.execute("""
            INSERT INTO generated_reports (
                job_id, report_code, unit_index, excel_path, pdf_path, status,
                report_data_json, created_at, updated_at
            ) VALUES (?, 'REPORT-TEST-B', 1, ?, NULL, ?, '{}', ?, ?)
        """, (second_job_id, second_excel_path, second_report_status, now, now))
        second_report_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return [self.job_id, second_job_id], [self.report_id, second_report_id], legal_pdf_paths

    def test_sends_composed_message_and_pdf_through_gmail_smtp(self):
        smtp = Mock()
        with patch(
            "services.email_service.ReportGenerator.convert_to_pdf",
            return_value=self.report_pdf_path,
        ) as convert_to_pdf, patch("services.email_service.smtplib.SMTP") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
                subject="PDI approval",
                message="Please review <the report>.\nThank you.",
            )

        smtp_factory.assert_called_once_with("smtp.gmail.test", 587, timeout=300)
        convert_to_pdf.assert_called_once_with(self.report_id)
        smtp.login.assert_called_once_with("sender@example.com", "test-app-password")
        smtp.starttls.assert_called_once()
        sent_message = smtp.send_message.call_args.args[0]
        self.assertEqual(sent_message["From"], "sender@example.com")
        self.assertEqual(sent_message["To"], "customer@example.com")
        self.assertEqual(sent_message["Subject"], "PDI approval")
        self.assertEqual(
            sent_message.get_body(preferencelist=("plain",)).get_content().strip(),
            "Please review <the report>.\nThank you.",
        )
        self.assertIn("&lt;the report&gt;.<br>Thank you.", sent_message.get_body(
            preferencelist=("html",)
        ).get_content())
        attachment, = sent_message.iter_attachments()
        self.assertEqual(attachment.get_filename(), "generated_report.pdf")
        self.assertEqual(attachment.get_content(), b"generated report PDF")
        self.assertFalse(attachment.get_filename().endswith(".xlsx"))
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "Sent")

    def test_uses_implicit_tls_when_configured_for_port_465(self):
        smtp = Mock()
        with patch(
            "services.email_service.ReportGenerator.convert_to_pdf",
            return_value=self.report_pdf_path,
        ), patch("services.email_service.smtplib.SMTP_SSL") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service(smtp_port=465).send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
            )

        smtp_factory.assert_called_once()
        self.assertEqual(smtp_factory.call_args.args[:2], ("smtp.gmail.test", 465))
        self.assertEqual(smtp_factory.call_args.kwargs["timeout"], 300)
        smtp.starttls.assert_not_called()
        smtp.login.assert_called_once_with("sender@example.com", "test-app-password")
        smtp.send_message.assert_called_once()
        self.assertTrue(result["success"])

    def test_crompton_sends_both_approved_reports_and_saved_images(self):
        conn = database.get_db()
        with conn:
            conn.execute("UPDATE report_jobs SET total_reports = 2 WHERE id = ?", (self.job_id,))
            second_id = conn.execute("""
                INSERT INTO generated_reports (
                    job_id, report_code, unit_index, excel_path, status, report_data_json, created_at, updated_at
                )
                SELECT job_id, 'REPORT-TEST-2', 2, excel_path, 'Awaiting Review', '{}', created_at, updated_at
                FROM generated_reports WHERE id = ?
            """, (self.report_id,)).lastrowid
        photo = BytesIO()
        Image.new("RGB", (16, 16)).save(photo, "PNG")

        with self.assertRaises(HTTPException) as pending:
            crompton_email_scans.add_scan(self.job_id, photo.getvalue())
        self.assertEqual(pending.exception.status_code, 409)
        recipient = {"job_id": self.job_id, "to_email": "customer@example.com", "report_ids": [self.report_id]}
        self.assertFalse(self.create_service().send_customer_email(**recipient)["success"])

        with conn:
            conn.execute("UPDATE generated_reports SET status = 'Approved' WHERE id = ?", (second_id,))
        conn.close()
        scan = crompton_email_scans.add_scan(self.job_id, photo.getvalue())
        dropped_scan = crompton_email_scans.add_scan(self.job_id, photo.getvalue())
        crompton_email_scans.remove_scan(self.job_id, dropped_scan["id"])
        self.assertEqual(crompton_email_scans.list_scans(self.job_id), [scan])

        smtp = Mock()
        with patch("services.email_service.ReportGenerator.convert_to_pdf", return_value=self.report_pdf_path) as convert, \
                patch("services.email_service.smtplib.SMTP") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service().send_customer_email(**recipient)
        self.assertTrue(result["success"])
        self.assertEqual(result["attachments_count"], 3)
        self.assertEqual(result["scan_count"], 1)
        self.assertEqual([call.args[0] for call in convert.call_args_list], [self.report_id, second_id])
        sent_attachments = list(smtp.send_message.call_args.args[0].iter_attachments())
        self.assertEqual([item.get_content_type() for item in sent_attachments],
                         ["application/pdf", "application/pdf", "image/jpeg"])
        self.assertEqual(sent_attachments[-1].get_filename(), scan["filename"])
        self.assertEqual(sent_attachments[-1].get_content(), crompton_email_scans.get_scan(self.job_id, scan["id"]))

    def test_rejects_from_address_not_configured_as_gmail_alias(self):
        smtp = Mock()
        with patch("services.email_service.smtplib.SMTP") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                from_email="unverified@example.com",
                to_email="customer@example.com",
            )

        smtp_factory.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("verified alias", result["message"])

    def test_missing_gmail_credentials_returns_setup_instructions(self):
        result = self.create_service(smtp_username="", smtp_password="").send_customer_email(
            job_id=self.job_id,
            to_email="customer@example.com",
        )

        self.assertFalse(result["success"])
        self.assertIn("GMAIL_APP_PASSWORD", result["message"])

    def test_smtp_connection_error_returns_actionable_message(self):
        with patch(
            "services.email_service.ReportGenerator.convert_to_pdf",
            return_value=self.report_pdf_path,
        ), patch(
            "services.email_service.smtplib.SMTP",
            side_effect=ConnectionRefusedError("connection refused"),
        ):
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
            )

        self.assertFalse(result["success"])
        self.assertIn("Gmail SMTP delivery failed", result["message"])

    def test_smtp_server_rejection_includes_response_code_and_reason(self):
        smtp = Mock()
        smtp.send_message.side_effect = smtplib.SMTPDataError(
            552, b"5.3.4 Message size exceeds fixed maximum"
        )
        with patch(
            "services.email_service.ReportGenerator.convert_to_pdf",
            return_value=self.report_pdf_path,
        ), patch("services.email_service.smtplib.SMTP") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
            )

        self.assertFalse(result["success"])
        self.assertIn("SMTP server returned 552", result["message"])
        self.assertIn("Message size exceeds fixed maximum", result["message"])

    def test_disconnect_during_submission_warns_against_duplicate_retry(self):
        smtp = Mock()
        smtp.send_message.side_effect = smtplib.SMTPServerDisconnected(
            "connection unexpectedly closed"
        )
        with patch(
            "services.email_service.ReportGenerator.convert_to_pdf",
            return_value=self.report_pdf_path,
        ), patch("services.email_service.smtplib.SMTP") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
            )

        self.assertFalse(result["success"])
        self.assertIn("during message submission", result["message"])
        self.assertIn("check the sender's Sent folder", result["message"])

    def test_havells_email_requires_an_agreed_legal_checklist(self):
        conn = database.get_db()
        conn.execute("UPDATE report_jobs SET company_name = 'Havells' WHERE id = ?", (self.job_id,))
        conn.commit()
        conn.close()

        with patch("services.email_service.ReportGenerator.convert_to_pdf") as convert_to_pdf:
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
            )

        convert_to_pdf.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("J1 legal checklist must be agreed", result["message"])

    def test_havells_email_requires_pdi_reports_approved_before_j1(self):
        conn = database.get_db()
        conn.execute(
            "UPDATE report_jobs SET company_name = 'Havells', legal_status = 'Awaiting Review' WHERE id = ?",
            (self.job_id,),
        )
        conn.execute(
            "UPDATE generated_reports SET status = 'Printed' WHERE job_id = ?",
            (self.job_id,),
        )
        conn.commit()
        conn.close()

        with patch("services.email_service.ReportGenerator.convert_to_pdf") as convert_to_pdf:
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
            )

        convert_to_pdf.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("Approve every PDI report", result["message"])

    def test_havells_email_attaches_the_j1_pdf_with_pdi_reports(self):
        legal_pdf_path = os.path.join(self.temp_dir.name, "legal-j1.pdf")
        with open(legal_pdf_path, "wb") as legal_pdf:
            legal_pdf.write(b"J1 legal report PDF")
        conn = database.get_db()
        conn.execute("""
            UPDATE report_jobs
            SET company_name = 'Havells', legal_status = 'Agreed', legal_pdf_path = ?
            WHERE id = ?
        """, (legal_pdf_path, self.job_id))
        conn.commit()
        conn.close()
        smtp = Mock()

        with patch(
            "services.email_service.ReportGenerator.convert_to_pdf",
            return_value=self.report_pdf_path,
        ), patch("services.email_service.smtplib.SMTP") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service().send_customer_email(
                job_id=self.job_id,
                to_email="customer@example.com",
            )

        attachments = list(smtp.send_message.call_args.args[0].iter_attachments())
        self.assertTrue(result["success"])
        self.assertEqual(result["attachments_count"], 2)
        self.assertEqual(
            {attachment.get_filename() for attachment in attachments},
            {"generated_report.pdf", "legal-j1.pdf"},
        )
        conn = database.get_db()
        emailed_reports = conn.execute(
            "SELECT emailed_reports FROM report_jobs WHERE id = ?", (self.job_id,)
        ).fetchone()["emailed_reports"]
        conn.close()
        self.assertEqual(emailed_reports, 1)

    def test_sends_all_model_reports_and_j1_pdfs_in_one_email(self):
        job_ids, report_ids, legal_pdf_paths = self.create_havells_batch()
        report_pdf_paths = {}
        for report_id, filename in zip(report_ids, ("report-a.pdf", "report-b.pdf")):
            pdf_path = os.path.join(self.temp_dir.name, filename)
            with open(pdf_path, "wb") as report_pdf:
                report_pdf.write(f"PDF for {report_id}".encode())
            report_pdf_paths[report_id] = pdf_path
        smtp = Mock()

        with patch(
            "services.email_service.ReportGenerator.convert_to_pdf",
            side_effect=lambda report_id: report_pdf_paths[report_id],
        ) as convert_to_pdf, patch("services.email_service.smtplib.SMTP") as smtp_factory:
            smtp_factory.return_value.__enter__.return_value = smtp
            result = self.create_service().send_customer_email(
                job_id=job_ids[0],
                to_email="customer@example.com",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["model_count"], 2)
        self.assertEqual(result["attachments_count"], 4)
        self.assertCountEqual(
            [call.args[0] for call in convert_to_pdf.call_args_list],
            report_ids,
        )
        self.assertEqual(smtp.send_message.call_count, 1)
        sent_message = smtp.send_message.call_args.args[0]
        self.assertCountEqual(
            [attachment.get_filename() for attachment in sent_message.iter_attachments()],
            [
                "report-a.pdf", "report-b.pdf",
                os.path.basename(legal_pdf_paths[0]), os.path.basename(legal_pdf_paths[1]),
            ],
        )
        conn = database.get_db()
        emailed_jobs = conn.execute(
            "SELECT id, emailed_reports FROM report_jobs WHERE id IN (?, ?) ORDER BY id",
            job_ids,
        ).fetchall()
        email_records = conn.execute(
            "SELECT job_id, status FROM email_jobs WHERE job_id IN (?, ?) ORDER BY job_id",
            job_ids,
        ).fetchall()
        conn.close()
        self.assertEqual([row["emailed_reports"] for row in emailed_jobs], [1, 1])
        self.assertEqual([row["job_id"] for row in email_records], job_ids)
        self.assertEqual([row["status"] for row in email_records], ["Sent", "Sent"])

    def test_batch_email_waits_until_every_model_report_is_approved(self):
        job_ids, _, _ = self.create_havells_batch(second_report_status="Printed")

        with patch("services.email_service.ReportGenerator.convert_to_pdf") as convert_to_pdf, patch(
            "services.email_service.smtplib.SMTP"
        ) as smtp_factory:
            result = self.create_service().send_customer_email(
                job_id=job_ids[0],
                to_email="customer@example.com",
            )

        self.assertFalse(result["success"])
        self.assertIn("every PDI report for every model", result["message"])
        convert_to_pdf.assert_not_called()
        smtp_factory.assert_not_called()

    def test_batch_email_waits_until_every_model_j1_checklist_is_agreed(self):
        job_ids, _, _ = self.create_havells_batch(second_legal_status="Awaiting Review")

        with patch("services.email_service.ReportGenerator.convert_to_pdf") as convert_to_pdf, patch(
            "services.email_service.smtplib.SMTP"
        ) as smtp_factory:
            result = self.create_service().send_customer_email(
                job_id=job_ids[0],
                to_email="customer@example.com",
            )

        self.assertFalse(result["success"])
        self.assertIn("J1 legal checklist for every model", result["message"])
        convert_to_pdf.assert_not_called()
        smtp_factory.assert_not_called()

    def test_batch_email_requires_reports_for_every_model(self):
        job_ids, _, _ = self.create_havells_batch()
        conn = database.get_db()
        conn.execute("DELETE FROM generated_reports WHERE job_id = ?", (job_ids[1],))
        conn.commit()
        conn.close()

        with patch("services.email_service.ReportGenerator.convert_to_pdf") as convert_to_pdf, patch(
            "services.email_service.smtplib.SMTP"
        ) as smtp_factory:
            result = self.create_service().send_customer_email(
                job_id=job_ids[0],
                to_email="customer@example.com",
            )

        self.assertFalse(result["success"])
        self.assertIn("every PDI report for every model", result["message"])
        convert_to_pdf.assert_not_called()
        smtp_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
