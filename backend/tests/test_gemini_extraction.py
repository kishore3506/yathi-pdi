import json
import requests
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.gemini_service import GeminiService


class FakeResponse:
    status_code = 200
    ok = True

    def __init__(self, result):
        self.result = result

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(self.result)}]}}]}


class FakeUnavailableResponse:
    status_code = 503
    ok = False
    text = "Service unavailable"

    def json(self):
        return {"error": {"message": self.text}}


class GeminiExtractionTests(unittest.TestCase):
    @patch("services.gemini_service.requests.post")
    def test_sends_image_to_gemini_and_validates_lot_size(self, post):
        post.return_value = FakeResponse({
            "lot_size": 1201,
            "product_number": "HV-101",
            "missing_fields": [],
            "field_confidence": {"lot_size": "high", "product_number": "low"},
            "uncertain_fields": [],
        })

        result = GeminiService(api_key="test-key", model="gemini-test").extract_document_info(
            image_base64_list=["encoded-image"]
        )

        request = post.call_args.kwargs
        self.assertEqual(request["headers"]["x-goog-api-key"], "test-key")
        self.assertIn("gemini-test:generateContent", post.call_args.args[0])
        self.assertEqual(request["json"]["contents"][0]["parts"][1]["inlineData"]["data"], "encoded-image")
        self.assertEqual(request["json"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(result["lot_size"], 1201)
        self.assertIsNone(result["product_number"])
        self.assertIn("product_number", result["missing_fields"])
        self.assertIn("product_number", result["uncertain_fields"])

    @patch("services.gemini_service.requests.post", side_effect=requests.Timeout)
    def test_stops_after_a_model_timeout_instead_of_waiting_for_fallback(self, post):
        service = GeminiService(api_key="test-key", model="gemini-primary-test")
        result = service.extract_document_info(
            text_content="Customer: Havells; lot size: 101."
        )

        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["timeout"], service.extraction_timeout)
        self.assertIn(f"after {service.extraction_timeout} seconds", result["error"])

    @patch("services.gemini_service.requests.post")
    def test_retries_503_then_falls_back_to_available_flash_lite_model(self, post):
        post.side_effect = [
            FakeUnavailableResponse(),
            FakeUnavailableResponse(),
            FakeUnavailableResponse(),
            FakeResponse({
                "company_name": "Havells",
                "lot_size": 101,
                "missing_fields": [],
            }),
        ]

        with patch("services.gemini_service.time.sleep") as sleep:
            result = GeminiService(api_key="test-key", model="gemini-primary-test").extract_document_info(
                text_content="Customer: Havells; lot size: 101."
            )

        self.assertEqual(post.call_count, 4)
        self.assertEqual(
            [call.args[0] for call in post.call_args_list[:3]],
            ["https://generativelanguage.googleapis.com/v1beta/models/gemini-primary-test:generateContent"] * 3,
        )
        self.assertIn("gemini-3.5-flash-lite:generateContent", post.call_args_list[3].args[0])
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1])
        self.assertEqual(result["model_used"], "gemini-3.5-flash-lite")
        self.assertEqual(result["lot_size"], 101)

    @patch("services.gemini_service.requests.post")
    def test_populates_confidence_when_gemini_omits_it(self, post):
        post.return_value = FakeResponse({
            "company_name": "Havells",
            "product_type": "Surface Pump",
            "model_name": "SP-220",
            "product_number": "HV-SP-220",
            "po_number": "PO-731",
            "lot_size": 101,
            "missing_fields": [],
        })

        result = GeminiService(api_key="test-key").extract_document_info(image_base64_list=["encoded-image"])

        self.assertEqual(result["field_confidence"]["model_name"], "medium")
        self.assertEqual(result["field_confidence"]["po_number"], "medium")
        self.assertEqual(result["field_confidence"]["lot_size"], "medium")

    @patch("services.gemini_service.requests.post")
    def test_extracts_each_order_model_with_its_own_po_and_quantity(self, post):
        post.return_value = FakeResponse({
            "model_items": [
                {
                    "item_name": "Mini Pump",
                    "product_number": "MHPAE01X00",
                    "lot_size": "20",
                    "po_number": "4506312327",
                },
                {
                    "item_name": "CM05 Pump",
                    "product_number": "MHPOCE0X50",
                    "lot_size": 75,
                    "po_number": "4506302533",
                },
            ],
            "missing_fields": [],
        })

        result = GeminiService(api_key="test-key").extract_document_info(image_base64_list=["encoded-image"])

        self.assertEqual(len(result["model_items"]), 2)
        self.assertEqual(result["model_items"][0]["lot_size"], 20)
        self.assertEqual(result["model_items"][1]["lot_size"], 75)
        self.assertEqual(result["model_items"][0]["po_number"], "4506312327")
        self.assertEqual(result["model_items"][1]["product_number"], "MHPOCE0X50")
        self.assertEqual(result["model_name"], "Mini Pump")
        self.assertEqual(result["product_number"], "MHPAE01X00")
        self.assertEqual(result["lot_size"], 20)
        self.assertEqual(result["po_number"], "4506312327")

    def test_returns_clear_message_when_api_key_is_missing(self):
        result = GeminiService(api_key="").extract_document_info(image_base64_list=["encoded-image"])

        self.assertIn("GEMINI_API_KEY", result["error"])


if __name__ == "__main__":
    unittest.main()
