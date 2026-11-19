import base64
import binascii
import os
import shutil
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from openpyxl.drawing.image import Image as ExcelImage
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage, UnidentifiedImageError
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


LEGAL_SHEET_NAME = "J1"
MRP_ROW = 13
CHECKLIST_ROWS = tuple(range(5, 20))
LEGAL_IMAGE_SLOTS = {
    "carton_with_label": {"anchor": "B21", "max_width": 280},
    "product_name_plate": {"anchor": "F21", "max_width": 280},
    "technical_specs": {"anchor": "G21", "max_width": 350},
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_IMAGE_SIZE = (1600, 1200)
LEGAL_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "templates",
    "Havells_Legal_Compliance_Checklist.xlsx",
)


class LegalChecklistService:
    def __init__(self, template_path: str = LEGAL_TEMPLATE_PATH):
        self.template_path = template_path

    def generate_workbook(self, job_data: Dict[str, Any], output_path: str) -> str:
        if not os.path.isfile(self.template_path):
            raise FileNotFoundError(f"Havells legal checklist template not found: {self.template_path}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copyfile(self.template_path, output_path)
        workbook = load_workbook(output_path)
        if LEGAL_SHEET_NAME not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f"Legal checklist template is missing the {LEGAL_SHEET_NAME} sheet")

        for sheet_name in list(workbook.sheetnames):
            if sheet_name != LEGAL_SHEET_NAME:
                del workbook[sheet_name]

        sheet = workbook[LEGAL_SHEET_NAME]
        inspection_date = job_data.get("inspection_date") or datetime.now().strftime("%d-%m-%Y")
        sheet["G1"] = f"Inspection Date : {inspection_date}"
        sheet["A2"] = f"Product : {job_data.get('model_name') or job_data.get('product_type') or ''}"
        sheet["D2"] = f"Lot Quantity : {job_data.get('lot_size') or ''}"
        sheet["H2"] = job_data.get("inspected_by") or "Yathi QA Inspector"
        sheet["A3"] = f"Model SKU No : {job_data.get('product_number') or ''}"
        sheet["D3"] = "Lot Decision (Accept / Reject) : Pending Review"
        sheet["H3"] = job_data.get("approved_by") or "Quality Head"

        for row in CHECKLIST_ROWS:
            sheet[f"H{row}"] = None if row == MRP_ROW else "OK"
            sheet[f"J{row}"] = "-"

        workbook.save(output_path)
        workbook.close()
        return output_path

    @staticmethod
    def _anchor_cell(image: ExcelImage) -> str:
        anchor = image.anchor
        if isinstance(anchor, str):
            return anchor.upper()
        anchor_from = getattr(anchor, "_from", None)
        if anchor_from is None:
            return ""
        return f"{get_column_letter(anchor_from.col + 1)}{anchor_from.row + 1}"

    @staticmethod
    def _decode_image(data_url: str) -> bytes:
        header, separator, encoded = data_url.partition(",")
        if not separator or header not in {
            "data:image/png;base64",
            "data:image/jpeg;base64",
            "data:image/jpg;base64",
            "data:image/webp;base64",
            "data:image/gif;base64",
        }:
            raise ValueError("Paste or select a PNG, JPEG, WebP, or GIF image.")

        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("The pasted image data is invalid.") from exc
        if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("Each pasted image must be smaller than 5 MB.")

        try:
            with PILImage.open(BytesIO(image_bytes)) as source:
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Each pasted image must be no larger than 12 megapixels.")
                source.load()
                source.thumbnail(MAX_IMAGE_SIZE)
                has_alpha = "A" in source.getbands() or "transparency" in source.info
                normalized = source.convert("RGBA" if has_alpha else "RGB")
                output = BytesIO()
                normalized.save(output, format="PNG", optimize=True)
                return output.getvalue()
        except (UnidentifiedImageError, OSError, PILImage.DecompressionBombError) as exc:
            raise ValueError("The pasted image could not be decoded.") from exc

    @staticmethod
    def _read_images(sheet) -> Dict[str, Any]:
        images: Dict[str, Any] = {slot: None for slot in LEGAL_IMAGE_SLOTS}
        slot_by_anchor = {
            details["anchor"]: slot
            for slot, details in LEGAL_IMAGE_SLOTS.items()
        }
        for image in sheet._images:
            slot = slot_by_anchor.get(LegalChecklistService._anchor_cell(image))
            if not slot or images[slot]:
                continue
            image_format = (image.format or "png").lower()
            mime_type = "image/jpeg" if image_format in {"jpg", "jpeg"} else "image/png"
            payload = base64.b64encode(image._data()).decode("ascii")
            images[slot] = f"data:{mime_type};base64,{payload}"
        return images

    @staticmethod
    def _replace_images(sheet, images: Dict[str, Any]) -> None:
        slot_anchors = {
            details["anchor"]
            for details in LEGAL_IMAGE_SLOTS.values()
        }
        sheet._images = [
            image for image in sheet._images
            if LegalChecklistService._anchor_cell(image) not in slot_anchors
        ]
        for slot, details in LEGAL_IMAGE_SLOTS.items():
            data_url = images.get(slot)
            if not data_url:
                continue
            image = ExcelImage(BytesIO(LegalChecklistService._decode_image(data_url)))
            scale = min(
                details["max_width"] / image.width,
                170 / image.height,
            )
            image.width = round(image.width * scale)
            image.height = round(image.height * scale)
            image.anchor = details["anchor"]
            sheet.add_image(image)

    def read_checklist(self, workbook_path: str) -> Dict[str, Any]:
        if not os.path.isfile(workbook_path):
            raise FileNotFoundError(f"Legal checklist workbook not found: {workbook_path}")

        workbook = load_workbook(workbook_path, data_only=True)
        if LEGAL_SHEET_NAME not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f"Legal checklist workbook is missing the {LEGAL_SHEET_NAME} sheet")

        sheet = workbook[LEGAL_SHEET_NAME]
        items: List[Dict[str, Any]] = []
        category = ""
        for row in CHECKLIST_ROWS:
            row_category = sheet[f"B{row}"].value
            if row_category:
                category = str(row_category).strip()
            number = sheet[f"A{row}"].value
            if number is None:
                continue
            items.append({
                "row_index": row,
                "number": str(number).strip(),
                "category": category,
                "details": str(sheet[f"C{row}"].value or "").strip(),
                "method": str(sheet[f"G{row}"].value or "").strip(),
                "status": None if row == MRP_ROW else str(sheet[f"H{row}"].value or "").strip() or "OK",
                "remarks": str(sheet[f"J{row}"].value or "").strip() or "-",
                "is_mrp": row == MRP_ROW,
            })

        result = {
            "items": items,
            "mrp_value": str(sheet[f"H{MRP_ROW}"].value or "").strip(),
            "product": str(sheet["A2"].value or "").strip(),
            "lot_quantity": str(sheet["D2"].value or "").strip(),
            "sku": str(sheet["A3"].value or "").strip(),
            "decision": str(sheet["D3"].value or "").strip(),
            "images": self._read_images(sheet),
        }
        workbook.close()
        return result

    def save_review(
        self,
        workbook_path: str,
        items: List[Dict[str, Any]],
        mrp_value: str,
        images: Optional[Dict[str, Any]] = None,
    ) -> str:
        submitted = {item["row_index"]: item for item in items}
        expected_rows = set(CHECKLIST_ROWS)
        if len(items) != len(expected_rows) or set(submitted) != expected_rows:
            raise ValueError("Every J1 checklist row must be submitted exactly once.")
        if not mrp_value.strip():
            raise ValueError("Enter the model-specific MRP value before agreeing to the legal checklist.")
        for row in CHECKLIST_ROWS:
            if row != MRP_ROW and submitted[row].get("status") not in {"OK", "NG"}:
                raise ValueError(f"Choose OK or NG for J1 checklist item {submitted[row].get('number', row)}.")

        decision = "Reject" if any(
            submitted[row]["status"] == "NG"
            for row in CHECKLIST_ROWS
            if row != MRP_ROW
        ) else "Accept"

        workbook = load_workbook(workbook_path)
        sheet = workbook[LEGAL_SHEET_NAME]
        sheet[f"H{MRP_ROW}"] = mrp_value.strip()
        for row in CHECKLIST_ROWS:
            item = submitted[row]
            if row != MRP_ROW:
                sheet[f"H{row}"] = item["status"]
            sheet[f"J{row}"] = "-"
        sheet["D3"] = f"Lot Decision (Accept / Reject) : {decision}"
        if images is not None:
            self._replace_images(sheet, images)
        workbook.save(workbook_path)
        workbook.close()
        return decision

    def create_pdf(self, workbook_path: str, output_pdf_path: str) -> str:
        data = self.read_checklist(workbook_path)
        workbook = load_workbook(workbook_path)
        sheet = workbook[LEGAL_SHEET_NAME]
        document = SimpleDocTemplate(
            output_pdf_path,
            pagesize=landscape(A4),
            leftMargin=18,
            rightMargin=18,
            topMargin=18,
            bottomMargin=18,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "LegalTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=15,
            alignment=1,
        )
        body_style = ParagraphStyle("LegalBody", parent=styles["BodyText"], fontSize=7, leading=8)
        header_style = ParagraphStyle(
            "LegalHeader",
            parent=body_style,
            fontName="Helvetica-Bold",
            textColor=colors.white,
        )

        def paragraph(value: Any, style: ParagraphStyle = body_style) -> Paragraph:
            text = escape("" if value is None else str(value)).replace("\n", "<br/>")
            return Paragraph(text, style)

        elements = []
        logo = sheet._images[0] if sheet._images else None
        if logo:
            logo_image = Image(
                BytesIO(logo._data()),
                width=1.05 * inch,
                height=0.59 * inch,
            )
            title = paragraph("LEGAL COMPLIANCE CHECKSHEET", title_style)
            title_table = Table([[logo_image, title]], colWidths=[95, document.width - 95])
        else:
            title_table = Table([[paragraph("LEGAL COMPLIANCE CHECKSHEET", title_style)]])
        title_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(title_table)

        metadata = [
            [paragraph(sheet["F1"].value), paragraph(sheet["G1"].value),
             paragraph(sheet["I1"].value)],
            [paragraph(sheet["A2"].value), paragraph(sheet["D2"].value),
             paragraph(f"Inspected By : {sheet['H2'].value or ''}")],
            [paragraph(sheet["A3"].value), paragraph(sheet["D3"].value),
             paragraph(f"Approved By : {sheet['H3'].value or ''}")],
        ]
        metadata_table = Table(metadata, colWidths=[document.width * 0.45, document.width * 0.30, document.width * 0.25])
        metadata_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.extend([metadata_table, Spacer(1, 7)])

        table_data = [[
            paragraph("S.N", header_style),
            paragraph("Key Check Item", header_style),
            paragraph("Key Checkpoint Details", header_style),
            paragraph("Method", header_style),
            paragraph("OK / NG or MRP", header_style),
            paragraph("Remarks", header_style),
        ]]
        for item in data["items"]:
            value = data["mrp_value"] if item["is_mrp"] else item["status"] or ""
            table_data.append([
                paragraph(item["number"]),
                paragraph(item["category"]),
                paragraph(item["details"]),
                paragraph(item["method"]),
                paragraph(value),
                paragraph(item["remarks"]),
            ])

        checklist_table = Table(
            table_data,
            colWidths=[28, 104, 330, 68, 80, document.width - 610],
            repeatRows=1,
        )
        checklist_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(checklist_table)

        photo_headers = [
            "Carton with Label",
            "Product Name Plate / Labels/Engraving",
            "Technical Specs Details",
        ]
        photo_slots = list(LEGAL_IMAGE_SLOTS)
        photo_widths = [
            document.width * 0.30,
            document.width * 0.32,
            document.width * 0.38,
        ]
        photo_row = []
        for slot, width in zip(photo_slots, photo_widths):
            data_url = data["images"].get(slot)
            if data_url:
                image_bytes = self._decode_image(data_url)
                photo_row.append(Image(
                    BytesIO(image_bytes),
                    width=width - 10,
                    height=125,
                    kind="proportional",
                ))
            else:
                photo_row.append("")
        photo_table = Table(
            [
                [paragraph(title, header_style) for title in photo_headers],
                photo_row,
            ],
            colWidths=photo_widths,
            rowHeights=[24, 135],
            repeatRows=1,
        )
        photo_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 1), (-1, 1), "CENTER"),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.extend([Spacer(1, 8), photo_table])
        workbook.close()
        document.build(elements)
        return output_pdf_path
