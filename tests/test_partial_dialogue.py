import contextlib
import io
import unittest
from unittest.mock import patch
from prompt_lib.backends.huggingface_api import InferenceError
from src.experiment import run_record
from src.report import render_record

class PartialDialogueTests(unittest.TestCase):
    def run_case(self, replies):
        from prompt_lib.backends.groq_api import GroqAPIWrapper
        def call(**kwargs):
            item = replies.pop(0)
            if isinstance(item, Exception):
                raise item
            return {"model":kwargs["engine"], "choices":[{"text":item,"message":{"content":item}}],
                    "usage":{"total_tokens":100}}
        with patch.object(GroqAPIWrapper, "call", side_effect=call), contextlib.redirect_stdout(io.StringIO()):
            record = run_record("responsegen", {"context":"Explain Newton's third law."},
                                {"variant":"B", "original_model":"groq:test"}, attempts=2)
        self.assertEqual(replies, [])
        return record

    def test_rate_limit_after_refinement_preserves_both_answers(self):
        record = self.run_case(["Response: Initial answer", "Scores: Total score: 20/30",
                                "Response: Refined answer", InferenceError("Groq rate limit exceeded.",status_code=429)])
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["final_output"], "Refined answer")
        self.assertEqual(record["result"]["Initial answer"]["total_score"], 20)
        self.assertIsNone(record["result"]["Refined answer"]["total_score"])
        self.assertIn("Unavailable: feedback", render_record(record))
        self.assertEqual(len(record["calls"]), 4)

    def test_initial_feedback_failure_keeps_initial_answer(self):
        record = self.run_case(["Response: Initial answer", InferenceError("Groq rate limit exceeded.")])
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["final_output"], "Initial answer")

    def test_refinement_failure_keeps_scored_answer(self):
        record = self.run_case(["Response: Initial answer", "Scores: Total score: 20/30", InferenceError("Groq rate limit exceeded.")])
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["result"]["Initial answer"]["total_score"], 20)

    def test_initial_request_failure_is_not_partial(self):
        record = self.run_case([InferenceError("Groq rate limit exceeded.")])
        self.assertEqual(record["status"], "error")
        self.assertIsNone(record["final_output"])
