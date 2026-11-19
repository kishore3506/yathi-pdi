import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path
try:
    from .settings import DATABASE_PATH, ensure_data_directories
    from .migrations import run_migrations
    from .services.falcon_report import ORDER_SHEET, SHEET_NAME, TEMPLATE_NAME, workbook_mappings
    from .services.stg_report import TEMPLATE_NAME as STG_TEMPLATE_NAME
    from .services.ksb_report import HEADER_FIELDS as KSB_FIELDS, SHEET_NAME as KSB_SHEET_NAME, TEMPLATE_NAME as KSB_TEMPLATE_NAME
    from .services import crompton_report
except ImportError:
    from settings import DATABASE_PATH, ensure_data_directories
    from migrations import run_migrations
    from services.falcon_report import ORDER_SHEET, SHEET_NAME, TEMPLATE_NAME, workbook_mappings
    from services.stg_report import TEMPLATE_NAME as STG_TEMPLATE_NAME
    from services.ksb_report import HEADER_FIELDS as KSB_FIELDS, SHEET_NAME as KSB_SHEET_NAME, TEMPLATE_NAME as KSB_TEMPLATE_NAME
    from services import crompton_report

DB_PATH = str(DATABASE_PATH)
CUSTOMER_CATALOG = json.loads(Path(__file__).with_name("customer_catalog.json").read_text(encoding="utf-8"))
SURFACE_PUMP_TEMPLATES = {
    "Havells": "Havells_Surface_Pump_PDI.xlsx",
    "Crompton": "Crompton_Surface_Pump_PDI.xlsx",
    "KSB": "KSB_Surface_Pump_PDI.xlsx",
    "KOEL": "KOEL_Surface_Pump_PDI.xlsx",
}

def get_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_db():
    ensure_data_directories()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = FULL")
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # 1. companies (Customers / OEM Brands)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        code TEXT NOT NULL,
        is_supported INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)
    
    # 2. products
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER NOT NULL,
        product_type TEXT NOT NULL,
        product_name TEXT NOT NULL,
        model_number TEXT,
        sku_number TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
    );
    """)
    
    # 3. pdi_templates
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pdi_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER NOT NULL,
        product_type TEXT NOT NULL,
        product_model TEXT,
        template_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        sheet_names TEXT NOT NULL,
        primary_sheet TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        registration_date TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
    );
    """)
    
    # 4. template_field_mappings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS template_field_mappings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL,
        field_key TEXT NOT NULL,
        field_label TEXT NOT NULL,
        target_sheet TEXT NOT NULL,
        target_cell TEXT NOT NULL,
        is_header_field INTEGER DEFAULT 1,
        default_value TEXT,
        is_required INTEGER DEFAULT 0,
        validation_rule TEXT,
        FOREIGN KEY (template_id) REFERENCES pdi_templates(id) ON DELETE CASCADE
    );
    """)
    
    # 5. customers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        address TEXT,
        created_at TEXT NOT NULL
    );
    """)
    
    # 6. uploaded_requirements
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uploaded_requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        original_name TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        status TEXT NOT NULL
    );
    """)
    
    # 7. extracted_product_details
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extracted_product_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requirement_id INTEGER,
        company_name TEXT,
        product_type TEXT,
        product_number TEXT,
        lot_size INTEGER,
        customer_name TEXT,
        customer_email TEXT,
        supplier_name TEXT,
        supplier_location TEXT,
        po_number TEXT,
        po_total_qty INTEGER,
        raw_extracted_json TEXT,
        missing_fields TEXT,
        confirmed_by_user INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (requirement_id) REFERENCES uploaded_requirements(id) ON DELETE SET NULL
    );
    """)
    
    # 8. report_jobs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS report_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_code TEXT UNIQUE NOT NULL,
        requirement_id INTEGER,
        template_id INTEGER,
        company_name TEXT NOT NULL,
        product_type TEXT NOT NULL,
        model_name TEXT,
        product_number TEXT,
        po_number TEXT,
        lot_size INTEGER NOT NULL,
        customer_name TEXT,
        customer_email TEXT,
        status TEXT NOT NULL,
        total_reports INTEGER DEFAULT 0,
        approved_reports INTEGER DEFAULT 0,
        printed_reports INTEGER DEFAULT 0,
        emailed_reports INTEGER DEFAULT 0,
        legal_excel_path TEXT,
        legal_pdf_path TEXT,
        legal_status TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (requirement_id) REFERENCES uploaded_requirements(id) ON DELETE SET NULL,
        FOREIGN KEY (template_id) REFERENCES pdi_templates(id) ON DELETE SET NULL
    );
    """)
    report_job_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(report_jobs)").fetchall()
    }
    if "model_name" not in report_job_columns:
        cursor.execute("ALTER TABLE report_jobs ADD COLUMN model_name TEXT")
    if "po_number" not in report_job_columns:
        cursor.execute("ALTER TABLE report_jobs ADD COLUMN po_number TEXT")
    for column, column_type in (
        ("legal_excel_path", "TEXT"),
        ("legal_pdf_path", "TEXT"),
        ("legal_status", "TEXT"),
    ):
        if column not in report_job_columns:
            cursor.execute(f"ALTER TABLE report_jobs ADD COLUMN {column} {column_type}")
    
    # 9. generated_reports
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS generated_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        report_code TEXT NOT NULL,
        unit_index INTEGER NOT NULL,
        serial_number TEXT,
        excel_path TEXT NOT NULL,
        pdf_path TEXT,
        status TEXT NOT NULL,
        report_data_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES report_jobs(id) ON DELETE CASCADE
    );
    """)
    
    # 10. print_jobs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS print_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        report_id INTEGER,
        printer_name TEXT NOT NULL,
        status TEXT NOT NULL,
        error_message TEXT,
        printed_at TEXT NOT NULL,
        retries INTEGER DEFAULT 0,
        FOREIGN KEY (job_id) REFERENCES report_jobs(id) ON DELETE CASCADE,
        FOREIGN KEY (report_id) REFERENCES generated_reports(id) ON DELETE SET NULL
    );
    """)
    
    # 11. email_jobs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS email_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        customer_email TEXT NOT NULL,
        customer_name TEXT,
        webhook_url TEXT,
        status TEXT NOT NULL,
        response_data TEXT,
        sent_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES report_jobs(id) ON DELETE CASCADE
    );
    """)
    
    # 12. audit_logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        report_id INTEGER,
        action TEXT NOT NULL,
        performed_by TEXT NOT NULL,
        details_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES report_jobs(id) ON DELETE SET NULL,
        FOREIGN KEY (report_id) REFERENCES generated_reports(id) ON DELETE SET NULL
    );
    """)

    conn.commit()
    run_migrations(conn)
    seed_initial_data(conn)
    conn.close()

def seed_initial_data(conn):
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    backend_dir = os.path.dirname(__file__)
    templates_dir = os.path.join(backend_dir, "templates")

    cursor.execute("UPDATE companies SET name = 'KSB', code = 'KSB' WHERE name = 'KBS'")

    for c in CUSTOMER_CATALOG:
        cursor.execute("SELECT id FROM companies WHERE LOWER(name) = LOWER(?)", (c["name"],))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO companies (name, code, is_supported, created_at) VALUES (?, ?, 1, ?)", (c["name"], c["code"], now))
            company_id = cursor.lastrowid
        else:
            company_id = row["id"]

        if c["name"] == "Falcon":
            seed_falcon_template(cursor, company_id, Path(templates_dir), now)
            continue
        if c["name"] == "STG":
            stg_path = Path(templates_dir) / STG_TEMPLATE_NAME
            if stg_path.is_file():
                cursor.execute(
                    """
                    INSERT INTO pdi_templates (company_id, product_type, template_name, file_path,
                                               sheet_names, primary_sheet, registration_date)
                    SELECT ?, 'NSP', ?, ?, '[]', '', ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pdi_templates WHERE company_id = ? AND template_name = ?
                    )
                    """,
                    (company_id, STG_TEMPLATE_NAME, str(stg_path), now, company_id, STG_TEMPLATE_NAME),
                )
            continue

        template_file = SURFACE_PUMP_TEMPLATES.get(c["name"])
        if not template_file:
            continue

        # Check template
        cursor.execute(
            "SELECT id, template_name, file_path FROM pdi_templates "
            "WHERE company_id = ? AND product_type = 'Surface Pump' AND primary_sheet = 'Surface Pump'",
            (company_id,),
        )
        t_row = cursor.fetchone()
        tpl_path = os.path.join(templates_dir, template_file)

        if (
            t_row
            and t_row["template_name"] == "KBS_Surface_Pump_PDI.xlsx"
            and not os.path.isfile(t_row["file_path"])
            and os.path.isfile(tpl_path)
        ):
            cursor.execute(
                "UPDATE pdi_templates SET template_name = ?, file_path = ? WHERE id = ?",
                ("KSB_Surface_Pump_PDI.xlsx", tpl_path, t_row["id"]),
            )

        if not t_row and os.path.exists(tpl_path):
            sheet_names = ["Surface Pump", "Sampling Std", "Annexure-1", "Annexure-2", "Annexure-3", "Sheet1", "Sheet2"]
            cursor.execute("""
                INSERT INTO pdi_templates (
                    company_id, product_type, product_model, template_name,
                    file_path, sheet_names, primary_sheet, is_active, registration_date
                ) VALUES (?, 'Surface Pump', 'MMB/CMB/SW/PB', ?, ?, ?, 'Surface Pump', 1, ?)
            """, (company_id, template_file, tpl_path, json.dumps(sheet_names), now))
            template_id = cursor.lastrowid

            mappings = [
                ("supplier_name", "Supplier Code / Name", "Surface Pump", "C3", 1, "Yathi Pumps Pvt. Ltd.", 0, ""),
                ("supplier_location", "Supplier Location", "Surface Pump", "F3", 1, "Coimbatore, Tamil Nadu", 0, ""),
                ("sku_no", "SKU No.", "Surface Pump", "C4", 1, "", 1, ""),
                ("model_name", "Model Name", "Surface Pump", "D4", 1, "", 1, "prefix:Model Name : "),
                ("po_number", "PO Number", "Surface Pump", "C5", 1, "", 0, ""),
                ("lot_qty", "Lot Qty", "Surface Pump", "D5", 1, "", 1, "prefix:Lot Qty : "),
                ("po_total_qty", "PO Total QTY", "Surface Pump", "C6", 1, "", 0, ""),
                ("inspected_by", "Inspected by", "Surface Pump", "D6", 1, "Yathi QA Inspector", 0, "prefix:Inspected by : "),
                ("reject_reason", "Reject reason", "Surface Pump", "F6", 1, "", 0, ""),
                ("total_dispatched_qty", "Total Dispatched Qty", "Surface Pump", "C7", 1, "", 0, ""),
                ("approved_by", "Approved by", "Surface Pump", "D7", 1, "Quality Head", 0, "prefix:Approved by : "),
                ("residual_qty", "Residual Qty", "Surface Pump", "C8", 1, "", 0, ""),
                ("inspection_date", "Inspection Date", "Surface Pump", "H2", 1, "", 0, "prefix:Inspection Date : \n"),
                ("lot_dispatch_date", "Lot Dispatch Date", "Surface Pump", "J2", 1, "", 0, "prefix:Lot Dispatch Date : "),
                ("final_judgment", "Final Judgment (OK/Reject)", "Surface Pump", "E5", 1, "OK", 1, "highlight_or_tick")
            ]
            for m in mappings:
                cursor.execute("""
                    INSERT INTO template_field_mappings (
                        template_id, field_key, field_label, target_sheet,
                        target_cell, is_header_field, default_value, is_required, validation_rule
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (template_id, m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7]))

        if c["name"] == "KSB":
            seed_ksb_template(cursor, company_id, Path(templates_dir), now)
        if c["name"] == "Crompton":
            seed_crompton_template(cursor, company_id, Path(templates_dir), now)

    conn.commit()


def seed_crompton_template(cursor, company_id, templates_dir, now):
    path = templates_dir / crompton_report.TEMPLATE_NAME
    if not path.is_file():
        return
    existing = cursor.execute(
        "SELECT id, file_path, is_active FROM pdi_templates WHERE company_id = ? AND template_name = ?",
        (company_id, crompton_report.TEMPLATE_NAME),
    ).fetchone()
    if existing:
        if not Path(existing["file_path"]).is_file():
            cursor.execute("UPDATE pdi_templates SET file_path = ? WHERE id = ?", (str(path), existing["id"]))
        if not existing["is_active"]:
            return
    else:
        cursor.execute(
            """INSERT INTO pdi_templates (company_id, product_type, template_name, file_path,
                                          sheet_names, primary_sheet, registration_date)
               VALUES (?, 'Surface Pump', ?, ?, ?, ?, ?)""",
            (company_id, crompton_report.TEMPLATE_NAME, str(path), json.dumps([crompton_report.SHEET_NAME]),
             crompton_report.SHEET_NAME, now),
        )
        template_id = cursor.lastrowid
        cursor.executemany(
            """INSERT INTO template_field_mappings
               (template_id, field_key, field_label, target_sheet, target_cell) VALUES (?, ?, ?, ?, ?)""",
            (
                (template_id, key, label, crompton_report.SHEET_NAME, f"E{row}")
                for row, (key, label) in enumerate(crompton_report.HEADER_FIELDS, 2)
            ),
        )
    cursor.execute(
        "UPDATE pdi_templates SET is_active = 0 WHERE company_id = ? AND template_name = ?",
        (company_id, SURFACE_PUMP_TEMPLATES["Crompton"]),
    )


def seed_ksb_template(cursor, company_id, templates_dir, now):
    template_path = templates_dir / KSB_TEMPLATE_NAME
    if not template_path.is_file():
        return
    existing = cursor.execute(
        "SELECT id, file_path, is_active FROM pdi_templates WHERE company_id = ? AND template_name = ?",
        (company_id, KSB_TEMPLATE_NAME),
    ).fetchone()
    if existing:
        if not Path(existing["file_path"]).is_file():
            cursor.execute("UPDATE pdi_templates SET file_path = ? WHERE id = ?", (str(template_path), existing["id"]))
        if not existing["is_active"]:
            return
    else:
        cursor.execute(
            """INSERT INTO pdi_templates (company_id, product_type, template_name, file_path,
                                          sheet_names, primary_sheet, registration_date)
               VALUES (?, 'Surface Pump', ?, ?, ?, ?, ?)""",
            (company_id, KSB_TEMPLATE_NAME, str(template_path), json.dumps([KSB_SHEET_NAME, "Sheet1"]), KSB_SHEET_NAME, now),
        )
        template_id = cursor.lastrowid
        cursor.executemany(
            """INSERT INTO template_field_mappings
               (template_id, field_key, field_label, target_sheet, target_cell) VALUES (?, ?, ?, ?, ?)""",
            ((template_id, field, label, KSB_SHEET_NAME, cell) for field, (cell, label) in KSB_FIELDS.items()),
        )
    cursor.execute(
        "UPDATE pdi_templates SET is_active = 0 WHERE company_id = ? AND template_name = ?",
        (company_id, SURFACE_PUMP_TEMPLATES["KSB"]),
    )


def seed_falcon_template(cursor, company_id, templates_dir, now):
    template_path = templates_dir / TEMPLATE_NAME
    if not template_path.is_file():
        return
    existing = cursor.execute(
        "SELECT id, file_path FROM pdi_templates WHERE company_id = ? AND template_name = ?",
        (company_id, TEMPLATE_NAME),
    ).fetchone()
    if existing:
        if not Path(existing["file_path"]).is_file():
            cursor.execute("UPDATE pdi_templates SET file_path = ? WHERE id = ?", (str(template_path), existing["id"]))
        return

    cursor.execute(
        """
        INSERT INTO pdi_templates (company_id, product_type, template_name, file_path,
                                   sheet_names, primary_sheet, is_active, registration_date)
        VALUES (?, 'OEM Products', ?, ?, ?, ?, 1, ?)
        """,
        (company_id, TEMPLATE_NAME, str(template_path), json.dumps([SHEET_NAME, ORDER_SHEET]), SHEET_NAME, now),
    )
    template_id = cursor.lastrowid
    cursor.executemany(
        """
        INSERT INTO template_field_mappings (template_id, field_key, field_label, target_sheet,
                                             target_cell, is_header_field, is_required)
        VALUES (?, ?, ?, ?, ?, 1, 0)
        """,
        ((template_id, *mapping) for mapping in workbook_mappings()),
    )


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully for Yathi Pumps PDI Automation.")
