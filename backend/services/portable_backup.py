import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .. import database
    from ..migrations import run_migrations
    from ..settings import CUSTOM_TEMPLATES_DIR, REPORTS_DIR, UPLOAD_DIR
    from .falcon_report import TEMPLATE_NAME as FALCON_TEMPLATE_NAME
    from .stg_report import TEMPLATE_NAME as STG_TEMPLATE_NAME
    from .ksb_report import TEMPLATE_NAME as KSB_TEMPLATE_NAME
    from .crompton_report import TEMPLATE_NAME as CROMPTON_TEMPLATE_NAME
    from .crompton_report import LEGACY_TEMPLATE_NAME as CROMPTON_LEGACY_TEMPLATE_NAME
except ImportError:
    import database
    from migrations import run_migrations
    from settings import CUSTOM_TEMPLATES_DIR, REPORTS_DIR, UPLOAD_DIR
    from services.falcon_report import TEMPLATE_NAME as FALCON_TEMPLATE_NAME
    from services.stg_report import TEMPLATE_NAME as STG_TEMPLATE_NAME
    from services.ksb_report import TEMPLATE_NAME as KSB_TEMPLATE_NAME
    from services.crompton_report import TEMPLATE_NAME as CROMPTON_TEMPLATE_NAME
    from services.crompton_report import LEGACY_TEMPLATE_NAME as CROMPTON_LEGACY_TEMPLATE_NAME


_FILE_REFERENCES = (
    ("uploaded_requirements", "id", "file_path", "uploads"),
    ("pdi_templates", "id", "file_path", "templates"),
    ("generated_reports", "id", "excel_path", "reports"),
    ("generated_reports", "id", "pdf_path", "reports"),
    ("report_jobs", "id", "legal_excel_path", "reports"),
    ("report_jobs", "id", "legal_pdf_path", "reports"),
)

_STORAGE_BY_CATEGORY = {
    "uploads": UPLOAD_DIR,
    "templates": CUSTOM_TEMPLATES_DIR,
    "reports": REPORTS_DIR,
}

_BUSINESS_TABLES = (
    "products",
    "customers",
    "uploaded_requirements",
    "extracted_product_details",
    "report_jobs",
    "generated_reports",
    "print_jobs",
    "email_jobs",
    "audit_logs",
)


def _ensure_initial_import_target(conn):
    existing_records = sum(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _BUSINESS_TABLES
    )
    if existing_records:
        raise ValueError(
            "Import is allowed only before business records exist. "
            "No current records were changed."
        )

    surface_pump_templates = set(database.SURFACE_PUMP_TEMPLATES.values())
    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    templates = conn.execute(
        "SELECT template_name, file_path FROM pdi_templates"
    ).fetchall()
    registered_names = {row["template_name"] for row in templates}
    template_storage = CUSTOM_TEMPLATES_DIR.resolve()
    if (
        not surface_pump_templates <= registered_names <= surface_pump_templates | {
            FALCON_TEMPLATE_NAME, STG_TEMPLATE_NAME, KSB_TEMPLATE_NAME, CROMPTON_TEMPLATE_NAME,
            CROMPTON_LEGACY_TEMPLATE_NAME,
        }
        or any(
            not Path(row["file_path"]).is_file()
            or (
                Path(row["file_path"]).resolve()
                != (templates_dir / row["template_name"]).resolve()
                and template_storage
                not in Path(row["file_path"]).resolve().parents
            )
            for row in templates
        )
    ):
        raise ValueError(
            "Import requires the untouched built-in template registrations. "
            "No current records were changed."
        )


def create_backup(destination):
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError("Backup destination already exists; choose a new file name.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdi-backup-") as temp_dir:
        snapshot_path = Path(temp_dir) / "pdi_system.db"
        source = sqlite3.connect(database.DB_PATH, timeout=30)
        snapshot = sqlite3.connect(str(snapshot_path))
        try:
            source.backup(snapshot)
            snapshot.commit()
        finally:
            snapshot.close()
            source.close()

        conn = sqlite3.connect(str(snapshot_path), timeout=30)
        conn.row_factory = sqlite3.Row
        references = []
        try:
            for table, id_column, file_column, category in _FILE_REFERENCES:
                rows = conn.execute(
                    f"SELECT {id_column}, {file_column} FROM {table} "
                    f"WHERE {file_column} IS NOT NULL AND {file_column} != ''"
                ).fetchall()
                for row in rows:
                    original_path = Path(row[file_column])
                    if not original_path.is_file():
                        raise FileNotFoundError(
                            f"Cannot include a referenced {category} file in the backup."
                        )
                    archive_path = (
                        f"files/{category}/{row[id_column]}_"
                        f"{original_path.name}"
                    )
                    references.append({
                        "table": table,
                        "id": row[id_column],
                        "column": file_column,
                        "category": category,
                        "archive_path": archive_path,
                        "source_path": str(original_path),
                    })
        finally:
            conn.close()

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, "pdi_system.db")
            for reference in references:
                archive.write(reference["source_path"], reference["archive_path"])
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "file_references": [
                            {key: value for key, value in item.items() if key != "source_path"}
                            for item in references
                        ]
                    },
                    separators=(",", ":"),
                ),
            )
    return destination


def _validate_archive(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("The backup archive contains duplicate file entries.")
    if "pdi_system.db" not in names or "manifest.json" not in names:
        raise ValueError("The archive is not a supported PDI backup.")
    total_size = 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise ValueError("The backup archive contains an unsafe file path.")
        if info.file_size < 0:
            raise ValueError("The backup archive is invalid.")
        if info.filename == "manifest.json" and info.file_size > 5 * 1024 * 1024:
            raise ValueError("The backup manifest is too large.")
        total_size += info.file_size
        if total_size > 2 * 1024 * 1024 * 1024:
            raise ValueError("Expanded backup data exceeds the 2 GB import limit.")
    manifest = json.loads(archive.read("manifest.json"))
    references = manifest.get("file_references")
    if not isinstance(references, list):
        raise ValueError("The backup manifest is invalid.")
    archived_names = set(names)
    for reference in references:
        if not isinstance(reference, dict) or (
            (reference.get("table"), reference.get("column"), reference.get("category"))
            not in {(item[0], item[2], item[3]) for item in _FILE_REFERENCES}
            or not isinstance(reference.get("id"), int)
            or reference["id"] < 1
            or not isinstance(reference.get("archive_path"), str)
            or reference.get("archive_path") not in archived_names
        ):
            raise ValueError("The backup manifest contains an invalid file reference.")
    return references


def import_backup(source_archive):
    copied_files = []
    staged_database = None
    with tempfile.TemporaryDirectory(prefix="pdi-restore-") as temp_dir:
        source_database = Path(temp_dir) / "pdi_system.db"
        try:
            with zipfile.ZipFile(source_archive, "r") as archive:
                references = _validate_archive(archive)
                with archive.open("pdi_system.db") as source, source_database.open("wb") as target:
                    shutil.copyfileobj(source, target)

                current = database.get_db()
                try:
                    _ensure_initial_import_target(current)
                    administrator_count = current.execute(
                        "SELECT COUNT(*) FROM users WHERE role = 'administrator' AND is_active = 1"
                    ).fetchone()[0]
                    if not administrator_count:
                        raise ValueError("Create an administrator before importing a backup.")
                    users = [
                        tuple(row)
                        for row in current.execute(
                            "SELECT id, email, display_name, password_hash, role, is_active, created_at, updated_at "
                            "FROM users"
                        ).fetchall()
                    ]
                finally:
                    current.close()

                restored = sqlite3.connect(str(source_database), timeout=30)
                restored.row_factory = sqlite3.Row
                try:
                    integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
                    if integrity != "ok":
                        raise ValueError("The backup database failed its integrity check.")
                    required_tables = {
                        row["name"]
                        for row in restored.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        ).fetchall()
                    }
                    if not {"report_jobs", "uploaded_requirements", "generated_reports"} <= required_tables:
                        raise ValueError("The backup database is missing required PDI tables.")
                    run_migrations(restored)
                    if not restored.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                    ).fetchone():
                        raise ValueError("The backup database could not be upgraded for employee accounts.")
                    imported_users = [
                        tuple(row)
                        for row in restored.execute(
                            "SELECT id, email, display_name, password_hash, role, is_active, created_at, updated_at "
                            "FROM users ORDER BY id"
                        ).fetchall()
                    ]
                    restored.execute("DELETE FROM users")
                    restored.executemany(
                        """
                        INSERT INTO users
                            (id, email, display_name, password_hash, role, is_active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        users,
                    )
                    known_emails = {row[1].strip().lower() for row in users}
                    for imported_user in imported_users:
                        if imported_user[1].strip().lower() in known_emails:
                            continue
                        restored.execute(
                            """
                            INSERT INTO users
                                (email, display_name, password_hash, role, is_active, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            imported_user[1:],
                        )
                        known_emails.add(imported_user[1].strip().lower())

                    for reference in references:
                        storage_dir = _STORAGE_BY_CATEGORY[reference["category"]]
                        safe_name = Path(reference["archive_path"]).name
                        target = storage_dir / f"import-{uuid.uuid4().hex}_{safe_name}"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(reference["archive_path"]) as archived_file, target.open("wb") as output:
                            shutil.copyfileobj(archived_file, output)
                        copied_files.append(target)
                        cursor = restored.execute(
                            f"UPDATE {reference['table']} SET {reference['column']} = ? WHERE id = ?",
                            (str(target), reference["id"]),
                        )
                        if cursor.rowcount != 1:
                            raise ValueError("The backup manifest refers to a missing database record.")
                    restored.commit()
                    restored.execute("PRAGMA journal_mode = WAL")
                    restored.execute("PRAGMA synchronous = FULL")
                    restored.commit()
                    restored.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    restored.close()

                target_path = Path(database.DB_PATH)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                staging_path = target_path.with_name(
                    f"{target_path.name}.{uuid.uuid4().hex}.import"
                )
                staged_database = staging_path
                shutil.copy2(source_database, staging_path)

                active = sqlite3.connect(database.DB_PATH, timeout=30)
                try:
                    active.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    active.close()
                os.replace(staging_path, target_path)
                staged_database = None
                return {"imported_files": len(references), "status": "Imported"}
        except Exception:
            for copied_file in copied_files:
                if copied_file.is_file():
                    copied_file.unlink()
            if staged_database and staged_database.exists():
                staged_database.unlink()
            raise
