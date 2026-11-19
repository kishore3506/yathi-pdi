from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from .havells_pdf import render_workbook_pdf
from .xlsx_cell_values import MAIN, write_cell_values


LEGACY_TEMPLATE_NAME = "6) MBD - R4.pdf"
TEMPLATE_NAME = "6) MBD - R4.xlsx"
SHEET_NAME = "Crompton MBD R4"
NATIVE_SHEETS = ("Table 1", "Table 2")
TITLE = "Finished Good - Pre Dispatch Inspection (PDI) Report"
SERIAL_ROW = 16
COLUMNS = tuple("GHIJKLMNOP")
DECISIONS = ("Direct Pass", "Rejected", "Passed after Rework", "Passed under deviation without rework")

# Coordinates in the rendered source page (1310 x 927), measured from the top left.
# Fields are (key, label, page, left, top, right, bottom).
FIELDS = (
    ("supplier_name", "Name of the unit", 0, 293, 84, 926, 116),
    ("supplier_location", "Address of the unit", 0, 293, 117, 926, 150),
    ("lot_qty", "Lot size", 0, 684, 150, 1284, 194),
    ("model_name", "Model / type", 0, 168, 195, 542, 225),
    ("tds_reference", "TDS/TI reference number", 0, 684, 195, 1284, 225),
    ("product_reference", "Product reference", 0, 168, 226, 542, 312),
    ("batch_code", "Batch code / CCI reference", 0, 684, 226, 1284, 312),
    ("inspection_date", "Date of inspection", 0, 168, 313, 542, 344),
    ("vendor_report_number", "Vendor PDI report number", 0, 684, 313, 1284, 344),
    ("additional_info", "Additional information", 0, 168, 345, 542, 371),
    ("note", "Note", 1, 26, 454, 1283, 728),
    ("inspected_by", "Tested by", 1, 201, 760, 542, 797),
    ("approved_by", "Approved by", 1, 201, 798, 542, 835),
    ("deviation_number", "Deviation note number", 1, 1109, 835, 1283, 869),
    ("deviation_authority", "Deviation approval authority", 1, 1109, 869, 1283, 884),
)
ORDER_FIELDS = (("sku_no", "SKU"), ("po_number", "PO number"), ("final_judgment", "Decision on the lot"))
HEADER_FIELDS = tuple((field[0], field[1]) for field in FIELDS) + ORDER_FIELDS

# Page, vertical bounds, inspection description, specification, and parameter type.
CHECKS = (
    (0, 483, 521, "Electrical connections, loose wires and cable damage", "", "Attribute"),
    (0, 521, 561, "Body short / earth (insulation resistance)", "5 MΩ minimum", "Variable"),
    (0, 561, 619, "Nameplate, Crompton logo and label period for star-rated models", "As per validation report", "Attribute"),
    (0, 619, 693, "MRP label, warranty card, serial match and applicable stickers", "As per approved copy", "Attribute"),
    (0, 693, 744, "Abnormal noise during running test", "", "Attribute"),
    (0, 744, 794, "Casting defects and cable damage", "", "Attribute"),
    (0, 794, 858, "Paint shade, water marks, cleanliness, rust and flange thread size", "", "Attribute"),
    (1, 23, 57, "Rubber flap / gasket damage", "", "Attribute"),
    (1, 57, 98, "Terminal box cover / grommet fitment", "", "Attribute"),
    (1, 98, 136, "Fan cover fitment", "", "Attribute"),
    (1, 136, 182, "Motor dummy cap and plastic components", "", "Attribute"),
    (1, 182, 240, "Packing box condition, colour, photo and artwork", "", "Attribute"),
    (1, 240, 278, "Discharge at rated voltage", "LPM", "Variable"),
    (1, 278, 315, "Pressure / head at delivery end at rated voltage", "MTR", "Variable"),
    (1, 315, 354, "Leakage at shut-off condition", "No leakages", "Attribute"),
    (1, 354, 392, "Temperature rise test at higher / lower voltage for 2 hours", "Deg.C", "Variable"),
)
CHECK_ROWS = range(SERIAL_ROW + 1, SERIAL_ROW + 1 + len(CHECKS))
SAMPLE_EDGES = (623, 684, 744, 805, 865, 926, 987, 1047, 1108, 1169, 1229, 1284)
NATIVE_FIELDS = {
    "supplier_name": ("Table 1", "D2"), "supplier_location": ("Table 1", "D3"),
    "lot_qty": ("Table 1", "J5"), "model_name": ("Table 1", "C6"),
    "tds_reference": ("Table 1", "J6"), "product_reference": ("Table 1", "C7"),
    "batch_code": ("Table 1", "J7"), "inspection_date": ("Table 1", "C8"),
    "vendor_report_number": ("Table 1", "J8"), "additional_info": ("Table 1", "C9"),
    "note": ("Table 2", "A10"), "inspected_by": ("Table 2", "C12"),
    "approved_by": ("Table 2", "C13"), "deviation_number": ("Table 2", "Q14"),
    "deviation_authority": ("Table 2", "Q15"),
}
NATIVE_DECISIONS = dict(zip(DECISIONS, ("C15", "D15", "G15", "J15")))
NATIVE_COLUMNS = dict(zip((*COLUMNS, "U"), "IJKLMNOPQRS"))
NATIVE_ROWS = dict(zip(CHECK_ROWS, [("Table 1", row) for row in range(13, 20)] +
                       [("Table 2", row) for row in range(1, 10)]))


def _text(value):
    return "" if value is None else str(value)


def write_native_workbook(source, destination, data, observations=None):
    updates = {sheet: {} for sheet in NATIVE_SHEETS}
    workbook = load_workbook(source)
    try:
        for field, (sheet, address) in NATIVE_FIELDS.items():
            if data.get(field) is None:
                continue
            value = data[field]
            if field == "note":
                original = _text(workbook[sheet][address].value)
                prefix = original.partition("Note:")[0] + "Note:"
                value = f"{prefix} {value}" if value else prefix
            elif field in {"inspected_by", "approved_by"}:
                value = f"Name : {value}" if value else "Name :"
            elif field == "lot_qty" and str(value).isdecimal():
                value = int(value)
            elif field != "lot_qty":
                value = _text(value)
            if value != workbook[sheet][address].value:
                updates[sheet][address] = value
        decision = data.get("final_judgment")
        if decision in (*DECISIONS, ""):
            for label, address in NATIVE_DECISIONS.items():
                updates["Table 2"][address] = "✓" if decision == label else None
        for column, serial in zip(COLUMNS, data.get("serial_numbers") or ()):
            updates["Table 1"][f"{NATIVE_COLUMNS[column]}12"] = _text(serial)
        for row, (sheet, native_row) in {SERIAL_ROW: ("Table 1", 12), **NATIVE_ROWS}.items():
            readings = (observations or {}).get(str(row))
            if not isinstance(readings, dict):
                continue
            for column in COLUMNS if row == SERIAL_ROW else (*COLUMNS, "U"):
                if column not in readings:
                    continue
                address = f"{NATIVE_COLUMNS[column]}{native_row}"
                value = _text(readings[column])
                if value != _text(workbook[sheet][address].value).strip():
                    updates[sheet][address] = value or None
    finally:
        workbook.close()
    write_cell_values(source, destination, updates)


def read_native_report(workbook):
    def reading(sheet, address):
        return _text(workbook[sheet][address].value).strip()

    header = {key: reading(sheet, address) for key, (sheet, address) in NATIVE_FIELDS.items()}
    header["note"] = header["note"].partition("Note:")[2].strip()
    for field in ("inspected_by", "approved_by"):
        header[field] = header[field].removeprefix("Name :").strip()
    header["final_judgment"] = next(
        (label for label, cell in NATIVE_DECISIONS.items() if reading("Table 2", cell) == "✓"), ""
    )
    return {
        "primary_sheet": SHEET_NAME,
        "sheet_names": workbook.sheetnames,
        "header_data": {"title": TITLE, **header},
        "sample_columns": list(COLUMNS),
        "sample_serials": {column: reading("Table 1", f"{NATIVE_COLUMNS[column]}12") for column in COLUMNS},
        "checkpoints": [
            {
                "row_index": row, "item_sn": str(index), "parameter": label,
                "specification": specification, "method": method,
                "observations": {
                    column: reading(sheet, f"{native_column}{native_row}")
                    for column, native_column in NATIVE_COLUMNS.items()
                },
            }
            for index, ((row, (sheet, native_row)), (_, _, _, label, specification, method))
            in enumerate(zip(NATIVE_ROWS.items(), CHECKS), 1)
        ],
    }


def _print_copy(source, destination):
    # Add landscape print settings to a temporary copy of the two native sheets.
    with ZipFile(source) as original, ZipFile(destination, "w") as output:
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename in {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"}:
                sheet = etree.fromstring(content)
                properties = sheet.find(f"{MAIN}sheetPr")
                if properties is None:
                    properties = etree.Element(f"{MAIN}sheetPr")
                    sheet.insert(0, properties)
                setup = properties.find(f"{MAIN}pageSetUpPr")
                if setup is None:
                    setup = etree.SubElement(properties, f"{MAIN}pageSetUpPr")
                setup.set("fitToPage", "1")
                page = sheet.find(f"{MAIN}pageSetup")
                if page is None:
                    page = etree.Element(f"{MAIN}pageSetup")
                    sheet.find(f"{MAIN}pageMargins").addnext(page)
                for key, value in (("paperSize", "9"), ("orientation", "landscape"),
                                   ("fitToWidth", "1"), ("fitToHeight", "1")):
                    page.set(key, value)
                content = etree.tostring(sheet, encoding="UTF-8", xml_declaration=True)
            output.writestr(entry, content)


def write_native_pdf(workbook, output_pdf):
    render_workbook_pdf(workbook, output_pdf, _print_copy, "Crompton")


def _put(cell, value):
    cell.value = str(value) if value is not None and value != "" else None
    if cell.value is not None:
        cell.data_type = "s"


def write_workbook(workbook, output_path, data, observations=None):
    if workbook is None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = SHEET_NAME
        sheet["A1"] = TITLE
        sheet.column_dimensions["A"].width = 30
        sheet.column_dimensions["B"].width = 58
        for index, (_, label) in enumerate(HEADER_FIELDS, 2):
            sheet.cell(index, 1, label)
        for index, column in enumerate(COLUMNS, 1):
            sheet[f"{column}15"] = f"Unit {index}"
        sheet["U15"] = "Remarks"
        sheet["B16"] = "Serial number"
        for row, (_, _, _, label, specification, method) in zip(CHECK_ROWS, CHECKS):
            sheet.cell(row, 2, label)
            sheet.cell(row, 3, specification)
            sheet.cell(row, 4, method)

    sheet = workbook[SHEET_NAME]
    for index, (key, _) in enumerate(HEADER_FIELDS, 2):
        if data.get(key) is not None:
            value = data[key]
            if key != "final_judgment" or value in (*DECISIONS, ""):
                _put(sheet.cell(index, 5), value)
    for column, serial in zip(COLUMNS, data.get("serial_numbers") or ()):
        _put(sheet[f"{column}{SERIAL_ROW}"], serial)
    for row in (SERIAL_ROW, *CHECK_ROWS):
        readings = (observations or {}).get(str(row))
        if isinstance(readings, dict):
            for column in COLUMNS if row == SERIAL_ROW else (*COLUMNS, "U"):
                if column in readings:
                    _put(sheet[f"{column}{row}"], readings[column])
    try:
        workbook.save(output_path)
    finally:
        workbook.close()


def read_report(workbook):
    sheet = workbook[SHEET_NAME]

    def reading(row, column):
        return str(sheet[f"{column}{row}"].value or "")

    header = {key: reading(index, "E") for index, (key, _) in enumerate(HEADER_FIELDS, 2)}
    return {
        "primary_sheet": SHEET_NAME,
        "sheet_names": workbook.sheetnames,
        "header_data": {"title": TITLE, **header},
        "sample_columns": list(COLUMNS),
        "sample_serials": {column: reading(SERIAL_ROW, column) for column in COLUMNS},
        "checkpoints": [
            {
                "row_index": row,
                "item_sn": str(index),
                "parameter": label,
                "specification": specification,
                "method": method,
                "observations": {column: reading(row, column) for column in (*COLUMNS, "U")},
            }
            for index, (row, (_, _, _, label, specification, method)) in enumerate(zip(CHECK_ROWS, CHECKS), 1)
        ],
    }


def write_pdf(report, output_path):
    source = Path(__file__).resolve().parents[1] / "templates" / LEGACY_TEMPLATE_NAME
    writer = PdfWriter(clone_from=source)
    header = report["header_data"]
    for page_index, page in enumerate(writer.pages):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        scale_x, scale_y = width / 1310, height / 927
        layer = BytesIO()
        canvas = Canvas(layer, pagesize=(width, height))
        canvas.scale(scale_x, scale_y)

        def place(value, left, top, right, bottom, *, centered=False, wrap=False):
            text = str(value or "").strip()
            if not text:
                return
            size = 10 if centered else 12
            max_width = right - left - 6
            if wrap:
                lines = [
                    _fit_text(line, size, max_width)
                    for paragraph in text.splitlines()
                    for line in simpleSplit(paragraph, "Helvetica", size, max_width) or [""]
                ]
                baseline = top + size
            else:
                text = " ".join(text.split())
                while size > 8 and stringWidth(text, "Helvetica", size) > max_width:
                    size -= 1
                lines = [_fit_text(text, size, max_width)]
                baseline = (top + bottom + size * 0.7) / 2
            canvas.setFont("Helvetica", size)
            for line in lines[: max(1, int((bottom - top) / (size + 2)))]:
                y = 927 - baseline
                if centered:
                    canvas.drawCentredString((left + right) / 2, y, line)
                else:
                    canvas.drawString(left + 3, y, line)
                baseline += size + 2

        for field, _, index, left, top, right, bottom in FIELDS:
            if index == page_index:
                place(header.get(field), left, top, right, bottom, wrap=field == "note")

        def samples(values, top, bottom, columns):
            for index, column in enumerate(columns):
                place(values.get(column), SAMPLE_EDGES[index], top, SAMPLE_EDGES[index + 1], bottom, centered=True)

        if page_index == 0:
            samples(report["sample_serials"], 442, 483, COLUMNS)
        for check, (index, top, bottom, *_labels) in zip(report["checkpoints"], CHECKS):
            if page_index == index:
                samples(check["observations"], top, bottom, (*COLUMNS, "U"))

        decision = header.get("final_judgment")
        if page_index == 1 and decision in DECISIONS:
            x = (229, 417, 613, 774)[DECISIONS.index(decision)]
            y = 927 - 885
            canvas.setLineWidth(1.6)
            canvas.lines([(x - 5, y, x - 1, y - 4), (x - 1, y - 4, x + 6, y + 5)])
        canvas.showPage()
        canvas.save()
        layer.seek(0)
        page.merge_page(PdfReader(layer).pages[0])

    temporary_path = None
    try:
        with NamedTemporaryFile(dir=Path(output_path).parent, suffix=".pdf", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            writer.write(temporary)
        temporary_path.replace(output_path)
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def _fit_text(text, size, width):
    if stringWidth(text, "Helvetica", size) <= width:
        return text
    while text and stringWidth(text + "...", "Helvetica", size) > width:
        text = text[:-1]
    return text.rstrip() + "..."
