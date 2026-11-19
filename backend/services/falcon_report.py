from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas


SHEET_NAME = "Falcon PDI"
ORDER_SHEET = "Order Details"
TEMPLATE_NAME = "Falcon_PDI.xlsx"
PLACEHOLDER = "OK / NOT OK"
VERDICTS = {"OK", "NOT OK"}

# PDF coordinates are measured from the top-left of the original A4 page.
FORM_FIELDS = {
    "product_type": ("B6", "Products", 106, 102, 310),
    "power_rating": ("D6", "HP/KW", 359, 102, 474),
    "model_name": ("F6", "Model", 525, 102, 783),
    "serial_number": ("B7", "Serial number", 88, 114, 310),
    "incoming_date": ("D7", "Incoming date", 401, 114, 474),
    "supplier_name": ("F7", "Supplied by", 553, 114, 783),
    "lot_qty": ("B8", "Actual quantity", 118, 126, 310),
    "inspection_date": ("D8", "Date of report", 413, 126, 474),
    "invoice_number": ("F8", "Invoice number", 552, 126, 783),
    "prepared_by": ("B35", "Prepared by", 108, 449, 239),
    "inspected_by": ("D35", "Inspected by", 309, 449, 457),
    "approved_by": ("F35", "Approval by higher authority", 599, 449, 783),
}
ORDER_FIELDS = {
    "sku_no": ("B2", "SKU"),
    "po_number": ("B3", "PO number"),
    "po_total_qty": ("B4", "PO total quantity"),
    "lot_dispatch_date": ("B5", "Dispatch date"),
}
CHECKPOINT_Y = {
    11: 159.5, 14: 194, 15: 205.5, 16: 216.8, 17: 228.1, 18: 239.5,
    19: 251, 20: 262.2, 21: 273.7, 22: 284.9, 25: 321.9, 26: 333.2,
    27: 344.6, 28: 356, 29: 367.2, 30: 378.6, 31: 390, 32: 401.3,
}


def workbook_mappings():
    for key, (cell, label, *_position) in FORM_FIELDS.items():
        yield key, label, SHEET_NAME, cell
    for key, (cell, label) in ORDER_FIELDS.items():
        yield key, label, ORDER_SHEET, cell


def read_falcon_report(workbook):
    sheet = workbook[SHEET_NAME]
    header = {
        key: str(workbook[sheet_name][cell].value or "").strip()
        for key, _, sheet_name, cell in workbook_mappings()
    }
    header["title"] = sheet["A5"].value
    checkpoints = []
    for row in CHECKPOINT_Y:
        labels = [sheet[f"{column}{row}"].value for column in "AE"]
        remark = sheet[f"G{row}"].value
        checkpoints.append({
            "row_index": row,
            "parameter": " / ".join(label.removeprefix("▸ ") for label in labels if label),
            "observations": {"G": remark if remark in VERDICTS else ""},
            "is_multi_sample": False,
        })
    return {
        "sheet_names": workbook.sheetnames,
        "primary_sheet": SHEET_NAME,
        "header_data": header,
        "checkpoints": checkpoints,
        "footer_note": sheet["A34"].value,
    }


def write_falcon_pdf(report, output_path):
    source_path = Path(__file__).resolve().parents[1] / "templates" / "Falcon_PDI.pdf"
    writer = PdfWriter()
    page = writer.add_page(PdfReader(source_path).pages[0])
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    layer = BytesIO()
    canvas = Canvas(layer, pagesize=(width, height))

    def place_text(value, left, top, right):
        size = 8.0
        text = str(value).replace("\n", " ").replace("\r", " ")
        while size > 5 and stringWidth(text, "Helvetica", size) > right - left:
            size -= 0.5
        if stringWidth(text, "Helvetica", size) > right - left:
            text = text[: max(1, int(len(text) * (right - left) / stringWidth(text, "Helvetica", size)) - 3)] + "..."
        canvas.setFont("Helvetica", size)
        canvas.drawString(left, height - top, text)

    place_text("FALCON", 178, 42, 315)
    for key, (_, _, left, top, right) in FORM_FIELDS.items():
        value = report["header_data"].get(key)
        if value:
            place_text(value, left, top, right)

    for checkpoint in report["checkpoints"]:
        verdict = checkpoint["observations"]["G"]
        if verdict not in VERDICTS:
            continue
        y = height - CHECKPOINT_Y[checkpoint["row_index"]]
        canvas.setFillColorRGB(1, 1, 1)
        canvas.rect(724, y - 5, 64, 9.4, stroke=0, fill=1)
        canvas.setFillColorRGB(0, 0, 0)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawCentredString(756, y - 3, verdict)

    canvas.showPage()
    canvas.save()
    layer.seek(0)
    page.merge_page(PdfReader(layer).pages[0])
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=Path(output_path).parent, suffix=".pdf", delete=False) as output:
            temporary_path = Path(output.name)
            writer.write(output)
        temporary_path.replace(output_path)
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
