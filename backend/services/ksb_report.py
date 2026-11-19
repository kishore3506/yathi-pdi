from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


TEMPLATE_NAME = "KSB -PDI Report Format.xlsx"
SHEET_NAME = "KSB PDI FORMAT"
SAMPLE_COLUMNS = tuple("GHIJKLMNOPQRST")
CHECKPOINT_ROWS = range(17, 39)
HEADER_FIELDS = {
    "supplier_name": ("D3", "Manufacturer name"),
    "supplier_location": ("D4", "Location"),
    "product_type": ("D5", "Product category"),
    "model_name": ("D6", "Model / type"),
    "inspection_date": ("L3", "Date of inspection"),
    "lot_dispatch_date": ("L4", "Date of dispatch"),
    "lot_qty": ("L5", "Lot size"),
    "inspected_by": ("B44", "Inspected by"),
    "approved_by": ("K44", "Approved by"),
    "special_remarks": ("B39", "Remark"),
}


def _text(value):
    return "" if value is None else str(value).strip()


def fill_ksb_sheet(sheet, data, observations, serial_number):
    values = {**data, "lot_qty": data.get("lot_size")}
    for field, (address, label) in HEADER_FIELDS.items():
        if field not in values or values[field] is None:
            continue
        value = _text(values[field])
        if field in {"inspected_by", "approved_by", "special_remarks"}:
            heading = "Remark : -" if field == "special_remarks" else label.upper()
            value = f"{heading}\n{value}" if value else heading
        if field == "lot_qty" and value.isdecimal():
            sheet[address] = int(value)
        else:
            sheet[address] = value or None
            if value:
                sheet[address].data_type = "s"

    if serial_number:
        sheet["G16"] = serial_number
        sheet["G16"].data_type = "s"
    decision = data.get("final_judgment")
    if decision is not None:
        decision = _text(decision).upper()
        sheet["D43"] = "✔" if decision in {"OK", "PASS", "ACCEPT"} else None
        sheet["E43"] = "✔" if decision == "REJECT" else None

    for row in (16, *CHECKPOINT_ROWS):
        readings = (observations or {}).get(str(row))
        if not isinstance(readings, dict):
            continue
        columns = SAMPLE_COLUMNS if row == 16 else (*SAMPLE_COLUMNS, "U")
        for column in columns:
            if column not in readings:
                continue
            cell = sheet[f"{column}{row}"]
            cell.value = _text(readings[column]) or None
            if cell.value:
                cell.data_type = "s"


def read_ksb_report(workbook):
    sheet = workbook[SHEET_NAME]
    header = {key: _text(sheet[address].value) for key, (address, _) in HEADER_FIELDS.items()}
    for key, prefix in (("inspected_by", "INSPECTED BY"), ("approved_by", "APPROVED BY"), ("special_remarks", "Remark : -")):
        header[key] = header[key].removeprefix(prefix).strip()
    header.update(
        title=sheet["D1"].value,
        judgment_ok=_text(sheet["D43"].value),
        judgment_reject=_text(sheet["E43"].value),
    )
    return {
        "primary_sheet": SHEET_NAME,
        "sheet_names": workbook.sheetnames,
        "header_data": header,
        "sample_columns": list(SAMPLE_COLUMNS),
        "sample_serials": {column: _text(sheet[f"{column}16"].value) for column in SAMPLE_COLUMNS},
        "checkpoints": [
            {
                "row_index": row, "item_sn": _text(sheet[f"B{row}"].value),
                "parameter": _text(sheet[f"C{row}"].value),
                "specification": _text(sheet[f"E{row}"].value),
                "method": _text(sheet[f"F{row}"].value),
                "observations": {column: _text(sheet[f"{column}{row}"].value) for column in (*SAMPLE_COLUMNS, "U")},
            }
            for row in CHECKPOINT_ROWS
        ],
    }


def write_ksb_pdf(data, path):
    document = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=18, rightMargin=18)
    normal = ParagraphStyle("KsbBody", fontName="Helvetica", fontSize=7, leading=8.5, splitLongWords=True)
    title = ParagraphStyle("KsbTitle", parent=normal, fontName="Helvetica-Bold", fontSize=12, leading=14)

    def paragraph(value, style=normal):
        return Paragraph(escape(_text(value)).replace("\n", "<br/>"), style)

    header = data["header_data"]
    columns = data["sample_columns"]
    serials = data["sample_serials"]
    decision = "Reject" if header["judgment_reject"] else "Accept" if header["judgment_ok"] else ""
    rows = [["S.N.", "Parameter description", "Specification", "Inspection method", *[
        paragraph(serials[column] or f"Sample {index}") for index, column in enumerate(columns, 1)
    ], "Remarks"]]
    for check in data["checkpoints"]:
        rows.append([paragraph(check[key]) for key in ("item_sn", "parameter", "specification", "method")] + [
            paragraph(check["observations"][column]) for column in (*columns, "U")
        ])
    table = Table(rows, colWidths=[26, 140, 100, 63, *([30] * len(columns)), 46], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    details = [paragraph(f"{label}: {header.get(key, '')}") for key, (_, label) in HEADER_FIELDS.items() if header.get(key)]
    document.build([
        paragraph(f"KSB | {header['title']}", title), Spacer(1, 6),
        *details, Spacer(1, 6), table, Spacer(1, 6), paragraph(f"Decision on the lot: {decision}"),
    ])
