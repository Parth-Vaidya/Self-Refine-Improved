import io
import contextlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.chat_pipeline import (
    ChatResponsePipeline,
    load_personalization_instruction,
    parse_chat_feedback,
)
from prompt_lib.backends.huggingface_api import InferenceError


class ChatPipelineTests(unittest.TestCase):
    def test_parse_chat_feedback_with_valid_score(self):
        text = "Relevance is good.\nCritique Summary: Add more detail.\nTotal score: 8/10"
        critique, score = parse_chat_feedback(text)
        self.assertEqual(score, 8)
        self.assertIn("Add more detail", critique)

    def test_parse_chat_feedback_with_alternative_scale(self):
        text = "Total score: 4/5\nCritique Summary: Good job."
        _, score = parse_chat_feedback(text)
        self.assertEqual(score, 8)

    def test_parse_chat_feedback_malformed_graceful_fallback(self):
        text = "The response is fine, no specific numerical score given."
        critique, score = parse_chat_feedback(text)
        self.assertEqual(score, 7)
        self.assertIn("The response is fine", critique)

    def test_generate_initial_message(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=1)
        with patch.object(pipeline, "_call_model", return_value="Hello! How can I help you today?"):
            resp = pipeline.generate_chat_response("User: Hi there!")
        self.assertEqual(resp, "Hello! How can I help you today?")

    def test_multiturn_context_passed_to_pipeline(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=1)
        calls = []

        def fake_call(prompt, stage, **kwargs):
            calls.append((prompt, stage))
            return "Sure, here are examples."

        with patch.object(pipeline, "_call_model", side_effect=fake_call):
            context = "User: Explain Newton's laws.\nAssistant: Newton's first law is inertia.\nUser: Give examples."
            resp = pipeline.generate_chat_response(context)

        self.assertEqual(resp, "Sure, here are examples.")
        self.assertEqual(len(calls), 1)
        self.assertIn("Newton's first law is inertia", calls[0][0])
        self.assertIn("User: Give examples.", calls[0][0])

    def test_successful_refinement_cycle(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2)
        outputs = [
            "Draft answer without formula.",
            "Critique Summary: Include the formula.\nTotal score: 6/10",
            "Refined answer including F = ma.",
        ]
        with patch.object(pipeline, "_call_model", side_effect=outputs):
            final_resp = pipeline.generate_chat_response("User: What is Newton's second law?")

        self.assertEqual(final_resp, "Refined answer including F = ma.")

    def test_early_stopping_on_high_score_skips_refinement(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2)
        outputs = [
            "Optimal initial palindrome checker.",
            "Critique Summary: None\nTotal score: 10/10",
        ]
        calls = []

        def call_side_effect(prompt, stage, **kwargs):
            calls.append(stage)
            return outputs.pop(0)

        with patch.object(pipeline, "_call_model", side_effect=call_side_effect):
            resp = pipeline.generate_chat_response("User: Write a palindrome checker in Python")

        self.assertEqual(resp, "Optimal initial palindrome checker.")
        # Only generation and feedback are called; refinement is skipped due to high score
        self.assertEqual(calls, ["generation", "feedback"])

    def test_failed_refinement_preserves_initial_response(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2)
        outputs = [
            "Valid initial answer.",
            InferenceError("Groq rate limit exceeded.", status_code=429),
        ]

        def call_side_effect(prompt, stage, **kwargs):
            item = outputs.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch.object(pipeline, "_call_model", side_effect=call_side_effect):
            resp = pipeline.generate_chat_response("User: Question")

        self.assertEqual(resp, "Valid initial answer.")

    def test_malformed_feedback_does_not_crash_and_uses_initial_or_refined(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2)
        outputs = [
            "Initial answer.",
            "This is feedback without any score label at all.",
            "Refined answer addressing informal feedback.",
        ]
        with patch.object(pipeline, "_call_model", side_effect=outputs):
            resp = pipeline.generate_chat_response("User: Help me write an essay.")

        self.assertEqual(resp, "Refined answer addressing informal feedback.")

    def test_initial_generation_failure_raises(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2)
        with patch.object(pipeline, "_call_model", side_effect=InferenceError("Rate limit", status_code=429)):
            with self.assertRaises(InferenceError):
                pipeline.generate_chat_response("User: Hello")

    def test_call_model_passes_stop_token_positional_to_openai_api_wrapper(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=1)
        mock_output = {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "Test response"}}]}
        with patch("prompt_lib.backends.openai_api.OpenaiAPIWrapper.call", return_value=mock_output) as mock_call:
            res = pipeline.generate_initial("User: Hello")

        self.assertEqual(res, "Test response")
        mock_call.assert_called_once()
        kwargs = mock_call.call_args.kwargs
        self.assertIn("stop_token", kwargs)
        self.assertIsNone(kwargs["stop_token"])
        self.assertEqual(kwargs["stage"], "generation")
        self.assertEqual(kwargs["engine"], "groq:qwen/qwen3.8-27b")

    def test_feedback_and_refine_pass_stop_token(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2)
        mock_output = {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "Critique\nTotal score: 8/10"}}]}
        with patch("prompt_lib.backends.openai_api.OpenaiAPIWrapper.call", return_value=mock_output) as mock_call:
            feedback, score = pipeline.get_feedback("User: Hi", "Draft")

        self.assertEqual(score, 8)
        self.assertIn("stop_token", mock_call.call_args.kwargs)
        self.assertIsNone(mock_call.call_args.kwargs["stop_token"])
        self.assertEqual(mock_call.call_args.kwargs["stage"], "feedback")

        mock_refine_output = {"model": "groq:qwen/qwen3.8-27b", "choices": [{"message": {"content": "Refined response"}}]}
        with patch("prompt_lib.backends.openai_api.OpenaiAPIWrapper.call", return_value=mock_refine_output) as mock_call2:
            refined = pipeline.refine("User: Hi", "Draft", "Add detail")

        self.assertEqual(refined, "Refined response")
        self.assertIn("stop_token", mock_call2.call_args.kwargs)
        self.assertIsNone(mock_call2.call_args.kwargs["stop_token"])
        self.assertEqual(mock_call2.call_args.kwargs["stage"], "refinement")

    def test_standard_mode_performs_only_initial_generation(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=3)
        calls = []

        def fake_call(prompt, stage, **kwargs):
            calls.append(stage)
            return "Standard response"

        with patch.object(pipeline, "_call_model", side_effect=fake_call):
            resp = pipeline.generate_chat_response("User: Quick question", mode="standard")

        self.assertEqual(resp, "Standard response")
        # Ensure ONLY 'generation' was invoked; never 'feedback' or 'refinement'
        self.assertEqual(calls, ["generation"])

    def test_self_refine_mode_invokes_complete_pipeline(self):
        pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2)
        calls = []

        def fake_call(prompt, stage, **kwargs):
            calls.append(stage)
            if stage == "generation":
                return "Draft"
            elif stage == "feedback":
                return "Critique\nTotal score: 5/10"
            elif stage == "refinement":
                return "Refined Draft"
            return "Unknown"

        with patch.object(pipeline, "_call_model", side_effect=fake_call):
            resp = pipeline.generate_chat_response("User: Complex question", mode="self_refine")

        self.assertEqual(resp, "Refined Draft")
        self.assertEqual(calls, ["generation", "feedback", "refinement"])

    def test_load_personalization_instruction_enabled_and_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "user_profile.json"

            # 1. Profile with enabled and disabled preferences
            profile_data = {
                "preferences": {
                    "prefers_step_by_step": {
                        "description": "Prefers step-by-step explanations",
                        "enabled": True,
                    },
                    "prefers_concise_answers": {
                        "description": "Prefers short, concise answers",
                        "enabled": False,
                    },
                    "prefers_examples": {
                        "description": "Prefers practical examples and demonstrations",
                        "enabled": True,
                    },
                }
            }
            profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

            instruction = load_personalization_instruction(profile_path)
            self.assertIsNotNone(instruction)
            self.assertIn("Prefers step-by-step explanations", instruction)
            self.assertIn("Prefers practical examples and demonstrations", instruction)
            self.assertNotIn("Prefers short, concise answers", instruction)

    def test_load_personalization_instruction_missing_and_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "non_existent.json"
            self.assertIsNone(load_personalization_instruction(missing_path))

            invalid_path = Path(tmpdir) / "invalid.json"
            invalid_path.write_text("{ corrupt json ...", encoding="utf-8")
            self.assertIsNone(load_personalization_instruction(invalid_path))

            empty_path = Path(tmpdir) / "empty.json"
            empty_path.write_text(json.dumps({"preferences": {}}), encoding="utf-8")
            self.assertIsNone(load_personalization_instruction(empty_path))

    def test_standard_mode_with_personalization_instruction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "user_profile.json"
            profile_data = {
                "preferences": {
                    "prefers_step_by_step": {
                        "description": "Prefers step-by-step explanations",
                        "enabled": True,
                    }
                }
            }
            profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

            pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=1, profile_path=profile_path)
            captured_prompts = []

            def fake_call(prompt, stage, **kwargs):
                captured_prompts.append((prompt, stage))
                return "Personalized answer"

            with patch.object(pipeline, "_call_model", side_effect=fake_call):
                resp = pipeline.generate_chat_response("User: Solve x^2 = 4", mode="standard")

            self.assertEqual(resp, "Personalized answer")
            self.assertEqual(len(captured_prompts), 1)
            self.assertEqual(captured_prompts[0][1], "generation")
            self.assertIn("Prefers step-by-step explanations", captured_prompts[0][0])

    def test_self_refine_mode_with_personalization_instruction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "user_profile.json"
            profile_data = {
                "preferences": {
                    "prefers_simple_code": {
                        "description": "Prefers simple and clean code implementations",
                        "enabled": True,
                    }
                }
            }
            profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

            pipeline = ChatResponsePipeline(engine="groq:qwen/qwen3.8-27b", max_attempts=2, profile_path=profile_path)
            captured_calls = []

            def fake_call(prompt, stage, **kwargs):
                captured_calls.append((prompt, stage))
                if stage == "generation":
                    return "Draft code"
                elif stage == "feedback":
                    return "Critique Summary: Simplify code.\nTotal score: 6/10"
                elif stage == "refinement":
                    return "Refined simple code"
                return ""

            with patch.object(pipeline, "_call_model", side_effect=fake_call):
                resp = pipeline.generate_chat_response("User: How to sort a list?", mode="self_refine")

            self.assertEqual(resp, "Refined simple code")
            self.assertEqual(len(captured_calls), 3)

            # 1. Generation contains personalization
            self.assertIn("Prefers simple and clean code implementations", captured_calls[0][0])
            # 2. Feedback prompt contains personalization criteria
            self.assertIn("Adherence to user preferences", captured_calls[1][0])
            self.assertIn("Prefers simple and clean code implementations", captured_calls[1][0])
            # 3. Refinement prompt contains personalization context
            self.assertIn("Prefers simple and clean code implementations", captured_calls[2][0])


if __name__ == "__main__":
    unittest.main()

