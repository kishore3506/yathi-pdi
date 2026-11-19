import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from services.template_matcher import TemplateMatcher


class TemplateMatcherTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = database.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        database.init_db()

        conn = database.get_db()
        self.havells_company_id = conn.execute(
            "SELECT id FROM companies WHERE name = 'Havells'"
        ).fetchone()["id"]
        self.surface_template = conn.execute("""
            SELECT id, file_path
            FROM pdi_templates
            WHERE company_id = ? AND product_type = 'Surface Pump'
        """, (self.havells_company_id,)).fetchone()
        conn.execute("""
            INSERT INTO pdi_templates (
                company_id, product_type, product_model, template_name, file_path,
                sheet_names, primary_sheet, is_active, registration_date
            ) VALUES (?, 'Submersible Pump', 'Other Model', 'Other Havells Template',
                      ?, '[]', 'Surface Pump', 1, '2026-11-13')
        """, (self.havells_company_id, self.surface_template["file_path"]))
        conn.commit()
        conn.close()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_havells_models_always_match_surface_pump_template(self):
        result = TemplateMatcher().match_template(
            "Havells",
            "Submersible Pump",
            "Other Model",
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["template_id"], self.surface_template["id"])
        self.assertEqual(result["product_type"], "Surface Pump")

    def test_legacy_and_canonical_customer_names_resolve_to_ksb(self):
        matcher = TemplateMatcher()

        self.assertEqual(matcher.normalize_customer("KBS Pumps"), "KSB")
        self.assertEqual(matcher.normalize_customer("KSB Pumps"), "KSB")
        self.assertEqual(matcher.normalize_customer("KBL"), "KSB")

    def test_existing_kbs_company_and_template_are_migrated(self):
        conn = database.get_db()
        company = conn.execute(
            "SELECT id FROM companies WHERE name = 'KSB'"
        ).fetchone()
        conn.execute(
            "UPDATE companies SET name = 'KBS', code = 'KBS' WHERE id = ?",
            (company["id"],),
        )
        conn.execute("""
            UPDATE pdi_templates
            SET template_name = 'KBS_Surface_Pump_PDI.xlsx',
                file_path = 'legacy-template-path'
            WHERE company_id = ?
        """, (company["id"],))
        conn.commit()
        conn.close()

        database.init_db()

        conn = database.get_db()
        company = conn.execute(
            "SELECT id, code FROM companies WHERE name = 'KSB'"
        ).fetchone()
        template = conn.execute(
            "SELECT template_name, file_path FROM pdi_templates WHERE company_id = ?",
            (company["id"],),
        ).fetchone()
        conn.close()

        self.assertEqual(company["code"], "KSB")
        self.assertEqual(template["template_name"], "KSB_Surface_Pump_PDI.xlsx")
        self.assertTrue(template["file_path"].endswith("KSB_Surface_Pump_PDI.xlsx"))


if __name__ == "__main__":
    unittest.main()
