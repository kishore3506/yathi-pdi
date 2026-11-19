import asyncio
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import openpyxl
from docx import Document
from fastapi import UploadFile
from reportlab.pdfgen import canvas

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.report_analysis import (
    extract_report_text,
    render_report_analysis,
    select_existing_reports,
)
from services.document_extractor import DocumentExtractor
from routes.chat import ReportAnalysisRequest, analyze_existing_reports, analyze_uploaded_report


class ReportAnalysisTests(unittest.TestCase):
    class FakeExtractor:
        def extract_document_info(self, **kwargs):
            self.text_content = kwargs["text_content"]
            return {}

    def test_extracts_text_from_pdf_xlsx_and_docx(self):
        pdf_buffer = BytesIO()
        pdf = canvas.Canvas(pdf_buffer)
        pdf.drawString(40, 800, "PDI Report: Pump A")
        pdf.save()
        self.assertIn("PDI Report: Pump A", extract_report_text(pdf_buffer.getvalue(), "report.pdf"))

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "Inspection"
        worksheet.append(["Model", "Pump A"])
        workbook_buffer = BytesIO()
        workbook.save(workbook_buffer)
        self.assertIn("Model | Pump A", extract_report_text(workbook_buffer.getvalue(), "report.xlsx"))

        document = Document()
        document.add_paragraph("PDI Report: Pump A")
        document.add_table(rows=1, cols=2).rows[0].cells[0].text = "Overall judgment"
        document.tables[0].rows[0].cells[1].text = "OK"
        docx_buffer = BytesIO()
        document.save(docx_buffer)
        docx_text = extract_report_text(docx_buffer.getvalue(), "report.docx")
        self.assertIn("PDI Report: Pump A", docx_text)
        self.assertIn("Overall judgment | OK", docx_text)

    def test_requirement_extractor_reads_docx_documents(self):
        document = Document()
        document.add_paragraph("Customer: Havells")
        document_buffer = BytesIO()
        document.save(document_buffer)
        fake_ai = self.FakeExtractor()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "requirement.docx"
            source.write_bytes(document_buffer.getvalue())
            DocumentExtractor(gemini_service=fake_ai).process_file(str(source))

        self.assertIn("Customer: Havells", fake_ai.text_content)

    def test_selects_existing_reports_using_user_criteria_and_caps_all(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        reports = [
            {
                "id": 1,
                "report_code": "HAV_PDI_PUMP_A_001",
                "company_name": "Havells",
                "product_type": "Surface Pump",
                "model_name": "Pump A",
                "product_number": "SKU-1",
                "po_number": "PO-1",
                "created_at": f"{today}T10:00:00",
            },
            {
                "id": 2,
                "report_code": "KSB_PDI_PUMP_B_001",
                "company_name": "KSB",
                "product_type": "Surface Pump",
                "model_name": "Pump B",
                "product_number": "SKU-2",
                "po_number": "PO-2",
                "created_at": f"{yesterday}T10:00:00",
            },
        ]

        selected = select_existing_reports("Analyze the Havells Pump A report.", reports)
        self.assertEqual([report["id"] for report in selected], [1])
        self.assertEqual(len(select_existing_reports("Analyze all reports.", reports)), 2)
        with self.assertRaisesRegex(ValueError, "20 reports or fewer"):
            select_existing_reports("Analyze all reports.", reports * 11)

    def test_renders_analysis_as_pdf_and_docx(self):
        pdf, pdf_type, pdf_extension = render_report_analysis(
            "# Findings\n- Check observation 5. ✔",
            "PDI report",
            "pdf",
        )
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual((pdf_type, pdf_extension), ("application/pdf", ".pdf"))

        docx, docx_type, docx_extension = render_report_analysis(
            "# Findings\n- Check observation 5.",
            "PDI report",
            "docx",
        )
        self.assertTrue(ZipFile(BytesIO(docx)).testzip() is None)
        self.assertEqual(
            docx_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(docx_extension, ".docx")
        self.assertIn("Check observation 5.", "\n".join(
            paragraph.text for paragraph in Document(BytesIO(docx)).paragraphs
        ))

        archive, archive_type, archive_extension = render_report_analysis(
            "# Findings\n- Check observation 5.",
            "PDI report",
            "both",
        )
        with ZipFile(BytesIO(archive)) as files:
            self.assertEqual(
                set(files.namelist()),
                {"pdi_report_analysis.pdf", "pdi_report_analysis.docx"},
            )
        self.assertEqual((archive_type, archive_extension), ("application/zip", ".zip"))

    def test_rejects_unsupported_and_oversized_input(self):
        with self.assertRaisesRegex(ValueError, "Unsupported report file"):
            extract_report_text(b"data", "report.xls")
        with self.assertRaisesRegex(ValueError, "15 MB"):
            extract_report_text(b"x" * (15 * 1024 * 1024 + 1), "report.pdf")

    @patch("routes.chat.GeminiService")
    def test_uploaded_report_endpoint_returns_requested_download(self, gemini_service):
        gemini = gemini_service.return_value
        gemini.api_key = "configured"
        gemini.generate_chat_response.return_value = "# Summary\n- Review checkpoint 4."
        pdf_buffer = BytesIO()
        pdf = canvas.Canvas(pdf_buffer)
        pdf.drawString(40, 800, "PDI Report: Pump A")
        pdf.save()
        uploaded_file = UploadFile(filename="pdi-report.pdf", file=BytesIO(pdf_buffer.getvalue()))

        response = asyncio.run(analyze_uploaded_report(uploaded_file, "pdf"))

        self.assertEqual(response.media_type, "application/pdf")
        self.assertTrue(response.body.startswith(b"%PDF"))
        gemini.generate_chat_response.assert_called_once()
        self.assertTrue(gemini.generate_chat_response.call_args.kwargs["report_analysis"])

    @patch("routes.chat.GeminiService")
    @patch("routes.chat.get_db")
    def test_existing_reports_endpoint_returns_word_analysis(self, get_db, gemini_service):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE report_jobs (
                id INTEGER PRIMARY KEY,
                company_name TEXT,
                product_type TEXT,
                model_name TEXT,
                product_number TEXT,
                po_number TEXT,
                status TEXT
            );
            CREATE TABLE generated_reports (
                id INTEGER PRIMARY KEY,
                job_id INTEGER,
                report_code TEXT,
                status TEXT,
                created_at TEXT,
                report_data_json TEXT
            );
            INSERT INTO report_jobs VALUES
                (1, 'Havells', 'Surface Pump', 'Pump A', 'SKU-1', 'PO-1', 'Awaiting Review');
            INSERT INTO generated_reports VALUES
                (1, 1, 'HAV_PDI_PUMP_A_001', 'Awaiting Review', '2026-11-17T10:00:00',
                 '{"checkpoints":[{"item_sn":"1","specification":"10","observations":{"G":"10"}}]}');
        """)
        get_db.return_value = connection
        gemini = gemini_service.return_value
        gemini.api_key = "configured"
        gemini.generate_chat_response.return_value = "# Summary\n- No discrepancies found."

        response = analyze_existing_reports(ReportAnalysisRequest(
            request_text="Analyze the Havells Pump A report.",
            output_format="docx",
        ))

        self.assertEqual(
            response.media_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertTrue(response.body.startswith(b"PK"))
        self.assertIn("checkpoints", gemini.generate_chat_response.call_args.args[0][0]["content"])
        connection.close()


if __name__ == "__main__":
    unittest.main()
