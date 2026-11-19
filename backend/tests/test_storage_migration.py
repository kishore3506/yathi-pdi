import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import storage_migration


class StorageMigrationTests(unittest.TestCase):
    def test_migration_preserves_existing_destination_and_repoints_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "old location" / "purchase order.pdf"
            destination_dir = root / "persistent data" / "uploads"
            destination = destination_dir / source.name
            source.parent.mkdir(parents=True)
            destination_dir.mkdir(parents=True)
            source.write_bytes(b"original upload")
            destination.write_bytes(b"existing destination")

            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute(
                "CREATE TABLE uploaded_requirements (id INTEGER PRIMARY KEY, file_path TEXT)"
            )
            conn.execute(
                "INSERT INTO uploaded_requirements (id, file_path) VALUES (1, ?)",
                (str(source),),
            )

            with (
                patch.object(
                    storage_migration,
                    "_FILE_REFERENCES",
                    (("uploaded_requirements", "id", "file_path", "uploads"),),
                ),
                patch.dict(
                    storage_migration._STORAGE_BY_CATEGORY,
                    {"uploads": destination_dir},
                ),
            ):
                updated = storage_migration.migrate_file_references(conn)

            migrated_path = Path(
                conn.execute(
                    "SELECT file_path FROM uploaded_requirements WHERE id = 1"
                ).fetchone()["file_path"]
            )
            self.assertEqual(updated, 1)
            self.assertNotEqual(migrated_path, destination)
            self.assertEqual(migrated_path.read_bytes(), b"original upload")
            self.assertEqual(destination.read_bytes(), b"existing destination")
            self.assertEqual(source.read_bytes(), b"original upload")
            conn.close()

    def test_missing_referenced_file_fails_without_rewriting_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing = root / "missing.pdf"
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute(
                "CREATE TABLE uploaded_requirements (id INTEGER PRIMARY KEY, file_path TEXT)"
            )
            conn.execute(
                "INSERT INTO uploaded_requirements (id, file_path) VALUES (7, ?)",
                (str(missing),),
            )

            with (
                patch.object(
                    storage_migration,
                    "_FILE_REFERENCES",
                    (("uploaded_requirements", "id", "file_path", "uploads"),),
                ),
                patch.dict(
                    storage_migration._STORAGE_BY_CATEGORY,
                    {"uploads": root / "uploads"},
                ),
                self.assertRaisesRegex(FileNotFoundError, "record 7"),
            ):
                storage_migration.migrate_file_references(conn)

            self.assertEqual(
                conn.execute(
                    "SELECT file_path FROM uploaded_requirements WHERE id = 7"
                ).fetchone()["file_path"],
                str(missing),
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
