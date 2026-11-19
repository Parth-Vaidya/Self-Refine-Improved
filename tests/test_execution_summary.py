"""Unit tests for Self-Refine execution summary and preference provenance."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.summary import (
    clean_preference_name,
    format_execution_summary,
    format_quality_score,
    get_summary_metadata,
    resolve_preference_sources,
)
from src.chat_pipeline import ChatResponsePipeline
from src.experiment import run_record
from src.report import render_record


class ExecutionSummaryFormattingTests(unittest.TestCase):
    def test_exact_example_formatting(self):
        line = format_execution_summary(
            score=9,
            max_score=10,
            loops=1,
            preference_sources="Previous Chats",
            applied_preferences=["Simple language", "prefers_step_by_step", "prefers_examples"],
            applied=True,
        )
        expected = (
            "[SELF-REFINE SUMMARY] Quality: 9/10 (90%) | Loops: 1 | "
            "Preference Source: Previous Chats | "
            "Preferences: Simple language, Step-by-step explanations, Practical examples | "
            "Applied: Yes"
        )
        self.assertEqual(line, expected)

    def test_quality_score_scales(self):
        self.assertEqual(format_quality_score(9, 10), "Quality: 9/10 (90%)")
        self.assertEqual(format_quality_score(28, 30), "Quality: 28/30 (93%)")
        self.assertEqual(format_quality_score(20, 25), "Quality: 20/25 (80%)")
        self.assertEqual(format_quality_score(None, 10), "Quality: N/A")
        self.assertEqual(format_quality_score(5, None), "Quality: N/A")
        self.assertEqual(format_quality_score(-1, 10), "Quality: N/A")
        self.assertEqual(format_quality_score(5, 0), "Quality: N/A")

    def test_no_personalization_formatting(self):
        line = format_execution_summary(
            score=28,
            max_score=30,
            loops=1,
            preference_sources=None,
            applied_preferences=None,
            applied=False,
        )
        expected = (
            "[SELF-REFINE SUMMARY] Quality: 28/30 (93%) | Loops: 1 | "
            "Preference Source: None | Preferences: None | Applied: No"
        )
        self.assertEqual(line, expected)

    def test_single_pass_standard_formatting(self):
        line = format_execution_summary(
            score=None,
            max_score=None,
            loops=0,
            preference_sources=None,
            applied_preferences=None,
            applied=False,
        )
        expected = (
            "[SELF-REFINE SUMMARY] Quality: N/A | Loops: 0 | "
            "Preference Source: None | Preferences: None | Applied: No"
        )
        self.assertEqual(line, expected)

    def test_combined_preference_sources_formatting(self):
        line = format_execution_summary(
            score=8,
            max_score=10,
            loops=2,
            preference_sources=["Current Query", "Previous Chats"],
            applied_preferences=["prefers_step_by_step", "prefers_examples"],
            applied=True,
        )
        expected = (
            "[SELF-REFINE SUMMARY] Quality: 8/10 (80%) | Loops: 2 | "
            "Preference Source: Current Query + Previous Chats | "
            "Preferences: Step-by-step explanations, Practical examples | "
            "Applied: Yes"
        )
        self.assertEqual(line, expected)

    def test_clean_preference_names(self):
        self.assertEqual(clean_preference_name("prefers_step_by_step"), "Step-by-step explanations")
        self.assertEqual(clean_preference_name("prefers_concise_answers"), "Concise answers")
        self.assertEqual(clean_preference_name("prefers_simple_code"), "Simple code")
        self.assertEqual(clean_preference_name("prefers_examples"), "Practical examples")
        self.assertEqual(clean_preference_name("Prefers step-by-step explanations"), "Step-by-step explanations")
        self.assertEqual(clean_preference_name("Prefers short, concise answers"), "Concise answers")
        self.assertEqual(clean_preference_name("Prefers simple and clean code implementations"), "Simple code")
        self.assertEqual(clean_preference_name("Prefers practical examples and demonstrations"), "Practical examples")
        self.assertEqual(clean_preference_name("Simple language"), "Simple language")

    def test_preferences_deduplication(self):
        meta = get_summary_metadata(
            score=9,
            max_score=10,
            loops=1,
            preference_sources="User Profile",
            applied_preferences=[
                "prefers_step_by_step",
                "Prefers step-by-step explanations",
                "prefers_examples",
                "Practical examples",
            ],
            applied=True,
        )
        self.assertEqual(meta["preferences"], ["Step-by-step explanations", "Practical examples"])
        self.assertEqual(meta["preferences_display"], "Step-by-step explanations, Practical examples")


class PreferenceProvenanceTests(unittest.TestCase):
    def test_source_from_current_query_only(self):
        query = "Can you please break it down step-by-step and provide simple code?"
        sources, cleaned = resolve_preference_sources(
            applied_preferences=["prefers_step_by_step", "prefers_simple_code"],
            query_text=query,
            chats_dir="non_existent_chats_dir",
            profile_data={"preferences": {}},
        )
        self.assertEqual(sources, ["Current Query"])
        self.assertIn("Step-by-step explanations", cleaned)
        self.assertIn("Simple code", cleaned)

    def test_source_from_previous_chats_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            chats_dir = Path(temp_dir) / "chats"
            chats_dir.mkdir()
            chat_file = chats_dir / "chat_001.txt"
            chat_file.write_text(
                "User: Please walk me through this step-by-step.\nAssistant: Sure!\n",
                encoding="utf-8",
            )

            sources, cleaned = resolve_preference_sources(
                applied_preferences=["prefers_step_by_step"],
                query_text="Explain recursion.",
                chats_dir=chats_dir,
                profile_data={"preferences": {"prefers_step_by_step": {"enabled": True}}},
            )
            # Must attribute to Previous Chats because it originated in chat history
            self.assertEqual(sources, ["Previous Chats"])
            self.assertEqual(cleaned, ["Step-by-step explanations"])

    def test_source_from_user_profile_only(self):
        # Configured in user profile without being present in query or previous chats
        with tempfile.TemporaryDirectory() as temp_dir:
            chats_dir = Path(temp_dir) / "chats"
            chats_dir.mkdir()
            profile = {
                "preferences": {
                    "prefers_concise_answers": {
                        "description": "Prefers short, concise answers",
                        "enabled": True,
                    }
                }
            }
            sources, cleaned = resolve_preference_sources(
                applied_preferences=["prefers_concise_answers"],
                query_text="What is the capital of France?",
                chats_dir=chats_dir,
                profile_data=profile,
            )
            self.assertEqual(sources, ["User Profile"])
            self.assertEqual(cleaned, ["Concise answers"])

    def test_combined_query_and_previous_chats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            chats_dir = Path(temp_dir) / "chats"
            chats_dir.mkdir()
            (chats_dir / "chat_001.txt").write_text(
                "User: Always give me practical examples please.\n", encoding="utf-8"
            )

            query = "Walk me through this step-by-step."
            sources, cleaned = resolve_preference_sources(
                applied_preferences=["prefers_step_by_step", "prefers_examples"],
                query_text=query,
                chats_dir=chats_dir,
                profile_data={"preferences": {"prefers_examples": {"enabled": True}}},
            )
            self.assertEqual(sources, ["Current Query", "Previous Chats"])
            self.assertEqual(cleaned, ["Step-by-step explanations", "Practical examples"])

    def test_combined_profile_and_previous_chats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            chats_dir = Path(temp_dir) / "chats"
            chats_dir.mkdir()
            (chats_dir / "chat_001.txt").write_text(
                "User: Break it down step-by-step.\n", encoding="utf-8"
            )

            profile = {
                "preferences": {
                    "prefers_step_by_step": {"enabled": True},
                    "prefers_simple_code": {"enabled": True},  # profile only
                }
            }
            sources, cleaned = resolve_preference_sources(
                applied_preferences=["prefers_step_by_step", "prefers_simple_code"],
                query_text="Explain bubble sort.",
                chats_dir=chats_dir,
                profile_data=profile,
            )
            self.assertEqual(sources, ["User Profile", "Previous Chats"])
            self.assertEqual(cleaned, ["Step-by-step explanations", "Simple code"])

    def test_detected_in_query_but_not_applied(self):
        # Query contains preference wording, but personalization is disabled (applied=False)
        line = format_execution_summary(
            score=25,
            max_score=30,
            loops=1,
            preference_sources=None,
            applied_preferences=None,
            applied=False,
        )
        self.assertIn("Preference Source: None", line)
        self.assertIn("Preferences: None", line)
        self.assertIn("Applied: No", line)


class ChatPipelineSummaryIntegrationTests(unittest.TestCase):
    def test_pipeline_standard_mode_summary(self):
        pipeline = ChatResponsePipeline(engine="groq:test", max_attempts=1)
        with patch.object(pipeline, "_call_model", return_value="Standard answer."):
            resp = pipeline.generate_chat_response("Explain momentum.", mode="standard")
        self.assertEqual(resp, "Standard answer.")
        self.assertTrue(hasattr(pipeline, "last_execution_summary"))
        self.assertIn("[SELF-REFINE SUMMARY]", pipeline.last_execution_summary)
        self.assertIn("Quality: N/A", pipeline.last_execution_summary)
        self.assertIn("Loops: 0", pipeline.last_execution_summary)

    def test_pipeline_self_refine_mode_summary(self):
        pipeline = ChatResponsePipeline(engine="groq:test", max_attempts=2)
        responses = [
            "Initial answer.",
            "Relevance is good.\nCritique Summary: Add more details.\nTotal score: 9/10",
        ]
        with patch.object(pipeline, "_call_model", side_effect=responses):
            resp = pipeline.generate_chat_response("Explain momentum.", mode="self_refine")
        self.assertEqual(resp, "Initial answer.")
        self.assertIn("Quality: 9/10 (90%)", pipeline.last_execution_summary)
        self.assertIn("Loops: 0", pipeline.last_execution_summary)  # Stopped early on score >= 9

    def test_pipeline_with_personalization_profile(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({
                "preferences": {
                    "prefers_step_by_step": {
                        "description": "Prefers step-by-step explanations",
                        "enabled": True,
                    }
                }
            }, f)
            temp_profile = f.name

        pipeline = ChatResponsePipeline(engine="groq:test", max_attempts=2, profile_path=temp_profile)
        responses = [
            "Initial step-by-step draft.",
            "Critique Summary: Improve clarity.\nTotal score: 7/10",
            "Refined step-by-step answer.",
        ]
        with patch.object(pipeline, "_call_model", side_effect=responses):
            resp = pipeline.generate_chat_response("Explain energy.", mode="self_refine")
        self.assertEqual(resp, "Refined step-by-step answer.")
        self.assertIn("Quality: 7/10 (70%)", pipeline.last_execution_summary)
        self.assertIn("Loops: 1", pipeline.last_execution_summary)
        self.assertIn("Applied: Yes", pipeline.last_execution_summary)
        self.assertIn("Step-by-step explanations", pipeline.last_execution_summary)
        Path(temp_profile).unlink(missing_ok=True)


class ExperimentRunnerSummaryIntegrationTests(unittest.TestCase):
    def test_experiment_prints_and_records_summary(self):
        from prompt_lib.backends.groq_api import GroqAPIWrapper

        replies = [
            "Response: Newton's second law is F=ma.",
            "Scores:\n* Relevant: 3\n* Total score: 27/30",
            "Response: Newton's second law states that Force = mass * acceleration.",
            "Scores:\n* Relevant: 3\n* Total score: 30/30",
        ]

        def fake_call(**kwargs):
            item = replies.pop(0)
            return {
                "model": kwargs.get("engine", "test"),
                "choices": [{"text": item, "message": {"content": item}}],
                "usage": {"total_tokens": 100},
            }

        out = io.StringIO()
        with patch.object(GroqAPIWrapper, "call", side_effect=fake_call), contextlib.redirect_stdout(out):
            record = run_record(
                "responsegen",
                {"context": "Explain Newton's second law."},
                {"variant": "B", "original_model": "groq:test"},
                attempts=2,
            )

        self.assertIn("execution_summary", record)
        self.assertIn("summary_text", record)
        self.assertIn("[SELF-REFINE SUMMARY]", record["summary_text"])
        self.assertIn("Quality: 30/30 (100%)", record["summary_text"])
        self.assertIn("Loops: 1", record["summary_text"])
        self.assertIn("Applied: No", record["summary_text"])

        # Check markdown report rendering
        rendered = render_record(record)
        self.assertIn("## Execution summary", rendered)
        self.assertIn(record["summary_text"], rendered)


if __name__ == "__main__":
    unittest.main()
