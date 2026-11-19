TABLE_SHEETS = {
    "report_jobs": "Inspection Jobs",
    "generated_reports": "Reports",
    "uploaded_requirements": "Uploaded Requirements",
    "extracted_product_details": "Extracted Details",
    "companies": "Companies",
    "customers": "Customers",
    "products": "Products",
    "pdi_templates": "Templates",
    "template_field_mappings": "Template Field Mappings",
    "print_jobs": "Print History",
    "email_jobs": "Email History",
    "audit_logs": "Activity Log",
}


def upgrade(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS excel_backup_revision (id INTEGER PRIMARY KEY, revision BLOB NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO excel_backup_revision VALUES (1, randomblob(16))")
    existing_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in TABLE_SHEETS.keys() & existing_tables:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS excel_backup_{table}_{operation.lower()}
                AFTER {operation} ON {table}
                BEGIN
                    UPDATE excel_backup_revision SET revision = randomblob(16) WHERE id = 1;
                END
            """)
