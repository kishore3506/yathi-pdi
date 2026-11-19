import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from zipfile import ZipFile

from lxml import etree

try:
    from ..settings import DATA_DIR
except ImportError:
    from settings import DATA_DIR

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SHEET_NAME = "Surface Pump"
REPORT_RANGE = "'Surface Pump'!$A$1:$K$81"
_RENDER_LOCK = Lock()


def _trim_title_padding(content):
    root = etree.fromstring(content)
    for item in root.iter(f"{MAIN}t"):
        if item.text and item.text.startswith("Pump - Pre-dispatch Inspection Report"):
            item.text = item.text.rstrip()
            return etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    return content


def _print_copy(source, destination):
    # Restrict printing to the PDI form. Preserve the worksheet XML and its drawing,
    # styles, values, page scaling, margins, and printer configuration.
    with ZipFile(source) as original, ZipFile(destination, "w") as copy:
        workbook = etree.fromstring(original.read("xl/workbook.xml"))
        sheets = workbook.find(f"{MAIN}sheets")
        index = next((index for index, sheet in enumerate(sheets) if sheet.get("name") == SHEET_NAME), None)
        if index is None:
            raise ValueError("The Havells Surface Pump worksheet is missing.")
        for position, sheet in enumerate(sheets):
            sheet.set("state", "visible" if position == index else "hidden")
        for view in workbook.findall(f"{MAIN}bookViews/{MAIN}workbookView"):
            view.set("activeTab", str(index))
            view.set("firstSheet", str(index))
        names = workbook.find(f"{MAIN}definedNames")
        if names is None:
            names = etree.Element(f"{MAIN}definedNames")
            sheets.addnext(names)
        areas = [name for name in names if name.get("name") == "_xlnm.Print_Area"]
        for area in areas:
            if area.get("localSheetId") != str(index):
                names.remove(area)
        if not any(name.get("localSheetId") == str(index) for name in areas):
            etree.SubElement(names, f"{MAIN}definedName", name="_xlnm.Print_Area", localSheetId=str(index)).text = REPORT_RANGE
        for entry in original.infolist():
            if entry.filename == "xl/workbook.xml":
                content = etree.tostring(workbook, encoding="UTF-8", xml_declaration=True)
            else:
                content = original.read(entry)
                if entry.filename == "xl/sharedStrings.xml" or entry.filename.startswith("xl/worksheets/sheet"):
                    content = _trim_title_padding(content)
            copy.writestr(entry, content)


def write_havells_pdf(workbook, output_pdf):
    executable = os.getenv("PDI_HAVELLS_SOFFICE") or shutil.which("soffice")
    if not executable and os.name == "nt":
        installed = Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "LibreOffice/program/soffice.com"
        executable = str(installed) if installed.is_file() else None
    if not executable:
        raise NotImplementedError("Install or configure LibreOffice on the server to export the Havells template as PDF.")
    output = Path(output_pdf)
    profile = (DATA_DIR / "havells-pdf-profile").as_uri()
    with TemporaryDirectory(prefix="havells-export-", dir=output.parent) as folder:
        root = Path(folder).resolve()
        source = root / "Havells.xlsx"
        _print_copy(workbook, source)
        try:
            with _RENDER_LOCK:
                subprocess.run([
                    executable, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                    "--convert-to", "pdf:calc_pdf_Export", "--outdir", str(root), str(source),
                ], check=True, timeout=60, capture_output=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError("The Havells workbook could not be printed to PDF.") from error
        result = source.with_suffix(".pdf")
        if not result.is_file() or not result.stat().st_size:
            raise RuntimeError("The Havells workbook did not produce a PDF.")
        result.replace(output)
