import sys
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from docx import Document
from fastapi.testclient import TestClient
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from auth import password_hasher
from main import app
from routes import reports
from services.stg_report import PHOTO_SLOTS, read_photo


class StgReportTests(unittest.TestCase):
    def test_generate_upload_replace_remove_and_download(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            database, "DB_PATH", str(Path(folder) / "test.db")
        ), patch.object(reports, "REPORTS_DIR", folder), TestClient(app) as client:
            with closing(database.get_db()) as db, db:
                db.execute(
                    """INSERT INTO users (email, display_name, password_hash, role, created_at, updated_at)
                       VALUES (?, ?, ?, 'administrator', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    ("stg@example.test", "Test Inspector", password_hasher.hash("test-inspector-password")),
                )
            self.assertEqual(client.post("/api/auth/login", json={
                "email": "stg@example.test", "password": "test-inspector-password",
            }).status_code, 200)
            template = client.post("/api/templates/match", json={"company_name": "STG", "product_type": "NSP"}).json()
            self.assertEqual(template["template_name"], "STG_PDI.docx")
            generated = client.post("/api/reports/generate", json={
                "template_id": template["template_id"], "company_name": "STG", "product_type": "NSP",
                "product_number": "00042", "lot_size": 1200, "model_name": "ESG1131207",
                "po_number": "PO-TEST-1",
            })
            self.assertEqual(generated.status_code, 200, generated.text)
            report, = generated.json()["reports"]
            report_url = f"/api/reports/{report['id']}"
            self.assertEqual(report["allocated_quantity"], 1200)
            self.assertEqual(report["report_data"]["header_data"]["model_name"], "ESG1131207")
            self.assertEqual(report["report_data"]["header_data"]["po_number"], "PO-TEST-1")
            self.assertEqual(report["report_data"]["header_data"]["batch_number"], "")
            slots = [slot for group in report["report_data"]["photo_groups"] for slot in group["slots"]]
            self.assertEqual(len({slot["key"] for slot in slots}), 46)
            self.assertFalse(any(slot["has_photo"] for slot in slots))
            original = Document(report["excel_path"])
            self.assertEqual(len(original._element.xpath(".//w:drawing")), 1)

            image = BytesIO()
            Image.new("RGB", (400, 200), "green").save(image, "PNG")
            first = report_url + "/photos/label-1"
            second = report_url + "/photos/size-4-weight"

            def upload(url, revision, content):
                return client.patch(url, data={"expected_revision": revision}, files={
                    "photo": ("inspection.png", content, "image/png"),
                })

            self.assertEqual(upload(first, 1, b"unreadable").status_code, 400)
            self.assertEqual(upload(first, 1, image.getvalue()).status_code, 200)
            self.assertEqual(upload(second, 1, image.getvalue()).status_code, 409)
            self.assertEqual(upload(second, 2, image.getvalue()).status_code, 200)
            self.assertEqual(client.get(first).headers["content-type"], "image/jpeg")
            self.assertEqual(client.get(second).content, client.get(first).content)
            self.assertEqual(client.patch(first, data={"expected_revision": 3}).status_code, 200)
            self.assertEqual(client.get(first).status_code, 404)
            self.assertEqual(client.get(second).status_code, 200)
            self.assertEqual(upload(first, 4, image.getvalue()).status_code, 200)

            word = client.get(report_url + "/download/document")
            self.assertTrue(word.is_success)
            self.assertIn(".docx", word.headers["content-disposition"])
            document = Document(BytesIO(word.content))
            self.assertEqual(len(document._element.xpath(".//w:drawing")), 3)
            for key in ("label-1", "size-4-weight"):
                slot = PHOTO_SLOTS[key]
                cell = document.tables[slot.table].cell(slot.row, slot.column)
                self.assertEqual(cell._tc.xpath(".//wp:docPr")[0].get("descr"), slot.label)
                self.assertIsNotNone(read_photo(report["excel_path"], key))
            self.assertEqual(client.post(report_url + "/approve", json={"expected_revision": 5}).status_code, 200)
            self.assertEqual(upload(first, 6, image.getvalue()).status_code, 409)
