import concurrent.futures
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prompt_lib.backends import request_budget as budget
from prompt_lib.backends.groq_api import GroqAPIWrapper
from prompt_lib.backends.huggingface_api import InferenceError
from src.responsegen.parsing import response_text, feedback_text

class BudgetAndDialogueTests(unittest.TestCase):
    def setUp(self):
        pacing = patch.dict("os.environ", {"GROQ_MIN_INTERVAL_SECONDS": "0"})
        pacing.start()
        self.addCleanup(pacing.stop)

    def test_atomic_cap_persists_across_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "budget.db"
            with closing(sqlite3.connect(ledger)) as db, db:
                db.execute("CREATE TABLE budget (id INTEGER PRIMARY KEY, used INTEGER)")
                db.execute("INSERT INTO budget VALUES (1, 698)")
            with patch.object(budget, "LEDGER", ledger):
                def attempt(_):
                    try:
                        return budget.reserve()
                    except RuntimeError:
                        return None
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(attempt, range(8)))
                self.assertEqual(sorted(v for v in results if v), [699, 700])
                with self.assertRaises(RuntimeError):
                    budget.reserve()
            with closing(sqlite3.connect(ledger)) as db, db:
                self.assertEqual(db.execute("SELECT used FROM budget").fetchone()[0], 700)

    def test_budget_failure_prevents_network(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-secret"}), patch.object(budget, "reserve", side_effect=RuntimeError), patch("requests.post") as post:
            with self.assertRaises(InferenceError):
                GroqAPIWrapper.call("test", engine="groq:test")
            post.assert_not_called()

    def test_retry_reserves_each_attempt(self):
        import requests
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-secret", "GROQ_MAX_RETRIES": "2"}), patch.object(budget, "reserve") as reserve, patch("requests.post", side_effect=requests.Timeout), patch("time.sleep"):
            with self.assertRaises(InferenceError):
                GroqAPIWrapper.call("test", engine="groq:test")
            self.assertEqual(reserve.call_count, 1)

    def test_dialogue_preserves_multiline_with_optional_labels(self):
        self.assertEqual(response_text("Response: Force equals mass.\nF = ma\n###"), "Force equals mass.\nF = ma")
        self.assertEqual(response_text("Force equals mass.\nF = ma"), "Force equals mass.\nF = ma")
        self.assertIn("Total score: 29/30", feedback_text("**Total score:** 29 / 30"))
        with self.assertRaises(InferenceError):
            feedback_text("No score available")
