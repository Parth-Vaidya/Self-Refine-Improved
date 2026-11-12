import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.chat_pipeline import ChatResponsePipeline
from src.evaluator import (
    CONDITIONS,
    run_single_evaluation,
    run_evaluations,
)
from src.eval_report import generate_evaluation_report


class Phase4EvaluatorTests(unittest.TestCase):
    def test_run_single_evaluation_records_telemetry_and_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")

            pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=1, profile_path=profile_path)
            prompt_item = {"id": "test_01", "category": "Programming", "query": "Write hello world in Python"}

            # Mock pipeline call that also records observed call usage
            mock_output = {
                "model": "groq:qwen/qwen3.8-27b",
                "choices": [{"message": {"content": "print('hello world')"}}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 5, "total_tokens": 20},
            }

            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", return_value=mock_output):
                record = run_single_evaluation(prompt_item, "A", pipeline)

            self.assertEqual(record["prompt_id"], "test_01")
            self.assertEqual(record["condition_key"], "A")
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["response"], "print('hello world')")
            self.assertGreaterEqual(record["telemetry"]["api_call_count"], 1)
            self.assertGreater(record["telemetry"]["latency_seconds"], 0.0)
            self.assertGreater(record["telemetry"]["total_tokens"], 0)

    def test_run_single_evaluation_self_refine_with_refinement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")

            pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2, profile_path=profile_path)
            prompt_item = {"id": "test_02", "category": "Programming", "query": "Solve quadratic equation"}

            mock_responses = [
                {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "x = (-b +- sqrt(d))/2a"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}},
                {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "Critique Summary: Define d.\nTotal score: 6/10"}}], "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}},
                {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "Where d = b^2 - 4ac, x = (-b +- sqrt(d))/2a"}}], "usage": {"prompt_tokens": 25, "completion_tokens": 15, "total_tokens": 40}},
            ]

            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", side_effect=mock_responses):
                record = run_single_evaluation(prompt_item, "B", pipeline)

            self.assertEqual(record["condition_key"], "B")
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["telemetry"]["api_call_count"], 3)
            self.assertEqual(record["telemetry"]["total_tokens"], 90)
            stages = [call["stage"] for call in record["telemetry"]["calls"]]
            self.assertEqual(stages, ["generation", "feedback", "refinement"])

    def test_run_single_evaluation_self_refine_early_stopping_on_high_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")

            pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2, profile_path=profile_path)
            prompt_item = {"id": "test_03", "category": "Programming", "query": "Write palindrome checker"}

            mock_responses = [
                {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "cleaned == cleaned[::-1]"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}},
                {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "Critique Summary: None\nTotal score: 10/10"}}], "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}},
            ]

            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", side_effect=mock_responses):
                record = run_single_evaluation(prompt_item, "B", pipeline)

            self.assertEqual(record["condition_key"], "B")
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["telemetry"]["api_call_count"], 2)
            self.assertEqual(record["telemetry"]["total_tokens"], 50)
            stages = [call["stage"] for call in record["telemetry"]["calls"]]
            self.assertEqual(stages, ["generation", "feedback"])

    def test_run_evaluations_writes_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_path = Path(tmpdir) / "prompts.json"
            prompts = [{"id": "p1", "category": "Reasoning", "query": "Why is the sky blue?"}]
            prompts_path.write_text(json.dumps(prompts), encoding="utf-8")

            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(json.dumps({
                "preferences": {
                    "prefers_step_by_step": {"description": "Step by step", "enabled": True}
                }
            }), encoding="utf-8")

            output_jsonl = Path(tmpdir) / "results.jsonl"

            mock_output = {
                "model": "groq:qwen/qwen3.8-27b",
                "choices": [{"message": {"content": "Rayleigh scattering"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            }

            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", return_value=mock_output):
                results = run_evaluations(
                    prompts_path=prompts_path,
                    profile_path=profile_path,
                    output_path=output_jsonl,
                    conditions=["A", "C"],
                    limit_prompts=1,
                )

            self.assertEqual(len(results), 2)
            self.assertTrue(output_jsonl.exists())
            lines = [json.loads(l) for l in output_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["condition_key"], "A")
            self.assertEqual(lines[1]["condition_key"], "C")
            self.assertFalse(lines[0]["personalization_enabled"])
            self.assertTrue(lines[1]["personalization_enabled"])

    def test_run_evaluations_resume_skips_completed_combinations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_path = Path(tmpdir) / "prompts.json"
            prompts = [
                {"id": "p1", "category": "Programming", "query": "Q1"},
                {"id": "p2", "category": "Reasoning", "query": "Q2"},
            ]
            prompts_path.write_text(json.dumps(prompts), encoding="utf-8")
            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")
            output_jsonl = Path(tmpdir) / "results.jsonl"

            mock_output = {
                "model": "groq:qwen/qwen3.8-27b",
                "choices": [{"message": {"content": "Answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

            # 1. First run: evaluate only condition A for prompt p1
            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", return_value=mock_output) as mock_call:
                run_evaluations(
                    prompts_path=prompts_path,
                    profile_path=profile_path,
                    output_path=output_jsonl,
                    conditions=["A"],
                    limit_prompts=1,
                    resume=True,
                )
                self.assertEqual(mock_call.call_count, 1)

            # Check that p1/A is saved
            lines_first = [json.loads(l) for l in output_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines_first), 1)
            self.assertEqual(lines_first[0]["prompt_id"], "p1")
            self.assertEqual(lines_first[0]["condition_key"], "A")

            # 2. Second run: resume for conditions A and B across both prompts (limit 2)
            # p1/A is already completed, so only p1/B, p2/A, p2/B are executed (3 evaluations).
            # Each Self-Refine evaluation (Condition B) performs 3 model calls (generation, feedback, refinement).
            # Each Standard evaluation (Condition A) performs 1 model call (generation).
            # Total expected model API calls = 3 (p1/B) + 1 (p2/A) + 3 (p2/B) = 7 calls.
            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", return_value=mock_output) as mock_call2:
                all_results = run_evaluations(
                    prompts_path=prompts_path,
                    profile_path=profile_path,
                    output_path=output_jsonl,
                    conditions=["A", "B"],
                    limit_prompts=2,
                    resume=True,
                )
                # Exactly 7 model calls: 3 for p1/B, 1 for p2/A, 3 for p2/B (p1/A skipped)
                self.assertEqual(mock_call2.call_count, 7)

            # Total records should now be 4: p1/A, p1/B, p2/A, p2/B
            lines_second = [json.loads(l) for l in output_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines_second), 4)
            pairs = [(r["prompt_id"], r["condition_key"]) for r in lines_second]
            self.assertEqual(pairs, [("p1", "A"), ("p1", "B"), ("p2", "A"), ("p2", "B")])
            self.assertEqual(len(all_results), 4)

    def test_run_evaluations_filter_by_prompt_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_path = Path(tmpdir) / "prompts.json"
            profile_path = Path(tmpdir) / "profile.json"
            output_jsonl = Path(tmpdir) / "output.jsonl"

            prompts_path.write_text(
                json.dumps([
                    {"id": "p1", "category": "Programming", "query": "Q1"},
                    {"id": "p2", "category": "Programming", "query": "Q2"},
                    {"id": "p3", "category": "Reasoning", "query": "Q3"},
                ]),
                encoding="utf-8",
            )
            profile_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")

            mock_output = {
                "model": "groq:qwen/qwen3.8-27b",
                "choices": [{"message": {"content": "Sample output"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", return_value=mock_output) as mock_call:
                results = run_evaluations(
                    prompts_path=prompts_path,
                    profile_path=profile_path,
                    output_path=output_jsonl,
                    conditions=["A"],
                    prompt_ids=["p2"],
                    resume=False,
                )
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["prompt_id"], "p2")
                self.assertEqual(results[0]["condition_key"], "A")
                self.assertEqual(mock_call.call_count, 1)

    def test_generate_evaluation_report_from_mock_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results_jsonl = Path(tmpdir) / "results.jsonl"
            report_md = Path(tmpdir) / "report.md"

            sample_data = [
                {
                    "prompt_id": "p1",
                    "condition_key": "A",
                    "status": "success",
                    "query": "Q1",
                    "response": "Answer A",
                    "telemetry": {"latency_seconds": 1.2, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "api_call_count": 1},
                },
                {
                    "prompt_id": "p1",
                    "condition_key": "B",
                    "status": "success",
                    "query": "Q1",
                    "response": "Answer B",
                    "telemetry": {"latency_seconds": 3.6, "prompt_tokens": 300, "completion_tokens": 150, "total_tokens": 450, "api_call_count": 3},
                },
            ]
            with results_jsonl.open("w", encoding="utf-8") as f:
                for d in sample_data:
                    f.write(json.dumps(d) + "\n")

            report_text = generate_evaluation_report(results_jsonl, report_md)
            self.assertTrue(report_md.exists())
            self.assertIn("Comparative Evaluation", report_text)
            self.assertIn("Latency Multiplier", report_text)
            self.assertIn("150.0", report_text)
            self.assertIn("450.0", report_text)

    def test_run_evaluations_resume_cleans_prior_failed_records_and_replaces_them(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_path = Path(tmpdir) / "prompts.json"
            prompts_path.write_text(
                json.dumps([
                    {"id": "p1", "category": "Programming", "query": "Q1"},
                    {"id": "p2", "category": "Programming", "query": "Q2"},
                ]),
                encoding="utf-8",
            )
            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")
            output_jsonl = Path(tmpdir) / "output.jsonl"

            # Pre-populate with 1 success (p1/A) and 1 error (p2/A)
            initial_records = [
                {"prompt_id": "p1", "condition_key": "A", "status": "success", "response": "OK", "telemetry": {}},
                {"prompt_id": "p2", "condition_key": "A", "status": "error", "error": "Rate limit", "telemetry": {}},
            ]
            with output_jsonl.open("w", encoding="utf-8") as f:
                for r in initial_records:
                    f.write(json.dumps(r) + "\n")

            mock_output = {
                "model": "groq:qwen/qwen3.8-27b",
                "choices": [{"message": {"content": "Recovered response"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", return_value=mock_output) as mock_call:
                results = run_evaluations(
                    prompts_path=prompts_path,
                    profile_path=profile_path,
                    output_path=output_jsonl,
                    conditions=["A"],
                    resume=True,
                )

            # p1/A was already success, so it was preserved.
            # p2/A had failed previously, so it was pruned and re-evaluated successfully.
            # Total records should be exactly 2, zero errors, zero duplicates.
            lines = [json.loads(l) for l in output_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["prompt_id"], "p1")
            self.assertEqual(lines[0]["status"], "success")
            self.assertEqual(lines[1]["prompt_id"], "p2")
            self.assertEqual(lines[1]["status"], "success")
            self.assertEqual(lines[1]["response"], "Recovered response")
            self.assertEqual(mock_call.call_count, 1)

    def test_run_evaluations_stop_on_error_halts_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_path = Path(tmpdir) / "prompts.json"
            prompts_path.write_text(
                json.dumps([{"id": "p1", "category": "Programming", "query": "Q1"}]),
                encoding="utf-8",
            )
            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")
            output_jsonl = Path(tmpdir) / "output.jsonl"

            with patch("prompt_lib.backends.groq_api.GroqAPIWrapper.call", side_effect=Exception("API failure")):
                with self.assertRaises(SystemExit):
                    run_evaluations(
                        prompts_path=prompts_path,
                        profile_path=profile_path,
                        output_path=output_jsonl,
                        conditions=["A"],
                        resume=True,
                        stop_on_error=True,
                    )

            # Output file should not contain the failed record
            if output_jsonl.exists():
                lines = [json.loads(l) for l in output_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
                self.assertEqual(len(lines), 0)


if __name__ == "__main__":
    unittest.main()

