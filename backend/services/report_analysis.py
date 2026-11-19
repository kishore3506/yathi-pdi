import re
from datetime import date, timedelta
from io import BytesIO
from typing import Dict, Iterable, List, Tuple
from xml.sax.saxutils import escape
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import openpyxl
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


MAX_REPORT_FILE_BYTES = 15 * 1024 * 1024
MAX_REPORT_TEXT_CHARS = 80_000
MAX_OFFICE_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_REPORT_PAGES = 100
MAX_REPORTS_PER_ANALYSIS = 20
SUPPORTED_REPORT_FORMATS = {"pdf", "docx", "both"}


def extract_report_text(file_content: bytes, filename: str) -> str:
    if len(file_content) > MAX_REPORT_FILE_BYTES:
        raise ValueError("The report file is too large. The maximum size is 15 MB.")

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "pdf":
        text = _extract_pdf_text(file_content)
    elif extension == "xlsx":
        _validate_office_archive(file_content)
        text = _extract_xlsx_text(file_content)
    elif extension == "docx":
        _validate_office_archive(file_content)
        text = _extract_docx_text(file_content)
    else:
        raise ValueError("Unsupported report file. Attach a searchable PDF, XLSX, or DOCX file.")

    if not text.strip():
        raise ValueError("No readable text was found. Scanned PDFs need a searchable text layer.")
    if len(text) > MAX_REPORT_TEXT_CHARS:
        raise ValueError("The report contains too much text to analyze at once. Please use a shorter report.")
    return text


def _validate_office_archive(file_content: bytes) -> None:
    try:
        with ZipFile(BytesIO(file_content)) as archive:
            members = archive.infolist()
    except BadZipFile as exc:
        raise ValueError("The Office document is invalid or damaged.") from exc

    if len(members) > 5000 or sum(member.file_size for member in members) > MAX_OFFICE_EXPANDED_BYTES:
        raise ValueError("The Office document exceeds the safe analysis limits.")


def _extract_pdf_text(file_content: bytes) -> str:
    reader = PdfReader(BytesIO(file_content))
    if reader.is_encrypted:
        raise ValueError("Password-protected PDFs cannot be analyzed.")
    if len(reader.pages) > MAX_REPORT_PAGES:
        raise ValueError(f"The PDF has more than {MAX_REPORT_PAGES} pages. Please split it before analysis.")

    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(f"--- Page {page_number} ---\n{page_text}")
    return "\n\n".join(pages)


def _extract_xlsx_text(file_content: bytes) -> str:
    try:
        workbook = openpyxl.load_workbook(BytesIO(file_content), data_only=True, read_only=True)
    except (
        BadZipFile,
        OSError,
        ValueError,
        openpyxl.utils.exceptions.InvalidFileException,
    ) as exc:
        raise ValueError("The Excel report could not be read. Use a valid XLSX workbook.") from exc

    sheets = []
    try:
        if len(workbook.worksheets) > 20:
            raise ValueError("The Excel workbook has more than 20 sheets. Please use a smaller workbook.")
        for sheet in workbook.worksheets[:20]:
            if (sheet.max_row or 1) > 2000 or (sheet.max_column or 1) > 40:
                raise ValueError(
                    f"Sheet '{sheet.title}' exceeds the 2,000-row or 40-column analysis limit."
                )
            rows = []
            for row in sheet.iter_rows(
                min_row=1,
                max_row=min(sheet.max_row or 1, 2000),
                max_col=min(sheet.max_column or 1, 40),
                values_only=True,
            ):
                values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                if values:
                    rows.append(" | ".join(values))
            if rows:
                sheets.append(f"--- Sheet: {sheet.title} ---\n" + "\n".join(rows))
    finally:
        workbook.close()
    return "\n\n".join(sheets)


def _extract_docx_text(file_content: bytes) -> str:
    try:
        document = Document(BytesIO(file_content))
    except (BadZipFile, OSError, PackageNotFoundError) as exc:
        raise ValueError("The Word report could not be read. Use a valid DOCX document.") from exc

    sections = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table_index, table in enumerate(document.tables, start=1):
        rows = []
        for row in table.rows:
            values = [cell.text.strip().replace("\n", " ") for cell in row.cells if cell.text.strip()]
            if values:
                rows.append(" | ".join(values))
        if rows:
            sections.append(f"--- Table {table_index} ---\n" + "\n".join(rows))
    return "\n\n".join(sections)


def select_existing_reports(
    request_text: str,
    reports: Iterable[Dict[str, object]],
) -> List[Dict[str, object]]:
    reports = list(reports)
    if not reports:
        raise LookupError("There are no generated reports available to analyze.")

    normalized_request = request_text.casefold()
    analyze_all = bool(re.search(r"\b(all|every|entire)\b", normalized_request))
    requested_dates = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", normalized_request))
    today = date.today()
    if re.search(r"\btoday\b", normalized_request):
        requested_dates.add(today.isoformat())
    if re.search(r"\byesterday\b", normalized_request):
        requested_dates.add((today - timedelta(days=1)).isoformat())

    searchable_fields = (
        "report_code",
        "company_name",
        "product_type",
        "model_name",
        "product_number",
        "po_number",
    )
    requested_terms = {
        str(report.get(field) or "").strip().casefold()
        for report in reports
        for field in searchable_fields
        if len(str(report.get(field) or "").strip()) >= 2
        and str(report.get(field) or "").strip().casefold() in normalized_request
    }

    if not analyze_all and not requested_terms and not requested_dates:
        raise ValueError(
            "Specify a report code, customer, model, SKU, PO number, or date; "
            "or ask to analyze all reports."
        )

    selected = []
    for report in reports:
        values = {
            str(report.get(field) or "").strip().casefold()
            for field in searchable_fields
        }
        term_match = not requested_terms or requested_terms.issubset(values)
        report_date = str(report.get("created_at") or "")[:10]
        date_match = not requested_dates or report_date in requested_dates
        if term_match and date_match:
            selected.append(report)

    if not selected:
        raise LookupError("No reports matched those details. Check the report code, customer, model, or date.")
    if len(selected) > MAX_REPORTS_PER_ANALYSIS:
        raise ValueError(
            f"{len(selected)} reports matched. Narrow the request to 20 reports or fewer "
            "by customer, model, report code, or date."
        )
    return selected


def render_report_analysis(analysis: str, source_name: str, output_format: str) -> Tuple[bytes, str, str]:
    output_format = output_format.lower()
    if output_format not in SUPPORTED_REPORT_FORMATS:
        raise ValueError("Choose PDF, DOCX, or both as the analysis download format.")

    if output_format == "pdf":
        return _render_pdf(analysis, source_name), "application/pdf", ".pdf"
    if output_format == "docx":
        return _render_docx(analysis, source_name), (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ), ".docx"

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("pdi_report_analysis.pdf", _render_pdf(analysis, source_name))
        archive.writestr("pdi_report_analysis.docx", _render_docx(analysis, source_name))
    return buffer.getvalue(), "application/zip", ".zip"


def _render_pdf(analysis: str, source_name: str) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="PDI Report Analysis",
        leftMargin=48,
        rightMargin=48,
        topMargin=48,
        bottomMargin=48,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("PDI Report Analysis", styles["Title"]),
        Paragraph(f"Source: {escape(_pdf_safe_text(source_name))}", styles["BodyText"]),
        Spacer(1, 14),
    ]
    for line in analysis.splitlines():
        if not line.strip():
            story.append(Spacer(1, 6))
        elif line.startswith("# "):
            story.append(Paragraph(escape(_pdf_safe_text(line[2:].strip())), styles["Heading1"]))
        elif line.startswith("## "):
            story.append(Paragraph(escape(_pdf_safe_text(line[3:].strip())), styles["Heading2"]))
        else:
            story.append(Paragraph(escape(_pdf_safe_text(line)), styles["BodyText"]))
    document.build(story)
    return buffer.getvalue()


def _pdf_safe_text(value: str) -> str:
    return value.encode("cp1252", errors="replace").decode("cp1252")


def _render_docx(analysis: str, source_name: str) -> bytes:
    document = Document()
    document.add_heading("PDI Report Analysis", level=0)
    document.add_paragraph(f"Source: {source_name}")

    for line in analysis.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            document.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            document.add_heading(stripped[2:], level=1)
        elif re.match(r"^[-*]\s+", stripped):
            document.add_paragraph(re.sub(r"^[-*]\s+", "", stripped), style="List Bullet")
        else:
            document.add_paragraph(stripped)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
