import contextlib
import io
import json
import os
from pathlib import Path
import sys
import traceback
import tempfile
import unittest
from unittest.mock import Mock, patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prompt-lib"))
from prompt_lib.backends.huggingface_api import HuggingFaceAPIWrapper as HF, InferenceError
from prompt_lib.experiment import CURRENT, select_model, observed_call

MODEL = "hf:Qwen/Qwen3-4B-Instruct-2507:nscale"


def response(text="refined", status=200, usage=None):
    r = Mock(status_code=status, headers={})
    r.json.return_value = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                           "usage": usage or {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
    return r


class AdapterTests(unittest.TestCase):
    def setUp(self):
        pacing = patch.dict(os.environ, {"GROQ_MIN_INTERVAL_SECONDS": "0"})
        pacing.start()
        self.addCleanup(pacing.stop)
        budget_patch = patch("prompt_lib.backends.request_budget.reserve", return_value=1)
        budget_patch.start()
        self.addCleanup(budget_patch.stop)
        self.env = patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real", "HF_MAX_RETRIES": "1", "HF_TIMEOUT": "5", "HF_GROQ_FALLBACK": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_payload_usage_and_safe_response(self):
        with patch("requests.post", return_value=response()) as post:
            result = HF.call("unchanged prompt", engine=MODEL, stop_token="###", max_tokens=30, temperature=0.2)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "unchanged prompt"}])
        self.assertEqual(kwargs["json"]["model"], MODEL[3:])
        self.assertEqual(kwargs["json"]["stop"], ["###"])
        self.assertEqual(kwargs["timeout"], 5)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(result["usage"]["total_tokens"], 12)
        self.assertNotIn("test-secret", json.dumps(result))

    def test_rate_limit_retry(self):
        first = response(status=429)
        first.headers = {"Retry-After": "3"}
        with patch("requests.post", side_effect=[first, response()]) as post, patch("time.sleep") as sleep:
            result = HF.call("p", engine=MODEL)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(3)
        self.assertEqual(result["inference"]["attempts"], 2)

    def test_failures_never_print_provider_secret(self):
        import requests
        for failure in [requests.Timeout("test-secret-not-real"), requests.ConnectionError("test-secret-not-real")]:
            with self.subTest(failure=type(failure)), patch("requests.post", side_effect=failure), patch("time.sleep"):
                try:
                    HF.call("p", engine=MODEL)
                except InferenceError:
                    self.assertNotIn("test-secret-not-real", traceback.format_exc())
                else:
                    self.fail("Expected failure")
        for status in (401, 403, 404, 429, 500, 503):
            with self.subTest(status=status), patch("requests.post", return_value=response(status=status)) as post, patch("time.sleep"):
                with self.assertRaises(InferenceError):
                    HF.call("p", engine=MODEL)
                self.assertEqual(post.call_count, 2 if status in (429, 500, 503) else 1)

    def test_missing_token_bad_config_empty_and_echo(self):
        with patch.dict(os.environ, {"HF_TOKEN": ""}), patch("requests.post") as post:
            with self.assertRaises(InferenceError):
                HF.call("p", engine=MODEL)
            post.assert_not_called()
        for text in ("", "test-secret-not-real"):
            with patch("requests.post", return_value=response(text)):
                with self.assertRaises(InferenceError):
                    HF.call("p", engine=MODEL)
        with patch.dict(os.environ, {"HF_TIMEOUT": "secret-invalid-value"}):
            with self.assertRaisesRegex(InferenceError, "Invalid HF"):
                HF.call("p", engine=MODEL)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        pacing = patch.dict(os.environ, {"GROQ_MIN_INTERVAL_SECONDS": "0"})
        pacing.start()
        self.addCleanup(pacing.stop)
        budget_patch = patch("prompt_lib.backends.request_budget.reserve", return_value=1)
        budget_patch.start()
        self.addCleanup(budget_patch.stop)
        env = patch.dict(os.environ, {"HF_GROQ_FALLBACK": "false"})
        env.start()
        self.addCleanup(env.stop)

    def test_selection(self):
        for variant in "ABC":
            config = dict(variant=variant, original_model="original", generation_model="generator",
                          feedback_model="critic", refinement_model=MODEL, calls=[])
            marker = CURRENT.set(config)
            try:
                self.assertEqual(select_model("generation", "legacy"), "original" if variant == "B" else "generator")
                if variant == "A":
                    with self.assertRaises(InferenceError): select_model("refinement", "legacy")
                else:
                    self.assertEqual(select_model("refinement", "legacy"), MODEL if variant == "C" else "original")
            finally:
                CURRENT.reset(marker)
        self.assertEqual(select_model("refinement", "legacy"), "legacy")

    def test_telemetry_estimate_and_failure(self):
        config = {"calls": [], "prices": {MODEL: {"input_per_million": 1, "output_per_million": 2}}}
        marker = CURRENT.set(config)
        try:
            observed_call(lambda **k: response().json(), "refinement", MODEL, prompt="p", max_tokens=30)
            self.assertAlmostEqual(config["calls"][0]["cost_usd"], 0.000014)
            self.assertEqual(config["calls"][0]["cost_kind"], "estimate")
            with self.assertRaises(InferenceError):
                observed_call(Mock(side_effect=RuntimeError("secret")), "refinement", MODEL, prompt="p")
            self.assertEqual(config["calls"][-1]["status"], "error")
            self.assertNotIn("secret", json.dumps(config["calls"]))
        finally:
            CURRENT.reset(marker)

    def test_actual_acronym_pipeline_abc(self):
        from src.experiment import run_record
        from prompt_lib.backends.gemini_api import GeminiAPIWrapper
        feedback = "Total score: 20/25"
        for variant in "ABC":
            replies = ["Acronym: INIT"] if variant == "A" else (
                ["Acronym: INIT", feedback, "Title: title\nAcronym: NEXT", feedback] if variant == "B" else
                ["Acronym: INIT", feedback, feedback])
            def original(**kwargs):
                return {"model": kwargs["engine"], "choices": [{"text": replies.pop(0)}]}
            config = dict(variant=variant, original_model="gemini-1.5-flash", refinement_model=MODEL)
            with self.subTest(variant=variant), patch.object(GeminiAPIWrapper, "call", side_effect=original), \
                 patch("requests.post", return_value=response("Title: title\nAcronym: NEXT")) as post, \
                 patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real"}), \
                 patch("src.acronym.task_iterate.open", mock_open()), contextlib.redirect_stdout(io.StringIO()):
                record = run_record("acronym", {"title": "title"}, config, attempts=2)
            self.assertEqual(record["status"], "success", record)
            self.assertEqual([c["stage"] for c in record["calls"]], ["generation"] if variant == "A" else
                             ["generation", "feedback", "refinement", "feedback"])
            self.assertEqual(post.call_count, 1 if variant == "C" else 0)
            for call in record["calls"]:
                self.assertEqual(call["requested_model"], MODEL if variant == "C" and call["stage"] == "refinement" else "gemini-1.5-flash")

    def test_gsm_c_rejected_before_network(self):
        from src.experiment import run_record
        with patch("requests.post") as post, self.assertRaises(InferenceError):
            run_record("gsm", {"input": "question"}, {"variant": "C"})
        post.assert_not_called()

    def test_sentiment_router_hf(self):
        from prompt_lib.backends import router
        marker = CURRENT.set(dict(variant="C", original_model="gemini-1.5-flash", refinement_model=MODEL, calls=[]))
        try:
            with patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real"}), patch("requests.post", return_value=response()):
                result = router.call("p", "gemini-1.5-flash", stage="refinement", return_entire_response=True)
                self.assertEqual(router.get_first_response(result, "gemini-1.5-flash"), "refined")
        finally:
            CURRENT.reset(marker)

    def test_terminal_transcript_and_final_result(self):
        from src.experiment import run_record
        from prompt_lib.backends.gemini_api import GeminiAPIWrapper
        transcript = io.StringIO()
        replies = ["Acronym: FIRST", "Total score: 10/25", "Total score: 20/25"]
        def original(**kwargs):
            return {"model": kwargs["engine"], "choices": [{"text": replies.pop(0)}]}
        with patch.object(GeminiAPIWrapper, "call", side_effect=original), \
             patch("requests.post", return_value=response("Title: unchanged\nAcronym: FINAL")), \
             patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real"}), \
             patch("src.acronym.task_iterate.open", mock_open()), contextlib.redirect_stdout(transcript):
            record = run_record("acronym", {"title": "original question"},
                                dict(variant="C", original_model="gemini-1.5-flash", refinement_model=MODEL), attempts=2)
        text = transcript.getvalue()
        self.assertLess(text.index("ORIGINAL USER INPUT"), text.index("INITIAL GENERATION"))
        self.assertLess(text.index("INITIAL GENERATION"), text.index("REFINEMENT 1"))
        self.assertLess(text.index("REFINEMENT 1"), text.index("FINAL OUTPUT"))
        self.assertIn("original question", text)
        self.assertEqual(record["final_output"], "FINAL")

    def test_payment_failure_visible_and_not_retried(self):
        from src.experiment import run_record
        transcript = io.StringIO()
        with patch("requests.post", return_value=response(status=402)) as post, \
             patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real"}), contextlib.redirect_stdout(transcript):
            record = run_record("acronym", {"title": "input"}, dict(variant="A", original_model=MODEL))
        self.assertEqual(record["status"], "error")
        self.assertIsNone(record["final_output"])
        self.assertIn("payment required", record["error"])
        self.assertIn("EXPERIMENT FAILED", transcript.getvalue())
        self.assertNotIn("test-secret-not-real", json.dumps(record) + transcript.getvalue())
        post.assert_called_once()

    def test_cli_saves_terminal_final_to_selected_path(self):
        from src.experiment import main
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "results.jsonl"
            config = Path(folder) / "config.json"
            config.write_text(json.dumps({"variant": "A", "original_model": MODEL}))
            argv = ["experiment", "--config", str(config), "--task", "acronym", "--query", "my title", "--output", str(dest)]
            with patch.object(sys, "argv", argv), patch("requests.post", return_value=response("Acronym: SAVED")), \
                 patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real"}), contextlib.redirect_stdout(io.StringIO()) as terminal:
                main()
            saved = json.loads(dest.read_text())
            self.assertEqual(saved["final_output"], "SAVED")
            readable = dest.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("## Final answer\n\nSAVED", readable)
            self.assertNotIn("file_sha256", readable)
            self.assertNotIn("test-secret-not-real", readable)
            self.assertEqual(saved["input"], {"title": "my title"})
            self.assertIn("FINAL OUTPUT\nSAVED", terminal.getvalue())
            self.assertNotIn("test-secret-not-real", dest.read_text())
            with patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):
                main()

    def test_remaining_iterative_task_routes(self):
        from src.experiment import run_record
        from prompt_lib.backends.gemini_api import GeminiAPIWrapper
        cases = [
            ("pie", {"input": "def f(): return 1"}, ["def f(): return 1", "use a constant", "this code is not slow"], "def f(): return 2", 2),
            ("responsegen", {"context": "User: Hello"}, ["Response: Hello", "Scores: Total score: 10/20", "Scores: Total score: 20/20"], "Response: Welcome", 2),
            ("sentiment_reversal", {"review": "fine", "sentiment": "Neutral", "target_sentiment": "Very positive"},
             ["Very positive: Nice", "Very positive", "Feedback: Try again", "Very positive", "Feedback: Great"], "Very positive: Excellent", 1),
            ("readability", {"input": "x=1"}, ["rename x"] * 5, "value = 1", 4),
        ]
        for task, row, replies, refined, attempts in cases:
            queue = list(replies)
            def original(**kwargs):
                text = queue.pop(0)
                return {"model": kwargs["engine"], "choices": [{"text": text, "message": {"content": text}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
            with self.subTest(task=task), patch.object(GeminiAPIWrapper, "call", side_effect=original), \
                 patch("requests.post", return_value=response(refined)) as post, \
                 patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real"}), \
                 patch("src.responsegen.task_iterate.open", mock_open()), contextlib.redirect_stdout(io.StringIO()):
                record = run_record(task, row, dict(variant="C", original_model="gemini-1.5-flash", refinement_model=MODEL), attempts=attempts)
            self.assertEqual(record["status"], "success", record)
            self.assertTrue(record["final_output"])
            self.assertGreater(post.call_count, 0)
            for call in record["calls"]:
                self.assertEqual(call["requested_model"], MODEL if call["stage"] == "refinement" else "gemini-1.5-flash")
            self.assertEqual(queue, [])

    def test_gsm_original_combined_stage(self):
        from src.experiment import run_record
        from prompt_lib.backends.gemini_api import GeminiAPIWrapper
        queue = ["def solution(): return 1", "it is correct\ndef solution(): return 1"]
        def original(**kwargs):
            return {"model": kwargs["engine"], "choices": [{"text": queue.pop(0)}]}
        with patch.object(GeminiAPIWrapper, "call", side_effect=original), contextlib.redirect_stdout(io.StringIO()):
            record = run_record("gsm", {"input": "what is one?"}, dict(variant="B", original_model="gemini-1.5-flash"), attempts=2)
        self.assertEqual(record["status"], "success", record)
        self.assertEqual([c["stage"] for c in record["calls"]], ["generation", "feedback_refinement"])

    def test_router_does_not_duplicate_openai_call_metrics(self):
        from prompt_lib.backends import router
        from prompt_lib.backends.openai_api import ChatGPTAPIWrapper
        config = dict(variant="B", original_model="gpt-4", calls=[])
        marker = CURRENT.set(config)
        try:
            with patch.object(ChatGPTAPIWrapper, "call", return_value=dict(response().json(), model="gpt-4")):
                router.call("p", "gpt-4", stage="generation", max_tokens=10, stop_token=None, temperature=0)
            self.assertEqual(len(config["calls"]), 1)
            self.assertEqual(config["calls"][0]["stage"], "generation")
        finally:
            CURRENT.reset(marker)

    def test_commongen_with_existing_nlp_evaluation(self):
        from src.experiment import run_record
        from prompt_lib.backends.gemini_api import GeminiAPIWrapper
        queue = ["Sentence: A cat waits.", "Concept Feedback: dog\nCommonsense Feedback: dog",
                 "Concept Feedback: None\nCommonsense Feedback: None"]
        def original(**kwargs):
            return {"model": kwargs["engine"], "choices": [{"text": queue.pop(0)}]}
        with patch.object(GeminiAPIWrapper, "call", side_effect=original), \
             patch("requests.post", return_value=response("Sentence: A cat meets a dog.")) as post, \
             patch.dict(os.environ, {"HF_TOKEN": "test-secret-not-real"}), contextlib.redirect_stdout(io.StringIO()):
            record = run_record("commongen", {"concepts": ["cat", "dog"]},
                                dict(variant="C", original_model="gemini-1.5-flash", refinement_model=MODEL), attempts=3)
        self.assertEqual(record["status"], "success", record)
        self.assertEqual(record["final_output"], "A cat meets a dog.")
        self.assertEqual(len(record["result"]), 2)  # Existing early stop is preserved.
        self.assertEqual([c["stage"] for c in record["calls"]], ["generation", "feedback", "refinement", "feedback"])
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
