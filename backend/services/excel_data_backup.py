import json
import logging
import os
import shutil
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event, RLock, Thread

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

try:
    from ..migrations.versions.v0002_excel_backup import TABLE_SHEETS
except ImportError:
    from migrations.versions.v0002_excel_backup import TABLE_SHEETS


logger = logging.getLogger(__name__)
FILENAME = "PDI Data.xlsx"
EXCEL_MAX_ROWS = 1_048_576
TEXT_CHUNK_SIZE = 15_000


class DataSheet:
    def __init__(self, workbook, title, headers):
        self.workbook = workbook
        self.title = title
        self.headers = headers
        self.page = 0
        self._new_sheet()

    def _new_sheet(self):
        self.page += 1
        suffix = f" {self.page}" if self.page > 1 else ""
        self.sheet = self.workbook.create_sheet(self.title[:31 - len(suffix)] + suffix)
        self.sheet.freeze_panes = "B2"
        header_row = []
        for index, header in enumerate(self.headers, 1):
            cell = WriteOnlyCell(self.sheet, value=header)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="234769")
            header_row.append(cell)
            self.sheet.column_dimensions[get_column_letter(index)].width = min(38, max(15, len(header) + 5))
        self.sheet.append(header_row)
        self.row = 1

    def append(self, values):
        if self.row == EXCEL_MAX_ROWS:
            self.finish()
            self._new_sheet()
        self.sheet.append([self._cell(value) for value in values])
        self.row += 1

    def _cell(self, value):
        if isinstance(value, int) and abs(value) >= 10**15:
            value = str(value)
        if isinstance(value, str):
            cell = WriteOnlyCell(self.sheet, value=value)
            cell.data_type = "s"
            return cell
        return value

    def finish(self):
        right = get_column_letter(len(self.headers))
        self.sheet.auto_filter.ref = f"A1:{right}{self.row}"
        self.sheet.close()


def write_workbook(conn, path):
    workbook = Workbook(write_only=True)
    contents = DataSheet(workbook, "Contents", ("Sheet", "Description"))
    contents.append(("Snapshot (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")))
    contents.append(("Scope", "PDI business records from SQLite. File columns reference attachments. The ZIP backup includes the actual files."))
    contents.append(("Privacy", "Employee accounts and integration URLs are excluded."))
    contents.append(("Long Values", "Join the parts in Part order by Table, Record ID and Column. Encoding identifies any escaped text."))
    long_values = DataSheet(workbook, "Long Values", ("Table", "Record ID", "Column", "Part", "Encoding", "Text"))
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, title in TABLE_SHEETS.items():
        if table not in existing:
            continue
        excluded = {"webhook_url"} if table == "email_jobs" else set()
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[1] not in excluded]
        headers = ", ".join('"' + name.replace('"', '""') + '"' for name in columns)
        records = conn.execute(f"SELECT {headers} FROM {table} ORDER BY id")
        sheet = DataSheet(workbook, title, columns)
        contents.append((title, table))
        for record in records:
            values = list(record)
            for index, value in enumerate(values):
                if not isinstance(value, str):
                    continue
                illegal_characters = ILLEGAL_CHARACTERS_RE.search(value)
                if not illegal_characters and len(value.encode("utf-16-le")) // 2 <= TEXT_CHUNK_SIZE:
                    continue
                encoding = "JSON string" if illegal_characters else "Text"
                if illegal_characters:
                    value = json.dumps(value, ensure_ascii=True)
                for part, offset in enumerate(range(0, len(value), TEXT_CHUNK_SIZE), 1):
                    text = value[offset:offset + TEXT_CHUNK_SIZE]
                    long_values.append((table, record[0], columns[index], part, encoding, text))
                values[index] = f"See Long Values · {table} / {record[0]} / {columns[index]}"
            sheet.append(values)
        sheet.finish()
    contents.finish()
    long_values.finish()
    workbook.save(path)


class ExcelDataBackup:
    def __init__(self, connect, path):
        self.connect = connect
        self.path = Path(path)
        self.lock = RLock()
        self._revision = None
        self._stop = Event()
        self._thread = Thread(target=self._run, name="pdi-excel-backup", daemon=True)

    def start(self):
        self._thread.start()

    def close(self):
        self._stop.set()
        self._thread.join()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception:
                logger.exception("Excel backup refresh failed")
            self._stop.wait(3)

    def refresh(self):
        with self.lock, closing(self.connect()) as conn:
            conn.execute("BEGIN")
            revision = conn.execute("SELECT revision FROM excel_backup_revision WHERE id = 1").fetchone()[0]
            if revision == self._revision and self.path.is_file():
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.path.parent, suffix=".xlsx", delete=False) as temp:
                temporary = Path(temp.name)
            try:
                write_workbook(conn, temporary)
                os.replace(temporary, self.path)
                self._revision = revision
            finally:
                temporary.unlink(missing_ok=True)

    def copy_latest(self, destination):
        with self.lock:
            self.refresh()
            shutil.copyfile(self.path, destination)
