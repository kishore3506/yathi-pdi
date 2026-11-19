from io import BytesIO
from pathlib import Path
from posixpath import normpath
from zipfile import ZipFile

from lxml import etree
from openpyxl.utils.cell import coordinate_to_tuple


MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def write_cell_values(template_path, output_path, values_by_sheet):
    """Update worksheet values without rewriting the workbook's other parts."""
    output = BytesIO()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with ZipFile(template_path) as original, ZipFile(output, "w") as result:
        workbook = etree.fromstring(original.read("xl/workbook.xml"), parser)
        relationships = etree.fromstring(original.read("xl/_rels/workbook.xml.rels"), parser)
        targets = {rel.get("Id"): rel.get("Target") for rel in relationships}
        updates = {}
        for sheet in workbook.find(f"{MAIN}sheets"):
            values = values_by_sheet.get(sheet.get("name"))
            if values:
                target = targets[sheet.get(REL_ID)]
                path = target.lstrip("/") if target.startswith("/") else normpath(f"xl/{target}")
                updates[path] = values

        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename in updates:
                sheet = etree.fromstring(content, parser)
                _update_sheet(sheet, updates[entry.filename])
                content = etree.tostring(sheet, encoding="UTF-8", xml_declaration=True)
            result.writestr(entry, content)

    Path(output_path).write_bytes(output.getbuffer())


def _update_sheet(sheet, values):
    sheet_data = sheet.find(f"{MAIN}sheetData")
    rows = {int(row.get("r")): row for row in sheet_data}
    cells = {cell.get("r"): cell for row in rows.values() for cell in row if cell.tag == f"{MAIN}c"}

    for address, value in values.items():
        cell = cells.get(address)
        if cell is None:
            row_number, column = coordinate_to_tuple(address)
            row = rows.get(row_number)
            if row is None:
                row = etree.Element(f"{MAIN}row", r=str(row_number))
                following_row = next((item for item in sheet_data if int(item.get("r")) > row_number), None)
                if following_row is None:
                    sheet_data.append(row)
                else:
                    following_row.addprevious(row)
                rows[row_number] = row
            cell = etree.Element(f"{MAIN}c", r=address)
            following_cell = next(
                (item for item in row if item.tag == f"{MAIN}c" and coordinate_to_tuple(item.get("r"))[1] > column),
                None,
            )
            if following_cell is None:
                row.append(cell)
            else:
                following_cell.addprevious(cell)

        for child in list(cell):
            if child.tag in {f"{MAIN}v", f"{MAIN}is", f"{MAIN}f"}:
                cell.remove(child)
        cell.attrib.pop("t", None)
        if isinstance(value, str):
            cell.set("t", "inlineStr")
            inline = etree.Element(f"{MAIN}is")
            text = etree.SubElement(inline, f"{MAIN}t")
            text.text = value
            if value != value.strip():
                text.set(XML_SPACE, "preserve")
            cell.insert(0, inline)
        elif value is not None:
            number = etree.Element(f"{MAIN}v")
            number.text = str(value)
            cell.insert(0, number)
