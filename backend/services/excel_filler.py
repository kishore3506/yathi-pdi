import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from typing import Dict, Any, List, Optional
import os
import logging
from collections import defaultdict
from openpyxl.cell.cell import MergedCell

try:
    from ..database import get_db
    from .falcon_report import CHECKPOINT_Y, PLACEHOLDER, SHEET_NAME, VERDICTS
    from .ksb_report import SHEET_NAME as KSB_SHEET_NAME, fill_ksb_sheet
    from .xlsx_cell_values import write_cell_values
except (ImportError, ValueError):
    from database import get_db
    from services.falcon_report import CHECKPOINT_Y, PLACEHOLDER, SHEET_NAME, VERDICTS
    from services.ksb_report import SHEET_NAME as KSB_SHEET_NAME, fill_ksb_sheet
    from services.xlsx_cell_values import write_cell_values

logger = logging.getLogger(__name__)

SUPPLIER_NAME = "Yathi Pumps"
SUPPLIER_LOCATION = "Coimbatore"

class ExcelFiller:
    def __init__(self):
        pass

    def get_mappings_for_template(self, template_id: int) -> List[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT field_key, field_label, target_sheet, target_cell,
                   is_header_field, default_value, is_required, validation_rule
            FROM template_field_mappings
            WHERE template_id = ?
        """, (template_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    def populate_template(
        self,
        template_file_path: str,
        output_file_path: str,
        template_id: int,
        data: Dict[str, Any],
        observation_overrides: Optional[Dict[str, Any]] = None,
        unit_index: int = 1,
        serial_number: Optional[str] = None
    ) -> str:
        """
        Populate an Excel report template using field mappings while strictly preserving:
        - Original styles, borders, colors, and layout
        - Fixed inspection criteria and standards
        - Company branding and images
        - Formulas
        """
        if not os.path.exists(template_file_path):
            raise FileNotFoundError(f"Template not found: {template_file_path}")

        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

        preserve_havells = str(data.get("company_name") or "").strip().casefold() == "havells" or (
            os.path.basename(template_file_path) == "Havells_Surface_Pump_PDI.xlsx"
        )
        wb = openpyxl.load_workbook(template_file_path, data_only=False)
        if KSB_SHEET_NAME in wb.sheetnames:
            values = {**data, "supplier_name": SUPPLIER_NAME, "supplier_location": SUPPLIER_LOCATION}
            fill_ksb_sheet(wb[KSB_SHEET_NAME], values, observation_overrides, serial_number)
            wb.save(output_file_path)
            wb.close()
            return output_file_path
        mappings = self.get_mappings_for_template(template_id)
        mapping_dict = {m["field_key"]: m for m in mappings}

        if SHEET_NAME in wb.sheetnames:
            values = {
                **data,
                "supplier_name": SUPPLIER_NAME,
                "sku_no": data.get("product_number"),
                "lot_qty": data.get("lot_size"),
                "serial_number": serial_number,
            }
            for key, mapping in mapping_dict.items():
                value = values.get(key)
                if value is None:
                    continue
                cell = wb[mapping["target_sheet"]][mapping["target_cell"]]
                if key in {"lot_qty", "po_total_qty"} and str(value).isdecimal():
                    cell.value = int(value)
                else:
                    cell.value = str(value)
                    cell.data_type = "s"

            sheet = wb[SHEET_NAME]
            for row in CHECKPOINT_Y:
                override = (observation_overrides or {}).get(str(row))
                if isinstance(override, dict):
                    override = override.get("G")
                if isinstance(override, str) and (override in VERDICTS or override == ""):
                    sheet[f"G{row}"] = override or PLACEHOLDER
            wb.save(output_file_path)
            wb.close()
            return output_file_path

        primary_sheet = "Surface Pump"
        ws = wb[primary_sheet] if primary_sheet in wb.sheetnames else wb.active
        values_by_sheet = defaultdict(dict)

        def set_cell(sheet, address, value):
            cell = sheet[address]
            if preserve_havells:
                if isinstance(cell, MergedCell) or cell.value == value:
                    return
                display_value = "" if cell.value is None else str(cell.value)
                if value == display_value:
                    return
            cell.value = value
            if preserve_havells:
                values_by_sheet[sheet.title][cell.coordinate] = cell.value

        if not ws["G8"].value:
            set_cell(ws, "G8", "Observation")
        first_sample_number = (unit_index - 1) * 5 + 1
        for sample_offset, column in enumerate(range(7, 12)):
            set_cell(ws, ws.cell(row=9, column=column).coordinate, first_sample_number + sample_offset)

        def set_mapped_cell(key: str, raw_value: Any):
            mapping = mapping_dict.get(key)
            if not mapping or raw_value is None or str(raw_value).strip() == "":
                return

            sheet_name = mapping["target_sheet"]
            target_ws = wb[sheet_name] if sheet_name in wb.sheetnames else ws
            cell_coord = mapping["target_cell"]
            rule = mapping.get("validation_rule") or ""

            val_str = str(raw_value).strip()
            if rule.startswith("prefix:"):
                prefix = rule[len("prefix:"):]
                final_val = f"{prefix}{val_str}"
            else:
                final_val = val_str

            set_cell(target_ws, cell_coord, final_val)

        # Populate standard header fields
        set_mapped_cell("supplier_name", SUPPLIER_NAME)
        set_mapped_cell("supplier_location", SUPPLIER_LOCATION)
        set_mapped_cell("sku_no", data.get("product_number"))
        set_mapped_cell("model_name", data.get("model_name"))
        set_mapped_cell("po_number", data.get("po_number"))
        set_mapped_cell("lot_qty", data.get("lot_size"))
        set_mapped_cell("po_total_qty", data.get("po_total_qty"))
        set_mapped_cell("inspected_by", data.get("inspected_by"))
        set_mapped_cell("approved_by", data.get("approved_by"))
        set_mapped_cell("total_dispatched_qty", data.get("total_dispatched_qty"))
        set_mapped_cell("residual_qty", data.get("residual_qty"))

        if data.get("inspection_date"):
            set_mapped_cell("inspection_date", data.get("inspection_date"))
        if data.get("lot_dispatch_date"):
            set_mapped_cell("lot_dispatch_date", data.get("lot_dispatch_date"))

        final_judgment = (data.get("final_judgment") or "").upper()
        ok_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        reject_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

        if "REJECT" in final_judgment:
            set_cell(ws, "E5", None)
            set_cell(ws, "F5", "Reject [✔]")
            if not preserve_havells:
                ws["F5"].fill = reject_fill
            if data.get("reject_reason"):
                set_cell(ws, "E6", data.get("reject_reason"))
        elif final_judgment in {"OK", "PASS", "ACCEPT"}:
            set_cell(ws, "E5", "OK [✔]")
            set_cell(ws, "F5", "Reject")
            if not preserve_havells:
                ws["E5"].fill = ok_fill

        if serial_number:
            set_cell(ws, "C4", f"{data.get('product_number', '')} / S/N: {serial_number}")

        if observation_overrides:
            for row_key, obs_val in observation_overrides.items():
                try:
                    r_idx = int(row_key)
                    if isinstance(obs_val, dict):
                        for col_letter, c_val in obs_val.items():
                            if c_val is not None:
                                set_cell(ws, f"{col_letter}{r_idx}", str(c_val))
                    else:
                        set_cell(ws, f"G{r_idx}", str(obs_val))
                except Exception as e:
                    logger.warning(f"Failed to apply override at row {row_key}: {e}")

        if preserve_havells:
            write_cell_values(template_file_path, output_file_path, values_by_sheet)
        else:
            wb.save(output_file_path)
        wb.close()
        return output_file_path
