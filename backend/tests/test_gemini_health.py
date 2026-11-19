import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import main


class GeminiHealthTests(unittest.TestCase):
    def setUp(self):
        self.original_result = main._gemini_health_result
        self.original_checked_at = main._gemini_health_checked_at
        self.original_running = main._gemini_health_probe_running
        main._gemini_health_result = None
        main._gemini_health_checked_at = 0.0
        main._gemini_health_probe_running = False

    def tearDown(self):
        main._gemini_health_result = self.original_result
        main._gemini_health_checked_at = self.original_checked_at
        main._gemini_health_probe_running = self.original_running

    def test_health_request_returns_while_gemini_probe_is_slow(self):
        release_probe = threading.Event()

        def check_health(_self):
            release_probe.wait(2)
            return {
                "status": "connected",
                "provider": "Google Gemini API",
                "active_model": "gemini-test",
                "api_key_configured": True,
            }

        service = type(
            "FakeGeminiService",
            (),
            {
                "api_key": "configured",
                "model": "gemini-test",
                "check_health": check_health,
            },
        )()

        with patch.object(main, "GeminiService", return_value=service):
            started_at = time.monotonic()
            result = main.health_check()
            elapsed = time.monotonic() - started_at
            self.assertLess(elapsed, 0.5)
            self.assertEqual(result["gemini"]["status"], "checking")

            release_probe.set()
            deadline = time.monotonic() + 1
            while main._gemini_health_probe_running and time.monotonic() < deadline:
                time.sleep(0.01)

            refreshed = main.health_check()

        self.assertEqual(refreshed["gemini"]["status"], "connected")


if __name__ == "__main__":
    unittest.main()
