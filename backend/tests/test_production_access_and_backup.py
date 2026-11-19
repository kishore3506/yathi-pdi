import os
import sys
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
import main
from auth import password_hasher
from fastapi.testclient import TestClient
from main import app
from openpyxl import load_workbook
from services import portable_backup


class ProductionAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = str(Path(self.temp_dir.name) / "pdi_system.db")
        database.init_db()
        self._create_user("inspector@example.com", "inspector", "inspector-password")
        self._create_user("approver@example.com", "approver", "approver-password")
        self._create_report()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _create_user(self, email, role, password):
        conn = database.get_db()
        conn.execute(
            """
            INSERT INTO users (email, display_name, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, '2026-01-01', '2026-01-01')
            """,
            (email, role.title(), password_hasher.hash(password), role),
        )
        conn.commit()
        conn.close()

    def _create_report(self):
        conn = database.get_db()
        cursor = conn.execute(
            """
            INSERT INTO report_jobs (
                job_code, company_name, product_type, lot_size, status, created_at, updated_at
            ) VALUES ('JOB-REVISION', 'Crompton', 'Pump', 1, 'Awaiting Review', '2026-01-01', '2026-01-01')
            """
        )
        conn.execute(
            """
            INSERT INTO generated_reports (
                job_id, report_code, unit_index, excel_path, status,
                report_data_json, created_at, updated_at, revision
            ) VALUES (?, 'REPORT-REVISION', 1, 'unused.xlsx', 'Awaiting Review',
                      '{}', '2026-01-01', '2026-01-01', 2)
            """,
            (cursor.lastrowid,),
        )
        conn.commit()
        conn.close()

    def test_api_requires_login_and_enforces_roles_and_revision(self):
        excel_path = Path(self.temp_dir.name) / "authorized-report.xlsx"
        excel_path.write_bytes(b"authorized test workbook")
        conn = database.get_db()
        conn.execute(
            "UPDATE generated_reports SET excel_path = ? WHERE id = 1",
            (str(excel_path),),
        )
        conn.commit()
        conn.close()

        with TestClient(app) as client:
            unauthenticated_reports = client.get("/api/reports")
            self.assertEqual(unauthenticated_reports.status_code, 401)
            self.assertEqual(
                unauthenticated_reports.headers["cache-control"],
                "no-store, max-age=0",
            )
            self.assertEqual(
                client.get("/api/reports/1/download/excel").status_code,
                401,
            )
            self.assertEqual(client.get("/api/admin/backup").status_code, 401)
            self.assertEqual(client.get("/api/admin/backup/excel").status_code, 401)
            self.assertEqual(client.get("/api/auth/setup/status").status_code, 200)

            login = client.post(
                "/api/auth/login",
                json={"email": " INSPECTOR@EXAMPLE.COM ", "password": "inspector-password"},
            )
            self.assertEqual(login.status_code, 200)
            workbook_download = client.get("/api/reports/1/download/excel")
            self.assertEqual(workbook_download.status_code, 200)
            self.assertEqual(workbook_download.content, b"authorized test workbook")
            self.assertEqual(client.get("/api/auth/users").status_code, 403)
            self.assertEqual(client.get("/api/admin/backup").status_code, 403)
            self.assertEqual(client.get("/api/admin/backup/excel").status_code, 403)
            self.assertEqual(
                client.post("/api/auth/users", json={}).status_code,
                403,
            )

            client.post("/api/auth/logout")
            login = client.post(
                "/api/auth/login",
                json={"email": "approver@example.com", "password": "approver-password"},
            )
            self.assertEqual(login.status_code, 200)
            stale_approval = client.post(
                "/api/reports/1/approve",
                json={"expected_revision": 1},
            )
            self.assertEqual(stale_approval.status_code, 409)

        conn = database.get_db()
        revision = conn.execute(
            "SELECT revision FROM generated_reports WHERE id = 1"
        ).fetchone()["revision"]
        conn.close()
        self.assertEqual(revision, 2)

    def test_unexpected_api_error_is_generic_and_not_cacheable(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            with patch.object(main, "get_db", side_effect=RuntimeError("private document text")):
                response = client.get("/api/health")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
        self.assertNotIn("private document text", response.text)

    def test_local_dashboard_and_report_approval_without_employee_accounts(self):
        with patch.object(main, "APP_ENV", "development"), TestClient(
            app, base_url="http://127.0.0.1:8001", client=("127.0.0.1", 50000)
        ) as client:
            session = client.get("/api/auth/me")
            self.assertEqual(session.json(), {"local_access": True, "role": "administrator"})
            self.assertNotIn("set-cookie", session.headers)
            self.assertEqual(client.get("/api/dashboard/stats").status_code, 200)
            self.assertEqual(client.get("/api/reports").status_code, 200)
            self.assertEqual(client.get("/api/auth/users").status_code, 404)
            self.assertEqual(client.post("/api/auth/login", json={}).status_code, 404)
            approval = {"expected_revision": 2}
            self.assertEqual(client.post(
                "/api/reports/1/approve", json=approval, headers={"Origin": "https://elsewhere.example"}
            ).status_code, 403)
            self.assertEqual(client.post(
                "/api/reports/1/approve", json=approval, headers={"Origin": "http://127.0.0.1:8001"}
            ).json()["status"], "Approved")

        with TestClient(app, base_url="http://127.0.0.1:8001", client=("192.0.2.1", 50000)) as client:
            self.assertEqual(client.get("/api/dashboard/stats").status_code, 401)

    def test_excel_copy_updates_after_commit_and_downloads_current_data(self):
        backup_dir = Path(self.temp_dir.name) / "backups"
        with patch.object(main, "APP_ENV", "development"), patch.object(main, "BACKUP_DIR", backup_dir), TestClient(
            app, base_url="http://127.0.0.1:8001", client=("127.0.0.1", 50000)
        ) as client:
            initial = client.get("/api/admin/backup/excel")
            self.assertEqual(initial.status_code, 200)
            self.assertIn("PDI Data.xlsx", unquote(initial.headers["content-disposition"]))
            self.assertEqual(initial.headers["cache-control"], "no-store, max-age=0")
            snapshot = backup_dir / "PDI Data.xlsx"
            original_mtime = snapshot.stat().st_mtime_ns
            long_value = "reading:" + "A" * 33_000
            db = database.get_db()
            try:
                with db:
                    db.execute("UPDATE report_jobs SET model_name = '=Literal model' WHERE id = 1")
                    db.execute("UPDATE generated_reports SET report_data_json = ? WHERE id = 1", (long_value,))
            finally:
                db.close()

            deadline = time.monotonic() + 10
            while snapshot.stat().st_mtime_ns == original_mtime and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertNotEqual(snapshot.stat().st_mtime_ns, original_mtime)

            response = client.get("/api/admin/backup/excel")
            workbook = load_workbook(BytesIO(response.content), read_only=True)
            try:
                jobs = iter(workbook["Inspection Jobs"].iter_rows())
                header = [cell.value for cell in next(jobs)]
                model = next(jobs)[header.index("model_name")]
                self.assertEqual((model.value, model.data_type), ("=Literal model", "s"))
                chunks = list(workbook["Long Values"].values)[1:]
                self.assertEqual("".join(row[-1] for row in chunks), long_value)
                self.assertNotIn("users", workbook.sheetnames)
                self.assertNotIn("webhook_url", list(workbook["Email History"].values)[0])
            finally:
                workbook.close()

    def test_dashboard_groups_customers_and_review_lists_older_models(self):
        db = database.get_db()
        try:
            with db:
                db.executemany("""
                    INSERT INTO report_jobs
                        (job_code, company_name, product_type, model_name, lot_size, status, created_at, updated_at)
                    VALUES (?, ?, 'Pump', ?, 1, 'Awaiting Review', ?, '2026-01-03')
                """, [
                    (
                        f"JOB-HAVELLS-{index}", " Havells " if index == 1 else "Havells",
                        f"Model {index}", f"2026-01-02T{index % 12:02}:42:00",
                    )
                    for index in range(1, 13)
                ])
        finally:
            db.close()
        with patch.object(main, "APP_ENV", "development"), TestClient(
            app, base_url="http://127.0.0.1:8001", client=("127.0.0.1", 50000)
        ) as client:
            stats = client.get("/api/dashboard/stats").json()
            self.assertEqual(stats["recent_customers"], ["Havells", "Crompton"])
            self.assertEqual(stats["recent_customer_activity"][0], {
                "company_name": "Havells",
                "created_at": "2026-01-02T11:42:00",
            })
            models = client.get("/api/dashboard/customer-jobs", params={"customer": "HAVELLS"}).json()
            self.assertEqual([job["model_name"] for job in models], [f"Model {index}" for index in range(12, 0, -1)])
            self.assertEqual(client.get("/api/dashboard/customer-jobs", params={"customer": "KSB"}).json(), [])


class TemplateSeedTests(unittest.TestCase):
    def test_initialization_does_not_replace_a_registered_template(self):
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = str(Path(temp_dir) / "pdi_system.db")
            try:
                database.init_db()
                registered_path = Path(temp_dir) / "registered-template.xlsx"
                registered_path.write_bytes(b"registered employee template")
                conn = database.get_db()
                conn.execute(
                    "UPDATE pdi_templates SET file_path = ?, template_name = ? WHERE template_name = ?",
                    (
                        str(registered_path),
                        "Employee Registered Copy.xlsx",
                        "Havells_Surface_Pump_PDI.xlsx",
                    ),
                )
                conn.commit()
                conn.close()

                database.init_db()
                conn = database.get_db()
                template = conn.execute(
                    "SELECT file_path, template_name FROM pdi_templates "
                    "WHERE template_name = 'Employee Registered Copy.xlsx'"
                ).fetchone()
                conn.close()
                self.assertEqual(template["file_path"], str(registered_path))
                self.assertEqual(registered_path.read_bytes(), b"registered employee template")
            finally:
                database.DB_PATH = original_db_path


class PortableBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.target_db_path = Path(self.temp_dir.name) / "cloud.db"
        self.source_db_path = Path(self.temp_dir.name) / "source.db"
        self.storage = {
            "uploads": Path(self.temp_dir.name) / "imported_uploads",
            "templates": Path(self.temp_dir.name) / "imported_templates",
            "reports": Path(self.temp_dir.name) / "imported_reports",
        }
        self.storage_patcher = patch.dict(
            portable_backup._STORAGE_BY_CATEGORY,
            self.storage,
        )
        self.storage_patcher.start()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.storage_patcher.stop()
        self.temp_dir.cleanup()

    def _create_admin(self, email):
        conn = database.get_db()
        conn.execute(
            """
            INSERT INTO users (email, display_name, password_hash, role, created_at, updated_at)
            VALUES (?, 'Cloud Administrator', ?, 'administrator', '2026-01-01', '2026-01-01')
            """,
            (email, password_hasher.hash("admin-password-long")),
        )
        conn.commit()
        conn.close()

    def test_import_preserves_target_admin_and_rejects_reimport_over_business_data(self):
        database.DB_PATH = str(self.source_db_path)
        database.init_db()
        self._create_admin("source-admin@example.com")
        source_file = Path(self.temp_dir.name) / "purchase-order.pdf"
        source_file.write_bytes(b"test purchase order")
        conn = database.get_db()
        conn.execute(
            """
            INSERT INTO uploaded_requirements (
                filename, original_name, file_type, file_path, uploaded_at, status
            ) VALUES ('po.pdf', 'po.pdf', 'pdf', ?, '2026-01-01', 'Uploaded')
            """,
            (str(source_file),),
        )
        checklist = Path(self.temp_dir.name) / "pending-j1.xlsx"
        checklist.write_bytes(b"test J1 workbook")
        pending_pdf = str(checklist.with_suffix(".pdf"))
        conn.execute("""
            INSERT INTO report_jobs (
                job_code, company_name, product_type, lot_size, status, legal_status, legal_excel_path,
                legal_pdf_path, created_at, updated_at
            ) VALUES ('PENDING-J1', 'Havells', 'Pump', 1, 'Awaiting Review', 'Awaiting Review', ?, ?,
                '2026-01-01', '2026-01-01')
        """, (str(checklist), pending_pdf))
        conn.commit()
        conn.close()

        backup_path = Path(self.temp_dir.name) / "source-backup.zip"
        portable_backup.create_backup(backup_path)
        conn = database.get_db()
        self.assertEqual(conn.execute("SELECT legal_pdf_path FROM report_jobs").fetchone()[0], pending_pdf)
        conn.close()

        database.DB_PATH = str(self.target_db_path)
        database.init_db()
        self._create_admin("cloud-admin@example.com")
        result = portable_backup.import_backup(backup_path)
        self.assertEqual(result["status"], "Imported")

        conn = database.get_db()
        admin = conn.execute(
            "SELECT email FROM users WHERE email = 'cloud-admin@example.com'"
        ).fetchone()["email"]
        imported_path = conn.execute(
            "SELECT file_path FROM uploaded_requirements"
        ).fetchone()["file_path"]
        restored_checklist = conn.execute(
            "SELECT legal_excel_path, legal_pdf_path, legal_status FROM report_jobs"
        ).fetchone()
        conn.close()
        self.assertEqual(restored_checklist["legal_status"], "Awaiting Review")
        self.assertIsNone(restored_checklist["legal_pdf_path"])
        self.assertEqual(Path(restored_checklist["legal_excel_path"]).read_bytes(), b"test J1 workbook")
        self.assertEqual(admin, "cloud-admin@example.com")
        conn = database.get_db()
        imported_admin = conn.execute(
            "SELECT 1 FROM users WHERE email = 'source-admin@example.com'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(imported_admin)
        self.assertEqual(Path(imported_path).read_bytes(), b"test purchase order")

        with self.assertRaisesRegex(ValueError, "only before business records exist"):
            portable_backup.import_backup(backup_path)
        conn = database.get_db()
        count = conn.execute("SELECT COUNT(*) FROM uploaded_requirements").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
