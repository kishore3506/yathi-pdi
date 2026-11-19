from dataclasses import dataclass
from io import BytesIO

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Emu, Mm, Pt
from PIL import Image, ImageOps, UnidentifiedImageError


TEMPLATE_NAME = "STG_PDI.docx"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_PHOTO_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class PhotoSlot:
    key: str
    label: str
    table: int
    row: int
    column: int
    row_span: int = 1


PHOTO_GROUPS = (
    ("Product photos", tuple(
        PhotoSlot(f"product-{index + 1}", f"Product Pic {index + 1}", 1, 4 + 2 * (index // 3), index % 3)
        for index in range(6)
    )),
    ("Sticker / label photos", tuple(
        PhotoSlot(f"label-{index + 1}", f"Sticker / Label Pic {index + 1}", 1, 9 + 2 * (index // 3), index % 3)
        for index in range(6)
    )),
    ("Inner box photos", (
        PhotoSlot("box-1", "Box / Cover Pic 1", 1, 14, 0),
        PhotoSlot("box-2", "Box / Cover Pic 2", 1, 14, 1),
        PhotoSlot("box-3", "Box / Cover Pic 3", 1, 14, 2),
        PhotoSlot("box-6", "Box / Cover Pic 6 – English description", 1, 16, 0, 5),
        PhotoSlot("box-5", "Box / Cover Pic 5 – Arabic description", 1, 16, 1, 5),
    )),
    ("Outer carton photos", (
        PhotoSlot("carton-1", "Carton Pic 1 – Brand", 1, 23, 0),
        PhotoSlot("carton-2", "Carton Pic 2", 1, 23, 1),
        PhotoSlot("carton-3", "Carton Pic 3", 1, 23, 2),
        PhotoSlot("carton-4", "Carton Pic 4 – English description", 1, 25, 0, 5),
        PhotoSlot("carton-5", "Carton Pic 5 – Arabic description", 1, 25, 1, 5),
    )),
    *(
        (f"Dimensional measurement photos – Size {size}", tuple(
            PhotoSlot(
                f"size-{size}-{key}", label, 2 + (size - 1) // 2,
                3 + 5 * ((size - 1) % 2) + 2 * (index // 3), index % 3,
            )
            for index, (key, label) in enumerate((
                ("length", "Length"), ("width", "Width"), ("height", "Height"),
                ("spec-1", "Other Specification 1"), ("spec-2", "Other Specification 2"),
                ("weight", "Weight"),
            ))
        )) for size in range(1, 5)
    ),
)
PHOTO_SLOTS = {slot.key: slot for _, slots in PHOTO_GROUPS for slot in slots}
REPORT_FIELDS = {
    "po_number": (0, 0, 1),
    "pod": (0, 0, 3),
    "pi_number": (0, 1, 1),
    "batch_number": (0, 1, 3),
    "inspection_date": (0, 3, 1),
    "model_name": (1, 1, 1),
}


def normalize_photo(content):
    """Decode a supported image, apply orientation, and store a bounded JPEG without EXIF."""
    try:
        with Image.open(BytesIO(content), formats=("JPEG", "PNG", "WEBP")) as source:
            if source.width * source.height > 30_000_000:
                raise ValueError("Choose a photo no larger than 30 megapixels.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            buffer = BytesIO()
            background.save(buffer, "JPEG", quality=88, optimize=True)
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Choose a readable JPEG, PNG, or WebP photo.") from exc


def _set_cell_text(cell, value):
    runs = [run for paragraph in cell.paragraphs for run in paragraph.runs]
    text_runs = [run for run in runs if run.text]
    if text_runs:
        text_runs[0].text = value
        for run in text_runs[1:]:
            run.text = ""
    elif runs:
        runs[0].text = value
    elif value:
        cell.paragraphs[0].add_run(value)


def _slot_cell(document, slot):
    return document.tables[slot.table].cell(slot.row, slot.column)


def _update_photo(document, key, photo):
    slot = PHOTO_SLOTS[key]
    cell = _slot_cell(document, slot)
    relationships = [blip.get(qn("r:embed")) for blip in cell._tc.xpath(".//a:blip")]
    for paragraph in cell.paragraphs:
        paragraph._element.getparent().remove(paragraph._element)
    used_images = {blip.get(qn("r:embed")) for blip in document._element.xpath(".//a:blip")}
    for relationship in set(relationships):
        if relationship and relationship not in used_images:
            document.part.drop_rel(relationship)
    paragraph = cell.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if photo is None:
        return

    table = document.tables[slot.table]
    height = sum(table.rows[index].height for index in range(slot.row, slot.row + slot.row_span))
    with Image.open(BytesIO(photo)) as image:
        scale = min((cell.width - Mm(5)) / image.width, (height - Mm(8)) / image.height)
        shape = paragraph.add_run().add_picture(
            BytesIO(photo), width=Emu(int(image.width * scale)), height=Emu(int(image.height * scale))
        )
    shape._inline.docPr.set("descr", slot.label)


def read_photo(path, key):
    document = Document(path)
    blips = _slot_cell(document, PHOTO_SLOTS[key])._tc.xpath(".//a:blip")
    if not blips:
        return None
    return document.part.related_parts[blips[0].get(qn("r:embed"))].blob


def write_report(source_path, output_path, values, *, photo_change=None):
    document = Document(source_path)
    for key, (table, row, column) in REPORT_FIELDS.items():
        if key in values and values[key] is not None:
            _set_cell_text(document.tables[table].cell(row, column), str(values[key])[:180])
    if photo_change is not None:
        _update_photo(document, *photo_change)
    document.save(output_path)
    return {
        "format": "docx",
        "header_data": {
            key: document.tables[table].cell(row, column).text.strip()
            for key, (table, row, column) in REPORT_FIELDS.items()
        },
        "photo_groups": [
            {
                "label": group,
                "slots": [
                    {
                        "key": slot.key,
                        "label": slot.label,
                        "has_photo": bool(_slot_cell(document, slot)._tc.xpath(".//a:blip")),
                    } for slot in slots
                ],
            } for group, slots in PHOTO_GROUPS
        ],
    }
