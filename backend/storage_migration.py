import hashlib
import shutil
import uuid
from pathlib import Path

try:
    from . import database
    from .settings import (
        APP_DIR,
        CUSTOM_TEMPLATES_DIR,
        REPORTS_DIR,
        UPLOAD_DIR,
    )
except ImportError:
    import database
    from settings import APP_DIR, CUSTOM_TEMPLATES_DIR, REPORTS_DIR, UPLOAD_DIR


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


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _destination_for(source: Path, destination_dir: Path) -> Path:
    destination = destination_dir / source.name
    if not destination.exists():
        return destination
    if destination.is_file() and source.stat().st_size == destination.stat().st_size:
        if _file_digest(source) == _file_digest(destination):
            return destination
    return destination_dir / f"migrated-{uuid.uuid4().hex}_{source.name}"


def migrate_file_references(conn) -> int:
    updated = 0
    for table, id_column, file_column, category in _FILE_REFERENCES:
        destination_dir = _STORAGE_BY_CATEGORY[category].resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        rows = conn.execute(
            f"SELECT {id_column}, {file_column} FROM {table} "
            f"WHERE {file_column} IS NOT NULL AND {file_column} != ''"
        ).fetchall()
        for row in rows:
            stored_path = Path(row[file_column]).expanduser()
            source = stored_path if stored_path.is_absolute() else APP_DIR / stored_path
            source = source.resolve()
            try:
                source.relative_to(destination_dir)
            except ValueError:
                pass
            else:
                if not source.is_file():
                    raise FileNotFoundError(
                        f"Registered {category} file for record {row[id_column]} is missing."
                    )
                continue

            if not source.is_file():
                raise FileNotFoundError(
                    f"Cannot migrate registered {category} file for record "
                    f"{row[id_column]}; the original file is missing."
                )

            destination = _destination_for(source, destination_dir)
            if destination != source.resolve():
                shutil.copy2(source, destination)
            if (
                source.stat().st_size != destination.stat().st_size
                or _file_digest(source) != _file_digest(destination)
            ):
                raise OSError(
                    f"Verification failed while migrating a registered {category} file."
                )
            conn.execute(
                f"UPDATE {table} SET {file_column} = ? WHERE {id_column} = ?",
                (str(destination), row[id_column]),
            )
            updated += 1
    return updated


def migrate_storage() -> int:
    database.init_db()
    conn = database.get_db()
    try:
        updated = migrate_file_references(conn)
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Persistent file references migrated: {migrate_storage()}")
