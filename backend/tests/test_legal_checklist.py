import base64
import asyncio
import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader
from PIL import Image as PILImage

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from schemas import LegalChecklistAgreementRequest, LegalChecklistImages, LegalChecklistItemUpdate
from services.legal_checklist_service import LegalChecklistService
from routes import reports as report_routes


class LegalChecklistServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workbook_path = os.path.join(self.temp_dir.name, "legal-j1.xlsx")
        self.pdf_path = os.path.join(self.temp_dir.name, "legal-j1.pdf")
        self.service = LegalChecklistService()
        self.service.generate_workbook({
            "model_name": "Test Model",
            "product_type": "Surface Pump",
            "product_number": "HV-101",
            "lot_size": 101,
            "inspection_date": "13-11-2026",
            "inspected_by": "QA Inspector",
            "approved_by": "Quality Head",
        }, self.workbook_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_saves_model_specific_review_and_exports_only_j1_as_pdf(self):
        checklist = self.service.read_checklist(self.workbook_path)
        self.assertEqual(len(checklist["items"]), 15)
        self.assertEqual(checklist["mrp_value"], "")
        self.assertTrue(all(item["status"] == "OK" for item in checklist["items"] if not item["is_mrp"]))

        workbook = load_workbook(self.workbook_path, data_only=True)
        sheet = workbook["J1"]
        for row in range(5, 20):
            self.assertEqual(sheet[f"H{row}"].value, None if row == 13 else "OK")
        workbook.close()

        items = []
        for item in checklist["items"]:
            items.append({
                "row_index": item["row_index"],
                "status": "NG" if item["row_index"] == 5 else ("OK" if not item["is_mrp"] else None),
            })
        image_buffer = BytesIO()
        PILImage.new("RGB", (40, 30), (30, 120, 200)).save(image_buffer, format="PNG")
        image_data = "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode("ascii")
        decision = self.service.save_review(
            self.workbook_path,
            items,
            "6,500.00",
            {"carton_with_label": image_data},
        )
        self.assertEqual(decision, "Reject")
        self.service.create_pdf(self.workbook_path, self.pdf_path)

        workbook = load_workbook(self.workbook_path, data_only=True)
        sheet = workbook["J1"]
        self.assertEqual(workbook.sheetnames, ["J1"])
        self.assertEqual(sheet["H5"].value, "NG")
        self.assertTrue(all(sheet[f"J{row}"].value == "-" for row in range(5, 20)))
        self.assertEqual(sheet["H13"].value, "6,500.00")
        self.assertIn("Reject", sheet["D3"].value)
        photo_anchors = {
            (image.anchor._from.col, image.anchor._from.row)
            for image in sheet._images
            if image.anchor._from.row == 20
        }
        self.assertIn((1, 20), photo_anchors)
        workbook.close()

        pdf_text = " ".join(page.extract_text() or "" for page in PdfReader(self.pdf_path).pages)
        self.assertIn("LEGAL COMPLIANCE CHECKSHEET", pdf_text)
        self.assertIn("Test Model", pdf_text)
        self.assertIn("6,500.00", pdf_text)
        self.assertIn("-", pdf_text)
        self.assertIn("Carton with Label", pdf_text)
        self.assertTrue(self.service.read_checklist(self.workbook_path)["images"]["carton_with_label"])

    def test_existing_blank_status_defaults_to_ok(self):
        workbook = load_workbook(self.workbook_path)
        workbook["J1"]["H5"] = None
        workbook.save(self.workbook_path)
        workbook.close()

        checklist = self.service.read_checklist(self.workbook_path)
        self.assertEqual(checklist["items"][0]["status"], "OK")
        self.assertEqual(checklist["mrp_value"], "")

    def test_remarks_default_to_dash_and_are_not_required_for_agreement(self):
        workbook = load_workbook(self.workbook_path, data_only=True)
        sheet = workbook["J1"]
        self.assertTrue(all(sheet[f"J{row}"].value == "-" for row in range(5, 20)))
        workbook.close()

        items = [
            {
                "row_index": item["row_index"],
                "status": None if item["is_mrp"] else "OK",
            }
            for item in self.service.read_checklist(self.workbook_path)["items"]
        ]
        self.service.save_review(self.workbook_path, items, "6,500.00")

        checklist = self.service.read_checklist(self.workbook_path)
        self.assertTrue(all(item["remarks"] == "-" for item in checklist["items"]))

    def test_legal_agreement_requires_all_pdi_reports_approved(self):
        original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        try:
            database.init_db()
            conn = database.get_db()
            now = "2026-11-13T00:00:00"
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO report_jobs (
                    job_code, company_name, product_type, lot_size, status,
                    legal_excel_path, legal_pdf_path, legal_status, created_at, updated_at
                ) VALUES (?, 'Havells', 'Surface Pump', 1, 'Awaiting Review', ?, ?, 'Awaiting Review', ?, ?)
            """, (
                "JOB-LEGAL-TEST",
                self.workbook_path,
                self.pdf_path,
                now,
                now,
            ))
            job_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO generated_reports (
                    job_id, report_code, unit_index, excel_path, status,
                    report_data_json, created_at, updated_at
                ) VALUES (?, 'REPORT-LEGAL-TEST', 1, ?, 'Awaiting Review', '{}', ?, ?)
            """, (job_id, self.workbook_path, now, now))
            conn.commit()
            conn.close()

            request = LegalChecklistAgreementRequest(
                agreed=True,
                mrp_value="6,500.00",
                items=[
                    LegalChecklistItemUpdate(
                        row_index=item["row_index"],
                        status=None if item["is_mrp"] else "OK",
                        remarks="Checked",
                    )
                    for item in self.service.read_checklist(self.workbook_path)["items"]
                ],
            )
            with self.assertRaises(report_routes.HTTPException) as raised:
                asyncio.run(report_routes.agree_legal_checklist(job_id, request))
            self.assertEqual(raised.exception.status_code, 409)
        finally:
            database.DB_PATH = original_db_path

    def test_job_details_backfills_a_legacy_havells_checklist(self):
        original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp_dir.name, "legacy-test.db")
        try:
            database.init_db()
            conn = database.get_db()
            now = "2026-11-13T00:00:00"
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO report_jobs (
                    job_code, company_name, product_type, model_name, product_number,
                    po_number, lot_size, status, total_reports, created_at, updated_at
                ) VALUES (?, 'Havells', 'Surface Pump', 'Test Model', 'HV-101',
                          'PO-101', 101, 'Approved', 1, ?, ?)
            """, ("JOB-LEGACY-LEGAL", now, now))
            job_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO generated_reports (
                    job_id, report_code, unit_index, excel_path, status,
                    report_data_json, created_at, updated_at
                ) VALUES (?, 'REPORT-LEGACY-LEGAL', 1, ?, 'Approved', '{}', ?, ?)
            """, (job_id, self.workbook_path, now, now))
            conn.commit()
            conn.close()

            details = asyncio.run(report_routes.get_job_details(job_id))
            self.assertEqual(details["legal_status"], "Awaiting Review")
            self.assertEqual(details["status"], "Awaiting Legal Review")
            self.assertEqual(len(details["legal_checklist"]["items"]), 15)
            self.assertTrue(os.path.isfile(details["legal_excel_path"]))
        finally:
            database.DB_PATH = original_db_path

    def test_agreement_saves_workbook_pdf_and_approval_status(self):
        original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp_dir.name, "approved-test.db")
        try:
            database.init_db()
            conn = database.get_db()
            now = "2026-11-13T00:00:00"
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO report_jobs (
                    job_code, company_name, product_type, lot_size, status,
                    legal_excel_path, legal_pdf_path, legal_status, created_at, updated_at
                ) VALUES (?, 'Havells', 'Surface Pump', 1, 'Awaiting Legal Review', ?, ?, 'Awaiting Review', ?, ?)
            """, (
                "JOB-LEGAL-APPROVAL",
                self.workbook_path,
                self.pdf_path,
                now,
                now,
            ))
            job_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO generated_reports (
                    job_id, report_code, unit_index, excel_path, status,
                    report_data_json, created_at, updated_at
                ) VALUES (?, 'REPORT-LEGAL-APPROVAL', 1, ?, 'Approved', '{}', ?, ?)
            """, (job_id, self.workbook_path, now, now))
            conn.commit()
            conn.close()

            image_buffer = BytesIO()
            PILImage.new("RGB", (20, 20), (10, 100, 220)).save(image_buffer, format="PNG")
            image_data = "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode("ascii")
            request = LegalChecklistAgreementRequest(
                agreed=True,
                mrp_value="6,500.00",
                images=LegalChecklistImages(carton_with_label=image_data),
                items=[
                    LegalChecklistItemUpdate(
                        row_index=item["row_index"],
                        status=None if item["is_mrp"] else "OK",
                        remarks="Verified",
                    )
                    for item in self.service.read_checklist(self.workbook_path)["items"]
                ],
            )
            result = asyncio.run(report_routes.agree_legal_checklist(job_id, request))
            self.assertEqual(result["legal_status"], "Agreed")
            self.assertEqual(result["decision"], "Accept")
            self.assertTrue(result["legal_checklist"]["images"]["carton_with_label"])
            self.assertTrue(os.path.isfile(self.pdf_path))
            details = asyncio.run(report_routes.get_job_details(job_id))
            self.assertEqual(details["legal_status"], "Agreed")
            self.assertEqual(len(details["legal_checklist"]["items"]), 15)

            conn = database.get_db()
            job = conn.execute(
                "SELECT legal_status, status FROM report_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            audit_action = conn.execute(
                "SELECT action FROM audit_logs WHERE job_id = ?", (job_id,)
            ).fetchone()["action"]
            conn.close()
            self.assertEqual(job["legal_status"], "Agreed")
            self.assertEqual(job["status"], "Approved")
            self.assertEqual(audit_action, "AGREE_LEGAL_CHECKLIST")
        finally:
            database.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
