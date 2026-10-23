import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from src.experiment import run_record

class ResumePipelineTests(unittest.TestCase):
    def test_two_refinements_continue_after_cooldown(self):
        def success(text):
            response = Mock(status_code=200)
            response.json.return_value = {"choices":[{"message":{"content":text}}], "usage":{"total_tokens":100}}
            return response
        replies = [success("Response: Initial"), success("Scores: Total score: 10/30"),
                   success("Response: First refinement"), success("Scores: Total score: 20/30"),
                   Mock(status_code=429, headers={"Retry-After":"10"}),
                   success("Response: Second refinement"), success("Scores: Total score: 30/30")]
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            with patch.dict(os.environ, {"GROQ_API_KEY":"test-secret", "GROQ_RESUME_ON_RATE_LIMIT":"true"}), patch("requests.post", side_effect=replies) as post, patch("prompt_lib.backends.request_budget.reserve") as reserve, patch("prompt_lib.backends.groq_pacing.wait") as wait, contextlib.redirect_stdout(io.StringIO()):
                record = run_record("responsegen", {"context":"Explain the law."},
                                    {"variant":"B", "original_model":"groq:test"}, attempts=3,
                                    checkpoint_path=checkpoint)
            self.assertEqual(record["status"], "success", record)
            self.assertEqual(record["final_output"], "Second refinement")
            self.assertEqual(list(record["result"]), ["Initial", "First refinement", "Second refinement"])
            self.assertEqual(len(record["calls"]), 6)
            self.assertEqual(post.call_args_list[4], post.call_args_list[5])
            self.assertEqual(reserve.call_count, 7)
            wait.assert_called_once_with(10)
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["answers"]), 3)
            self.assertEqual(saved["latest_answer"], "Second refinement")
