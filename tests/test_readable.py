import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.report import write_report
from src.check_config import describe

class ReadableTests(unittest.TestCase):
    def test_existing_failure_is_readable_and_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "failed.jsonl"
            source.write_text(json.dumps({"status":"error", "input":{"context":"Why?"}, "error":"No credits", "final_output":None}), encoding="utf-8")
            with patch("requests.post") as post:
                dest = write_report(source)
                self.assertIn("No credits", dest.read_text(encoding="utf-8"))
                with self.assertRaises(FileExistsError):
                    write_report(source)
                with self.assertRaises(ValueError):
                    write_report(source, source)
                post.assert_not_called()

    def test_preflight_resolves_actual_hf_stage_without_network(self):
        with patch("requests.post") as post:
            output = describe("experiments/C.json")
            self.assertIn("Refinement: hf:", output)
            self.assertIn("NOT verified", output)
            post.assert_not_called()
