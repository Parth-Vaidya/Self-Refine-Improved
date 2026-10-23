"""Groq never sleeps or retries, even with old timer settings present."""
import os
import unittest
from unittest.mock import patch, Mock
from prompt_lib.backends.groq_api import GroqAPIWrapper
from prompt_lib.backends.huggingface_api import InferenceError

class NoWaitTests(unittest.TestCase):
    def setUp(self):
        settings = patch.dict(os.environ, {"GROQ_RESUME_ON_RATE_LIMIT":"false"})
        settings.start()
        self.addCleanup(settings.stop)

    def test_rate_limit_fails_immediately_without_retry(self):
        response = Mock(status_code=429, headers={"Retry-After":"180"})
        with patch.dict(os.environ, {"GROQ_API_KEY":"test-secret", "GROQ_MIN_INTERVAL_SECONDS":"65", "GROQ_MAX_RETRIES":"5"}), patch("requests.post", return_value=response) as post, patch("prompt_lib.backends.request_budget.reserve") as reserve, patch("time.sleep") as sleep:
            with self.assertRaises(InferenceError):
                GroqAPIWrapper.call("question", engine="groq:test")
            post.assert_called_once()
            reserve.assert_called_once()
            sleep.assert_not_called()

    def test_success_ignores_old_timer_settings(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices":[{"message":{"content":"answer"}}]}
        with patch.dict(os.environ, {"GROQ_API_KEY":"test-secret", "GROQ_MIN_INTERVAL_SECONDS":"65"}), patch("requests.post", return_value=response), patch("prompt_lib.backends.request_budget.reserve"), patch("time.sleep") as sleep:
            result = GroqAPIWrapper.call("question", engine="groq:test")
            self.assertEqual(result["inference"]["max_retries"], 0)
            sleep.assert_not_called()

class ResumeTests(unittest.TestCase):
    def test_rate_limit_resumes_same_stage_with_same_payload(self):
        limited = Mock(status_code=429, headers={"Retry-After":"10"})
        good = Mock(status_code=200)
        good.json.return_value = {"choices":[{"message":{"content":"Refinement 2"}}]}
        with patch.dict(os.environ, {"GROQ_API_KEY":"test-secret", "GROQ_RESUME_ON_RATE_LIMIT":"true"}), patch("requests.post", side_effect=[limited,good]) as post, patch("prompt_lib.backends.request_budget.reserve") as reserve, patch("prompt_lib.backends.groq_pacing.wait") as wait:
            result = GroqAPIWrapper.call("Refine this previous answer", engine="groq:test")
            self.assertEqual(result["choices"][0]["text"], "Refinement 2")
            self.assertEqual(post.call_args_list[0], post.call_args_list[1])
            self.assertEqual(reserve.call_count, 2)
            wait.assert_called_once_with(10)

    def test_repeated_limits_are_bounded(self):
        limited = Mock(status_code=429, headers={"Retry-After":"10"})
        with patch.dict(os.environ, {"GROQ_API_KEY":"test-secret", "GROQ_RESUME_ON_RATE_LIMIT":"true"}), patch("requests.post", return_value=limited) as post, patch("prompt_lib.backends.request_budget.reserve"), patch("prompt_lib.backends.groq_pacing.wait") as wait:
            with self.assertRaises(InferenceError):
                GroqAPIWrapper.call("question", engine="groq:test")
            self.assertEqual(post.call_count, 6)
            self.assertEqual(wait.call_count, 5)
