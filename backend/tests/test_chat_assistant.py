import json
import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.gemini_service import GeminiService
from services.chat_context import build_chat_context
from services.report_summary import build_daily_comparison_summary, render_daily_comparison_pdf
from routes.chat import ChatMessage, ChatRequest, parse_report_request


class FakeChatResponse:
    status_code = 200
    ok = True

    def json(self):
        return {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Use the inspection page to start a new report."}]
                }
            }]
        }


class GeminiChatTests(unittest.TestCase):
    @patch("routes.chat.GeminiService")
    def test_extracts_chat_report_requirements_without_returning_contact_details(self, gemini_service):
        assistant = gemini_service.return_value
        assistant.api_key = "configured"
        assistant.extract_document_info.return_value = {
            "company_name": "Havells",
            "product_type": "Surface Pump",
            "model_items": [{
                "model_name": "Pump A",
                "product_number": "SKU-1",
                "lot_size": 150,
                "po_number": "PO-1",
            }],
            "customer_email": "qa@example.com",
        }

        result = parse_report_request(ChatRequest(messages=[
            ChatMessage(role="user", content="Create a Havells report for Pump A, SKU-1, lot 150, PO-1."),
        ]))

        self.assertEqual(result["company_name"], "Havells")
        self.assertEqual(result["product_type"], "Surface Pump")
        self.assertEqual(result["models"], [{
            "model_name": "Pump A",
            "product_number": "SKU-1",
            "lot_size": 150,
            "po_number": "PO-1",
        }])
        self.assertNotIn("customer_email", result)

    @patch("services.gemini_service.requests.post")
    def test_sends_conversation_to_gemini_and_returns_text(self, post):
        post.return_value = FakeChatResponse()
        assistant = GeminiService(api_key="test-key", model="gemini-test")
        context = {
            "as_of_local_date": "2026-11-13",
            "reports_generated_today": 7,
            "application_reference": {
                "supported_customers": ["Havells", "Crompton", "KSB", "KOEL"],
            },
        }

        answer = assistant.generate_chat_response([
            {"role": "user", "content": "How do I start?"},
            {"role": "assistant", "content": "Open New Inspection."},
            {"role": "user", "content": "Then what?"},
        ], application_context=context)

        request = post.call_args.kwargs
        self.assertEqual(answer, "Use the inspection page to start a new report.")
        self.assertEqual(request["headers"]["x-goog-api-key"], "test-key")
        self.assertIn("gemini-test:generateContent", post.call_args.args[0])
        self.assertEqual(
            [message["role"] for message in request["json"]["contents"]],
            ["user", "model", "user"],
        )
        system_instruction = request["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("read-only", system_instruction)
        self.assertIn("Answer any question about the app", system_instruction)
        self.assertIn("Do not restrict answers to a predefined list of topics", system_instruction)
        self.assertIn("do not start an action from a question or attachment alone", system_instruction)
        self.assertIn("Current read-only application reference", system_instruction)
        self.assertIn("Keep greetings brief", system_instruction)
        self.assertIn('"reports_generated_today":7', system_instruction)
        self.assertIn('"supported_customers":["Havells","Crompton","KSB","KOEL"]', system_instruction)

    @patch("services.gemini_service.requests.post")
    def test_report_analysis_uses_report_specific_read_only_instruction(self, post):
        post.return_value = FakeChatResponse()
        assistant = GeminiService(api_key="test-key", model="gemini-test")

        assistant.generate_chat_response(
            [{"role": "user", "content": "Analyze the uploaded report."}],
            report_analysis=True,
        )

        request = post.call_args.kwargs["json"]
        system_instruction = request["systemInstruction"]["parts"][0]["text"]
        self.assertIn("analyze PDI reports", system_instruction)
        self.assertIn("read-only analysis", system_instruction)
        self.assertEqual(request["generationConfig"]["maxOutputTokens"], 2048)
        self.assertIn("Analyze the uploaded report.", request["contents"][0]["parts"][0]["text"])

    @patch("services.chat_context.get_db")
    def test_builds_current_report_counts_from_read_only_database(self, get_db):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE report_jobs (
                id INTEGER PRIMARY KEY,
                company_name TEXT,
                product_type TEXT,
                model_name TEXT,
                status TEXT,
                created_at TEXT,
                legal_status TEXT,
                job_code TEXT,
                lot_size INTEGER
            );
            CREATE TABLE generated_reports (
                id INTEGER PRIMARY KEY,
                job_id INTEGER,
                created_at TEXT,
                status TEXT,
                report_code TEXT
            );
            CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE pdi_templates (
                id INTEGER PRIMARY KEY,
                company_id INTEGER,
                product_type TEXT,
                product_model TEXT,
                template_name TEXT,
                primary_sheet TEXT,
                is_active INTEGER
            );
            CREATE TABLE template_field_mappings (
                id INTEGER PRIMARY KEY,
                template_id INTEGER,
                field_key TEXT,
                field_label TEXT,
                target_sheet TEXT,
                target_cell TEXT,
                is_required INTEGER,
                validation_rule TEXT
            );
            CREATE TABLE print_jobs (id INTEGER PRIMARY KEY, status TEXT);
            CREATE TABLE email_jobs (id INTEGER PRIMARY KEY, status TEXT);
        """)
        today = date.today().isoformat()
        connection.execute(
            """INSERT INTO report_jobs
               (id, company_name, product_type, model_name, status, created_at, legal_status, job_code, lot_size)
               VALUES (1, 'Havells', 'Surface Pump', 'Pump A', 'Awaiting Review', ?, 'Pending', 'JOB-YATHI-HAV-01', 101)""",
            (f"{today}T10:00:00",),
        )
        connection.execute(
            "INSERT INTO generated_reports VALUES (1, 1, ?, 'Awaiting Review', 'Havells_PDI_X01_001')",
            (f"{today}T10:01:00",),
        )
        connection.execute("INSERT INTO companies VALUES (1, 'Havells')")
        connection.execute(
            """INSERT INTO pdi_templates
               VALUES (1, 1, 'Surface Pump', 'MMB/CMB/SW/PB', 'Havells_Surface_Pump_PDI.xlsx', 'Surface Pump', 1)"""
        )
        connection.execute(
            """INSERT INTO template_field_mappings
               VALUES (1, 1, 'sku_no', 'SKU No.', 'Surface Pump', 'C4', 1, '')"""
        )
        connection.commit()
        get_db.return_value = connection

        context = build_chat_context(
            screen="job-review", role="inspector", question="Is Havells_PDI_X01_001 approved?"
        )

        self.assertEqual(context["reports_generated_today"], 1)
        self.assertEqual(context["jobs_created_today"], 1)
        self.assertEqual(context["viewer"], {"screen": "job-review", "role": "inspector"})
        self.assertEqual(context["inspection_lookup"][0]["report_status"], "Awaiting Review")
        self.assertEqual(context["inspection_lookup"][0]["lot_size"], 101)
        self.assertIn("STG", context["application_reference"]["supported_customers"])
        self.assertIn("46 photo slots", context["application_reference"]["template_selection"]["stg"])
        self.assertEqual(context["reports_today_by_customer"], [
            {"company_name": "Havells", "reports_generated": 1},
        ])
        self.assertEqual(context["reports_today_by_model"], [{
            "company_name": "Havells",
            "model_name": "Pump A",
            "reports_generated": 1,
        }])
        self.assertEqual(context["reports_by_status"], [
            {"status": "Awaiting Review", "count": 1},
        ])
        self.assertEqual(context["application_reference"]["report_generation"]["lot_size_rules"][2], {
            "minimum_lot_size": 1201,
            "maximum_lot_size": 2500,
            "reports": 3,
        })
        self.assertEqual(context["application_reference"]["active_templates"], [{
            "company_name": "Havells",
            "product_type": "Surface Pump",
            "product_model": "MMB/CMB/SW/PB",
            "template_name": "Havells_Surface_Pump_PDI.xlsx",
            "primary_sheet": "Surface Pump",
        }])
        self.assertEqual(context["application_reference"]["active_template_field_mappings"], [{
            "company_name": "Havells",
            "template_name": "Havells_Surface_Pump_PDI.xlsx",
            "field_key": "sku_no",
            "field_label": "SKU No.",
            "target_sheet": "Surface Pump",
            "target_cell": "C4",
            "is_required": 1,
            "validation_rule": "",
        }])
        context_json = json.dumps(context)
        self.assertNotIn("customer_email", context_json)
        self.assertNotIn("GMAIL_APP_PASSWORD", context_json)
        self.assertIn("full inspection readings", context["application_reference"]["privacy_boundary"])

    def test_requires_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
            GeminiService(api_key="").generate_chat_response([
                {"role": "user", "content": "Hello"},
            ])

    def test_requires_last_message_from_user(self):
        assistant = GeminiService(api_key="test-key")

        with self.assertRaisesRegex(ValueError, "end with a user message"):
            assistant.generate_chat_response([
                {"role": "assistant", "content": "Hello"},
            ])

    def test_daily_comparison_and_pdf_use_generated_report_counts(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE report_jobs (
                id INTEGER PRIMARY KEY,
                company_name TEXT,
                product_type TEXT,
                model_name TEXT,
                status TEXT,
                created_at TEXT
            );
            CREATE TABLE generated_reports (
                id INTEGER PRIMARY KEY,
                job_id INTEGER,
                created_at TEXT
            );
        """)
        connection.executemany(
            "INSERT INTO report_jobs VALUES (?, 'Havells', 'Surface Pump', 'Pump A', 'Completed', ?)",
            [
                (1, "2026-11-13T10:00:00"),
                (2, "2026-11-12T10:00:00"),
            ],
        )
        connection.executemany(
            "INSERT INTO generated_reports VALUES (?, ?, ?)",
            [
                (1, 1, "2026-11-13T10:01:00"),
                (2, 1, "2026-11-13T10:02:00"),
                (3, 2, "2026-11-12T10:01:00"),
            ],
        )
        connection.commit()

        summary = build_daily_comparison_summary(
            as_of_date=date(2026, 11, 13),
            connection=connection,
        )
        pdf = render_daily_comparison_pdf(summary)

        self.assertEqual(summary["reports_today"], 2)
        self.assertEqual(summary["reports_yesterday"], 1)
        self.assertEqual(summary["report_difference"], 1)
        self.assertEqual(summary["model_breakdown"][0]["difference"], 1)
        self.assertTrue(pdf.startswith(b"%PDF"))
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute(
                "INSERT INTO generated_reports VALUES (4, 1, '2026-11-13T10:03:00')"
            )
        connection.close()


if __name__ == "__main__":
    unittest.main()
