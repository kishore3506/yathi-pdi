from .v0001_users_and_report_revisions import upgrade
from .v0002_excel_backup import upgrade as upgrade_excel_backup
from .v0003_crompton_email_scans import upgrade as upgrade_crompton_email_scans


MIGRATIONS = ((1, upgrade), (2, upgrade_excel_backup), (3, upgrade_crompton_email_scans))


def run_migrations(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, migration in MIGRATIONS:
        if version in applied:
            continue
        migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
    conn.commit()
