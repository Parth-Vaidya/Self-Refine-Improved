"""Offline provider switching tests; no real credentials or inference calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import traceback
import tempfile
import unittest
from unittest.mock import Mock, mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prompt-lib"))
from prompt_lib.backends.groq_api import GroqAPIWrapper as Groq
from prompt_lib.backends.huggingface_api import HuggingFaceAPIWrapper as HF, InferenceError
from prompt_lib.experiment import CURRENT

HF_MODEL = "hf:Qwen/Qwen3-4B-Instruct-2507:nscale"
GROQ_MODEL = "groq:openai/gpt-oss-20b"


def response(status=200, text="refined"):
    r = Mock(status_code=status, headers={})
    r.json.return_value = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
    return r


class GroqTests(unittest.TestCase):
    def setUp(self):
        pacing = patch.dict(os.environ, {"GROQ_MIN_INTERVAL_SECONDS": "0"})
        pacing.start()
        self.addCleanup(pacing.stop)
        budget_patch = patch("prompt_lib.backends.request_budget.reserve", return_value=1)
        budget_patch.start()
        self.addCleanup(budget_patch.stop)
        env = patch.dict(os.environ, {"HF_TOKEN": "fake-hf-secret", "GROQ_API_KEY": "fake-groq-secret",
            "HF_GROQ_FALLBACK": "true", "GROQ_MODEL_ID": "openai/gpt-oss-20b",
            "HF_TIMEOUT": "5", "GROQ_TIMEOUT": "6", "HF_MAX_RETRIES": "1", "GROQ_MAX_RETRIES": "1"})
        env.start()
        self.addCleanup(env.stop)

    def test_groq_payload_and_isolated_key(self):
        with patch("requests.post", return_value=response()) as post:
            result = Groq.call("same prompt", engine=GROQ_MODEL, stop_token="###", temperature=0.2, max_tokens=30)
        self.assertEqual(post.call_args.args[0], Groq.endpoint)
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer fake-groq-secret"})
        self.assertEqual(post.call_args.kwargs["json"]["model"], "openai/gpt-oss-20b")
        self.assertEqual(post.call_args.kwargs["json"]["messages"], [{"role": "user", "content": "same prompt"}])
        self.assertEqual(post.call_args.kwargs["json"]["stop"], ["###"])
        self.assertEqual(post.call_args.kwargs["timeout"], 6)
        self.assertEqual(result["model"], GROQ_MODEL)
        self.assertNotIn("secret", json.dumps(result))

    def test_hf_quota_switch_preserves_prompt_and_settings(self):
        for status in (402, 429):
            initial = [response(status)] * (2 if status == 429 else 1)
            with self.subTest(status=status), patch("requests.post", side_effect=initial + [response()]) as post, patch("time.sleep"):
                result = HF.call("same prompt", engine=HF_MODEL, max_tokens=30, temperature=0.3, stop_token="###")
            self.assertEqual(result["model"], GROQ_MODEL)
            self.assertEqual(result["inference"]["fallback"]["reason_http_status"], status)
            self.assertEqual(result["inference"]["fallback"]["primary_attempts"], len(initial))
            first = dict(post.call_args_list[0].kwargs["json"])
            last = dict(post.call_args_list[-1].kwargs["json"])
            first.pop("model")
            last.pop("model")
            self.assertEqual(first, last)
            self.assertEqual(post.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer fake-hf-secret")
            self.assertEqual(post.call_args_list[-1].kwargs["headers"]["Authorization"], "Bearer fake-groq-secret")

    def test_no_switch_on_auth_model_or_server_errors(self):
        for status in (400, 401, 403, 404, 503):
            with self.subTest(status=status), patch("requests.post", return_value=response(status)) as post, patch("time.sleep"):
                with self.assertRaises(InferenceError):
                    HF.call("p", engine=HF_MODEL)
                self.assertTrue(all(c.args[0] == HF.endpoint for c in post.call_args_list))

    def test_disabled_or_missing_key(self):
        for settings in ({"HF_GROQ_FALLBACK": "false"}, {"GROQ_API_KEY": ""}):
            with patch.dict(os.environ, settings), patch("requests.post", return_value=response(402)) as post:
                with self.assertRaises(InferenceError): HF.call("p", engine=HF_MODEL)
                post.assert_called_once()
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}), patch("requests.post") as post:
            with self.assertRaisesRegex(InferenceError, "GROQ_API_KEY"):
                Groq.call("p", engine=GROQ_MODEL)
            post.assert_not_called()

    def test_both_providers_exhausted_fail_safely(self):
        with patch("requests.post", side_effect=[response(402), response(429)]) as post, patch("time.sleep"):
            try:
                HF.call("p", engine=HF_MODEL)
            except InferenceError:
                trace = traceback.format_exc()
                self.assertIn("Groq fallback failed", trace)
                self.assertNotIn("fake-hf-secret", trace)
                self.assertNotIn("fake-groq-secret", trace)
            else:
                self.fail("Expected both providers to fail")
            self.assertEqual(post.call_count, 2)

    def test_fallback_effective_model_and_cost_in_experiment(self):
        from prompt_lib.backends.openai_api import OpenaiAPIWrapper
        config = dict(variant="C", original_model="gemini-1.5-flash", refinement_model=HF_MODEL,
                      hf_groq_fallback=True, groq_model=GROQ_MODEL, calls=[],
                      prices={HF_MODEL: {"input_per_million": 100, "output_per_million": 100},
                              GROQ_MODEL: {"input_per_million": 1, "output_per_million": 2}})
        marker = CURRENT.set(config)
        try:
            with patch("requests.post", side_effect=[response(402), response()]) as post:
                result = OpenaiAPIWrapper.call("p", 30, "legacy", "###", 0.2, stage="refinement")
            self.assertEqual(OpenaiAPIWrapper.get_first_response(result), "refined")
            record = config["calls"][0]
            self.assertEqual(record["requested_model"], HF_MODEL)
            self.assertEqual(record["effective_model"], GROQ_MODEL)
            self.assertAlmostEqual(record["cost_usd"], 0.000014)
            self.assertIsNone(record["fallback"]["primary_cost_usd"])
        finally:
            CURRENT.reset(marker)

    def test_baselines_and_original_c_stages_cannot_switch(self):
        from prompt_lib.backends.openai_api import OpenaiAPIWrapper
        for variant, stage in (("A", "generation"), ("B", "refinement"), ("C", "generation"), ("C", "feedback")):
            marker = CURRENT.set(dict(variant=variant, original_model=HF_MODEL, refinement_model=HF_MODEL,
                                      hf_groq_fallback=True, calls=[]))
            try:
                with patch("requests.post", return_value=response(402)) as post, self.assertRaises(InferenceError):
                    OpenaiAPIWrapper.call("p", 30, HF_MODEL, "###", 0.2, stage=stage)
                post.assert_called_once()
            finally:
                CURRENT.reset(marker)

    def test_actual_loop_reports_fallback_and_final_output(self):
        from src.experiment import run_record
        from prompt_lib.backends.gemini_api import GeminiAPIWrapper
        queue = ["Acronym: FIRST", "Total score: 10/25", "Total score: 20/25"]
        def original(**kwargs):
            return {"model": kwargs["engine"], "choices": [{"text": queue.pop(0)}]}
        config = dict(variant="C", original_model="gemini-1.5-flash", refinement_model=HF_MODEL, hf_groq_fallback=True)
        with patch.object(GeminiAPIWrapper, "call", side_effect=original), \
             patch("requests.post", side_effect=[response(402), response(text="Title: title\nAcronym: FINAL")]), \
             patch("src.acronym.task_iterate.open", mock_open()), contextlib.redirect_stdout(io.StringIO()) as terminal:
            record = run_record("acronym", {"title": "title"}, config, attempts=2)
        self.assertEqual(record["status"], "success", record)
        self.assertEqual(record["final_output"], "FINAL")
        self.assertIn("HF TO GROQ FALLBACK", terminal.getvalue())
        self.assertEqual(record["calls"][2]["effective_model"], GROQ_MODEL)

    def test_failed_fallback_keeps_attempted_model_in_record(self):
        from prompt_lib.backends.openai_api import OpenaiAPIWrapper
        config = dict(variant="C", original_model="gemini-1.5-flash", refinement_model=HF_MODEL,
                      hf_groq_fallback=True, calls=[])
        marker = CURRENT.set(config)
        try:
            with patch("requests.post", side_effect=[response(402), response(401)]), self.assertRaises(InferenceError):
                OpenaiAPIWrapper.call("p", 30, HF_MODEL, None, 0.2, stage="refinement")
            self.assertEqual(config["calls"][0]["effective_model"], GROQ_MODEL)
            self.assertEqual(config["calls"][0]["status"], "error")
            self.assertEqual(config["calls"][0]["fallback"]["reason_http_status"], 402)
            self.assertIsNone(config["calls"][0]["cost_usd"])
        finally:
            CURRENT.reset(marker)

    def test_configuration_is_explicit_and_rejects_baseline_fallback(self):
        from src.experiment import configuration
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            for variant in ("A", "B"):
                path.write_text(json.dumps({"variant": variant, "hf_groq_fallback": True}))
                with self.assertRaises(InferenceError): configuration(path)
            path.write_text(json.dumps({"variant": "C", "hf_groq_fallback": False}))
            self.assertFalse(configuration(path)["hf_groq_fallback"])
            path.write_text(json.dumps({"variant": "C", "hf_groq_fallback": True}))
            self.assertTrue(configuration(path)["hf_groq_fallback"])
            self.assertEqual(configuration(path)["groq_model"], GROQ_MODEL)


if __name__ == "__main__":
    unittest.main()
