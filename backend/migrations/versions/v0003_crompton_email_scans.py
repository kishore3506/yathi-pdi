def upgrade(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crompton_email_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL REFERENCES report_jobs(id) ON DELETE CASCADE,
            image BLOB NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS crompton_email_scans_by_job
        ON crompton_email_scans(job_id)
    """)
