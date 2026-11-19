import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZipFile

import openpyxl
from pypdf import PdfReader

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database
from services.excel_filler import ExcelFiller
from services.printer_service import PrinterService
from services.report_generator import ReportGenerator


class ReportGenerationTests(unittest.TestCase):
    def assert_havells_layout_preserved(self, template, report):
        main_sheet = "xl/worksheets/sheet1.xml"
        with ZipFile(template) as original, ZipFile(report) as generated:
            self.assertCountEqual(original.namelist(), generated.namelist())
            for part in original.namelist():
                if part != main_sheet:
                    self.assertTrue(original.read(part) == generated.read(part), f"Workbook part changed: {part}")

            def layout(archive):
                sheet = ElementTree.fromstring(archive.read(main_sheet))
                for cell in sheet.findall(".//{*}sheetData/{*}row/{*}c"):
                    cell.attrib.pop("t", None)
                    for child in list(cell):
                        if child.tag.rsplit("}", 1)[-1] in {"v", "is"}:
                            cell.remove(child)
                return ElementTree.tostring(sheet)

            self.assertTrue(layout(original) == layout(generated), "Surface Pump worksheet layout changed")

    def test_other_customers_get_one_report_with_the_full_lot_quantity(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            database, "DB_PATH", os.path.join(temp_dir, "test.db")
        ):
            database.init_db()
            for customer, template in (
                ("Falcon", "Falcon_PDI.xlsx"),
                ("KSB", "KSB -PDI Report Format.xlsx"),
            ):
                with self.subTest(customer=customer):
                    conn = database.get_db()
                    try:
                        template_id = conn.execute(
                            "SELECT id FROM pdi_templates WHERE template_name = ?", (template,)
                        ).fetchone()["id"]
                    finally:
                        conn.close()

                    result = ReportGenerator().generate_batch_reports({
                        "template_id": template_id,
                        "company_name": customer,
                        "product_type": "Surface Pump",
                        "product_number": "SKU-001",
                        "model_name": "Test Model",
                        "lot_size": 4001,
                        "po_number": "PO-001",
                    }, os.path.join(temp_dir, "reports"))

                    self.assertEqual(result["total_reports"], 1)
                    self.assertEqual(result["quantity_allocations"], [4001])
                    report, = result["reports"]
                    self.assertEqual(report["report_data"]["header_data"]["lot_qty"], "4001")

    def test_crompton_uses_excel_template_and_splits_lots_through_1200(self):
        import asyncio
        from routes.reports import generate_reports, save_report_update
        from schemas import ReportGenerateRequest, ReportUpdateRequest
        from services.crompton_report import NATIVE_SHEETS, TEMPLATE_NAME
        from services.report_generator import report_count_for_lot
        from services.template_matcher import TemplateMatcher

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            database, "DB_PATH", os.path.join(temp_dir, "test.db")
        ):
            database.init_db()
            match = TemplateMatcher().match_template("Crompton", "CMB", "MBD052(1PH)Y-18")
            self.assertEqual(match["template_name"], TEMPLATE_NAME)
            generator = ReportGenerator()
            data = {
                "template_id": match["template_id"], "company_name": "Crompton",
                "product_type": "CMB", "model_name": "MBD052(1PH)Y-18",
                "lot_size": 560,
                "serial_numbers": [f"SERIAL-{i:02}" for i in range(1, 21)],
            }
            with patch("routes.reports.REPORTS_DIR", temp_dir):
                job = asyncio.run(generate_reports(ReportGenerateRequest(**data)))
                large = asyncio.run(generate_reports(ReportGenerateRequest(**{**data, "lot_size": 1201})))
            report, second = job["reports"]
            self.assertEqual(large["total_reports"], 2)
            self.assertIn(data["model_name"], second["report_code"])
            self.assertEqual([item["report_data"]["header_data"]["model_name"] for item in job["reports"]],
                             [data["model_name"]] * 2)
            self.assertEqual(job["quantity_allocations"], [280, 280])
            self.assertEqual([item["report_data"]["header_data"]["lot_qty"] for item in job["reports"]], ["560", "560"])
            self.assertEqual(second["report_data"]["sample_serials"]["G"], "SERIAL-11")
            for first_check, second_check in zip(
                report["report_data"]["checkpoints"], second["report_data"]["checkpoints"]
            ):
                expected = first_check["observations"].copy()
                if first_check["row_index"] >= 22:
                    expected.update(dict.fromkeys("JKLMNOP", "-"))
                    for column in "GHI":
                        if first_check["row_index"] <= 23:
                            expected[column] = "✓"
                        elif expected[column] == "✓":
                            expected[column] = "-"
                self.assertEqual(second_check["observations"], expected, first_check["parameter"])
            for item in (report, second):
                workbook = openpyxl.load_workbook(item["excel_path"], read_only=True)
                try:
                    self.assertEqual(workbook["Table 2"]["C15"].value, 560)
                    self.assertEqual(item["report_data"]["header_data"]["final_judgment"], "")
                finally:
                    workbook.close()
            self.assertEqual(report["report_data"]["checkpoints"][5]["observations"]["J"], "✓")
            zero = generator.generate_batch_reports({**data, "lot_size": 0}, temp_dir)
            self.assertEqual(zero["quantity_allocations"], [0, 0])
            self.assertEqual(zero["reports"][0]["report_data"]["header_data"]["lot_qty"], "0")
            self.assertEqual(report_count_for_lot(1200, is_crompton=True), 2)
            self.assertEqual(report_count_for_lot(1201, is_crompton=True), 1)
            self.assertEqual(len(report["report_data"]["sample_columns"]), 10)
            self.assertEqual(len(report["report_data"]["checkpoints"]), 16)
            self.assertEqual(tuple(report["report_data"]["sheet_names"]), NATIVE_SHEETS)
            self.assertEqual(report["report_data"]["checkpoints"][1]["observations"]["G"], "∞")
            self.assertEqual(report["report_data"]["header_data"]["final_judgment"], "")
            saved = save_report_update(report["id"], ReportUpdateRequest(
                expected_revision=1,
                header_data={"tds_reference": "TDS-202", "note": "Check confirmed", "inspected_by": "QA Tester"},
                observation_readings={"17": {"P": "PASS", "U": "Verified"}, "32": {"G": "42.5"}},
                final_judgment="Passed after Rework",
            ))
            self.assertEqual(saved["report_data"]["header_data"]["final_judgment"], "Passed after Rework")
            saved_second = save_report_update(second["id"], ReportUpdateRequest(
                expected_revision=1, final_judgment="Direct Pass",
                header_data={"model_name": "Updated second report", "lot_qty": 561, "po_number": "SECOND-PO"},
                observation_readings={"16": {"G": "UPDATED-SERIAL"}, "22": {"G": "RECHECK", "J": "CHECKED-LATER"}},
            ))
            self.assertEqual(saved_second["report_data"]["header_data"]["final_judgment"], "Direct Pass")
            self.assertEqual(saved_second["report_data"]["header_data"]["po_number"], "SECOND-PO")
            self.assertEqual(saved_second["report_data"]["sample_serials"]["G"], "UPDATED-SERIAL")
            second_major = next(check for check in saved_second["report_data"]["checkpoints"] if check["row_index"] == 22)
            self.assertEqual((second_major["observations"]["G"], second_major["observations"]["J"]), ("RECHECK", "CHECKED-LATER"))
            with ZipFile(BACKEND_ROOT / "templates" / TEMPLATE_NAME) as source, ZipFile(report["excel_path"]) as actual:
                for part in source.namelist():
                    if part not in {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"}:
                        self.assertEqual(actual.read(part), source.read(part), part)
            output = PdfReader(generator.convert_to_pdf(report["id"]))
            self.assertEqual(len(output.pages), 2)
            self.assertTrue(all(page.mediabox.width > page.mediabox.height for page in output.pages))
            page_one, page_two = [" ".join(page.extract_text().split()) for page in output.pages]
            for text in ("MBD052(1PH)Y-18", "560", "TDS-202", "PASS", "Verified"):
                self.assertIn(text, page_one)
            self.assertRegex(page_one, r"SERIAL-\s*10\b")
            for text in ("42.5", "QA Tester", "Check confirmed"):
                self.assertIn(text, page_two)
            second_pdf = PdfReader(generator.convert_to_pdf(second["id"]))
            self.assertIn("561", second_pdf.pages[0].extract_text())
            self.assertIn("561", second_pdf.pages[1].extract_text())
            self.assertIn("Updated second report", second_pdf.pages[0].extract_text())

    def test_ksb_uses_the_registered_layout_and_all_fourteen_sample_columns(self):
        from services.template_matcher import TemplateMatcher

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            database, "DB_PATH", os.path.join(temp_dir, "test.db")
        ):
            database.init_db()
            match = TemplateMatcher().match_template("KSB", "Open Well", "SMARTY II PLUS")
            self.assertEqual(match["template_name"], "KSB -PDI Report Format.xlsx")
            generator = ReportGenerator()
            job = generator.generate_batch_reports({
                "template_id": match["template_id"],
                "company_name": "KSB",
                "product_type": "Open Well",
                "model_name": "SMARTY II PLUS",
                "product_number": "TEST-SKU",
                "po_number": "TEST-PO",
                "lot_size": 175,
                "observation_overrides": {"16": {"T": "SERIAL-14"}, "17": {"T": "Sample verified", "U": "Remark verified"}},
            }, temp_dir)
            report, = job["reports"]
            details = report["report_data"]
            self.assertEqual(len(details["checkpoints"]), 22)
            self.assertEqual(len(details["sample_columns"]), 14)
            self.assertEqual(details["sample_serials"]["T"], "SERIAL-14")
            self.assertFalse(details["header_data"]["judgment_ok"])
            workbook = openpyxl.load_workbook(report["excel_path"])
            try:
                self.assertEqual(workbook.active.title, "KSB PDI FORMAT")
                self.assertIn("$B$1:$U$47", workbook.active.print_area)
                self.assertEqual(workbook.active["D5"].value, "Open Well")
                self.assertEqual(workbook.active["D6"].value, "SMARTY II PLUS")
                self.assertEqual(workbook.active["L5"].value, 175)
                self.assertEqual(workbook.active["T17"].value, "Sample verified")
                self.assertEqual(workbook.active["U17"].value, "Remark verified")
                self.assertEqual(workbook["Sheet1"]["L9"].value, "=J9*1000/60")
            finally:
                workbook.close()
            pdf = PdfReader(generator.convert_to_pdf(report["id"]))
            text = "\n".join(page.extract_text() for page in pdf.pages)
            self.assertIn("SERIAL-14", "".join(text.split()))
            self.assertIn("Remark verified", " ".join(text.split()))

    def assert_sample_column_numbers(self, sheet, unit_index):
        first_sample_number = (unit_index - 1) * 5 + 1
        self.assertEqual(sheet["G8"].value, "Observation -  Sr. No")
        self.assertEqual(
            [sheet.cell(row=9, column=column).value for column in range(7, 12)],
            list(range(first_sample_number, first_sample_number + 5)),
        )

    def assert_havells_sample_observations(self, sheet):
        expected_specs = {
            "D49": "RPM (              ) , ",
            "D50": "\nPower (               ), ",
            "D51": "Current (     ),",
            "D54": "Discharge range, ",
            "D55": "\nOverall Effi, ",
            "D56": "\nMaximum Current, ",
            "D57": "Maximum Power, ",
        }
        for cell, expected in expected_specs.items():
            self.assertEqual(sheet[cell].value, expected)

        expected_samples = {
            49: [2952, "-", "-", "-", 2981],
            50: [163, "-", "-", "-", 162],
            51: [0.84, "-", "-", "-", 0.81],
            54: ["2711/720", "-", "-", "-", "2716/700"],
            56: [2.3, "-", "-", "-", 2.4],
            57: [524, "-", "-", "-", 528],
            58: [2739, "-", "-", "-", 2740],
        }
        for row, expected in expected_samples.items():
            self.assertEqual(
                [sheet.cell(row, column).value for column in range(7, 12)],
                expected,
            )
        self.assertEqual(sheet["G49"].number_format, "General")
        self.assertEqual(sheet["G51"].number_format, "General")
        self.assertEqual(sheet["G55"].value, "N/A")
        self.assertEqual(sheet["K55"].value, "N/A")

    def test_reject_judgment_writes_reason_to_merged_cell(self):
        original_db_path = database.DB_PATH
        template = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates", "Havells_Surface_Pump_PDI.xlsx"))
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = os.path.join(temp_dir, "test.db")
            try:
                database.init_db()
                conn = database.get_db()
                template_id = conn.execute(
                    "SELECT id FROM pdi_templates WHERE template_name = ?",
                    ("Havells_Surface_Pump_PDI.xlsx",),
                ).fetchone()["id"]
                conn.close()

                output_path = os.path.join(temp_dir, "reject-report.xlsx")
                ExcelFiller().populate_template(
                    template_file_path=template,
                    output_file_path=output_path,
                    template_id=template_id,
                    data={
                        "product_number": "HV-101",
                        "final_judgment": "Reject",
                        "reject_reason": "Bearing noise",
                    },
                )

                workbook = openpyxl.load_workbook(output_path, data_only=True)
                sheet = workbook["Surface Pump"]
                self.assertEqual(sheet["F5"].value, "Reject [✔]")
                self.assertEqual(sheet["E6"].value, "Bearing noise")
                workbook.close()
                self.assert_havells_layout_preserved(template, output_path)
            finally:
                database.DB_PATH = original_db_path

    def test_two_reports_split_101_units_and_preserve_template(self):
        original_db_path = database.DB_PATH
        template = os.path.join(os.path.dirname(__file__), "..", "templates", "Havells_Surface_Pump_PDI.xlsx")
        template = os.path.abspath(template)
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = os.path.join(temp_dir, "test.db")
            with open(template, "rb") as template_file:
                template_before = template_file.read()
            template_wb = openpyxl.load_workbook(template, data_only=True)
            template_ws = template_wb["Surface Pump"]
            preserved_cells = {cell: template_ws[cell].value for cell in ("E5", "F5", "C7", "C6", "G10", "G44", "K44")}
            template_wb.close()
            try:
                database.init_db()
                conn = database.get_db()
                template_id = conn.execute(
                    "SELECT id FROM pdi_templates WHERE template_name = ?",
                    ("Havells_Surface_Pump_PDI.xlsx",),
                ).fetchone()["id"]
                conn.close()

                result = ReportGenerator().generate_batch_reports({
                    "template_id": template_id,
                    "company_name": "Havells",
                    "product_type": "Surface Pump",
                    "product_number": "HV-101",
                    "model_name": "Test Model",
                    "lot_size": 101,
                    "po_number": "PO-101",
                    "supplier_name": "Yathi Pumps Pvt. Ltd.",
                    "supplier_location": "Coimbatore, Tamil Nadu",
                }, os.path.join(temp_dir, "reports"))

                self.assertEqual(result["total_reports"], 2)
                self.assertEqual(result["quantity_allocations"], [51, 50])
                self.assertEqual(len(result["reports"]), 2)
                self.assertEqual(result["legal_status"], "Awaiting Review")
                legal_workbook = openpyxl.load_workbook(result["legal_excel_path"], data_only=True)
                legal_sheet = legal_workbook["J1"]
                self.assertEqual(legal_workbook.sheetnames, ["J1"])
                self.assertEqual(legal_sheet["A2"].value, "Product : Test Model")
                self.assertEqual(legal_sheet["D2"].value, "Lot Quantity : 101")
                self.assertEqual(legal_sheet["A3"].value, "Model SKU No : HV-101")
                for row in range(5, 20):
                    self.assertEqual(legal_sheet[f"H{row}"].value, None if row == 13 else "OK")
                legal_workbook.close()
                quantities = []
                for unit_index, report in enumerate(result["reports"], start=1):
                    self.assert_havells_layout_preserved(template, report["excel_path"])
                    workbook = openpyxl.load_workbook(report["excel_path"], data_only=True)
                    self.assertEqual(workbook.active.title, "Surface Pump")
                    sheet = workbook["Surface Pump"]
                    self.assert_sample_column_numbers(sheet, unit_index)
                    quantities.append(sheet["D5"].value)
                    for cell, expected_value in preserved_cells.items():
                        self.assertEqual(sheet[cell].value, expected_value, f"Template value changed at {cell}")
                    self.assertEqual(sheet["C3"].value, "Yathi Pumps")
                    self.assertEqual(sheet["F3"].value, "Coimbatore")
                    self.assertEqual(sheet["D4"].value, "Model Name : Test Model")
                    self.assertEqual(sheet["C4"].value, "HV-101")
                    self.assertEqual(sheet["C5"].value, "PO-101")
                    self.assertEqual(sheet["G24"].value, "0.02 mm")
                    self.assertEqual(sheet["G44"].value, "2.14")
                    self.assertEqual(sheet["K44"].value, "2.13")
                    self.assert_havells_sample_observations(sheet)
                    self.assertEqual(sheet["G80"].value, "OK")
                    self.assertEqual(sheet["G74"].value, "> 50 Mic")
                    self.assertEqual(sheet["G64"].value, ">30%")
                    workbook.close()
                self.assertEqual(quantities, ["Lot Qty : 51", "Lot Qty : 50"])
                edited_path = os.path.join(temp_dir, "reviewed-report.xlsx")
                ExcelFiller().populate_template(
                    template_file_path=result["reports"][0]["excel_path"],
                    output_file_path=edited_path,
                    template_id=template_id,
                    data={"company_name": "Havells", "final_judgment": "OK"},
                    observation_overrides={"24": {"G": "0.03 mm"}, "49": {"G": "2952"}},
                )
                self.assert_havells_layout_preserved(template, edited_path)
                edited = openpyxl.load_workbook(edited_path, data_only=True)
                self.assertEqual(edited["Surface Pump"]["G24"].value, "0.03 mm")
                self.assertEqual(edited["Surface Pump"]["G49"].value, 2952)
                self.assertEqual(edited["Surface Pump"]["E5"].value, "OK [✔]")
                edited.close()

                second_model = ReportGenerator().generate_batch_reports({
                    "template_id": template_id,
                    "company_name": "Havells",
                    "product_type": "Submersible Pump",
                    "product_number": "HV-202",
                    "model_name": "Test Model B",
                    "lot_size": 75,
                    "po_number": "PO-202",
                }, os.path.join(temp_dir, "reports"))
                self.assertEqual(second_model["total_reports"], 1)
                second_workbook = openpyxl.load_workbook(
                    second_model["reports"][0]["excel_path"],
                    data_only=True,
                )
                second_sheet = second_workbook["Surface Pump"]
                self.assert_sample_column_numbers(second_sheet, 1)
                self.assertEqual(second_sheet["C4"].value, "HV-202")
                self.assertEqual(second_sheet["D4"].value, "Model Name : Test Model B")
                self.assertEqual(second_sheet["C5"].value, "PO-202")
                self.assertEqual(second_sheet["D5"].value, "Lot Qty : 75")
                self.assertEqual(second_sheet["G24"].value, "0.02 mm")
                self.assertEqual(second_sheet["G44"].value, "2.14")
                self.assertEqual(second_sheet["K44"].value, "2.13")
                self.assert_havells_sample_observations(second_sheet)
                self.assertEqual(second_sheet["G80"].value, "OK")
                self.assertEqual(second_sheet["G74"].value, "> 50 Mic")
                self.assertEqual(second_sheet["G64"].value, ">30%")
                second_workbook.close()

                three_report_model = ReportGenerator().generate_batch_reports({
                    "template_id": template_id,
                    "company_name": "Havells",
                    "product_type": "Surface Pump",
                    "product_number": "HV-303",
                    "model_name": "Test Model C",
                    "lot_size": 2500,
                    "po_number": "PO-303",
                }, os.path.join(temp_dir, "reports"))
                self.assertEqual(three_report_model["total_reports"], 3)
                for unit_index, report in enumerate(three_report_model["reports"], start=1):
                    workbook = openpyxl.load_workbook(report["excel_path"], data_only=True)
                    self.assert_sample_column_numbers(workbook["Surface Pump"], unit_index)
                    workbook.close()
                second_report_pdf = ReportGenerator().convert_to_pdf(
                    three_report_model["reports"][1]["id"]
                )
                second_pdf_text = " ".join(
                    " ".join((page.extract_text() or "").split())
                    for page in PdfReader(second_report_pdf).pages
                )
                self.assertIn("Pump - Pre-dispatch Inspection Report", second_pdf_text)
                self.assertRegex(second_pdf_text, r"\b6\s+7\s+8\s+9\s+10\b")
                for preset in ("0.02 mm", "2952", "0.84", "2711/720", "2.4", "SST Hrs Check"):
                    self.assertIn(preset, second_pdf_text)
                self.assertNotIn("PA001", second_pdf_text)

                first_report = result["reports"][0]
                pdf_path = ReportGenerator().convert_to_pdf(first_report["id"])
                ExcelFiller().populate_template(
                    template_file_path=first_report["excel_path"],
                    output_file_path=first_report["excel_path"],
                    template_id=template_id,
                    data={"company_name": "Havells"},
                    observation_overrides={
                        "29": {"G": "Updated bearing reading"},
                        "44": {column: f"sample {column}" for column in "GHIJK"},
                    },
                )

                refreshed_pdf = ReportGenerator().convert_to_pdf(first_report["id"])
                pdf_text = " ".join(
                    " ".join((page.extract_text() or "").split())
                    for page in PdfReader(refreshed_pdf).pages
                )
                self.assertEqual(refreshed_pdf, pdf_path)
                self.assertRegex(pdf_text, r"\b1\s+2\s+3\s+4\s+5\b")
                for value in (
                    "Updated bearing reading", "Bearing Noise", "< 65 Dba",
                    "sample G", "sample H", "sample I", "sample J", "sample K",
                ):
                    self.assertIn(value, pdf_text)

                printer = PrinterService()
                with patch.object(printer, "print_file", return_value={"success": True}) as print_file:
                    print_result = printer.execute_job_print(result["job_id"], printer_name="Test Printer")
                self.assertEqual(print_result["success_count"], 2)
                self.assertEqual(print_file.call_count, 2)

                with open(template, "rb") as template_file:
                    self.assertEqual(template_file.read(), template_before)
            finally:
                database.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
