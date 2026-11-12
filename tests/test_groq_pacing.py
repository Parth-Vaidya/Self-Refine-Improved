import io
import os
import sys
import unittest
from unittest.mock import patch, Mock

from prompt_lib.backends.groq_api import GroqAPIWrapper
from prompt_lib.backends.groq_pacing import retry_delay, wait
from prompt_lib.backends.huggingface_api import InferenceError


class NoWaitTests(unittest.TestCase):
    def setUp(self):
        settings = patch.dict(os.environ, {"GROQ_RESUME_ON_RATE_LIMIT": "false"})
        settings.start()
        self.addCleanup(settings.stop)

    def test_rate_limit_fails_immediately_without_retry(self):
        response = Mock(status_code=429, headers={"Retry-After": "180"})
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-secret", "GROQ_MIN_INTERVAL_SECONDS": "65", "GROQ_MAX_RETRIES": "5"}), patch("requests.post", return_value=response) as post, patch("prompt_lib.backends.request_budget.reserve") as reserve, patch("time.sleep") as sleep:
            with self.assertRaises(InferenceError):
                GroqAPIWrapper.call("question", engine="groq:test")
            post.assert_called_once()
            reserve.assert_called_once()
            sleep.assert_not_called()

    def test_success_ignores_old_timer_settings(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "answer"}}]}
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-secret", "GROQ_MIN_INTERVAL_SECONDS": "65"}), patch("requests.post", return_value=response), patch("prompt_lib.backends.request_budget.reserve"), patch("time.sleep") as sleep:
            result = GroqAPIWrapper.call("question", engine="groq:test")
            self.assertEqual(result["inference"]["max_retries"], 0)
            sleep.assert_not_called()


class ResumeTests(unittest.TestCase):
    def test_rate_limit_resumes_same_stage_with_same_payload(self):
        limited = Mock(status_code=429, headers={"Retry-After": "10"})
        good = Mock(status_code=200)
        good.json.return_value = {"choices": [{"message": {"content": "Refinement 2"}}]}
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-secret", "GROQ_RESUME_ON_RATE_LIMIT": "true"}), patch("requests.post", side_effect=[limited, good]) as post, patch("prompt_lib.backends.request_budget.reserve") as reserve, patch("prompt_lib.backends.groq_pacing.wait") as wait_mock:
            result = GroqAPIWrapper.call("Refine this previous answer", engine="groq:test")
            self.assertEqual(result["choices"][0]["text"], "Refinement 2")
            self.assertEqual(post.call_args_list[0], post.call_args_list[1])
            self.assertEqual(reserve.call_count, 2)
            wait_mock.assert_called_once_with(
                10,
                reason="Rate limit exceeded (HTTP 429)",
                attempt=1,
                max_retries=5,
            )

    def test_repeated_limits_are_bounded(self):
        limited = Mock(status_code=429, headers={"Retry-After": "10"})
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-secret", "GROQ_RESUME_ON_RATE_LIMIT": "true"}), patch("requests.post", return_value=limited) as post, patch("prompt_lib.backends.request_budget.reserve"), patch("prompt_lib.backends.groq_pacing.wait") as wait_mock:
            with self.assertRaises(InferenceError):
                GroqAPIWrapper.call("question", engine="groq:test")
            self.assertEqual(post.call_count, 6)
            self.assertEqual(wait_mock.call_count, 5)

    def test_default_retry_delay_is_5_seconds_when_no_valid_retry_after(self):
        self.assertEqual(retry_delay(None, 429), 5.0)
        self.assertEqual(retry_delay("", 429), 5.0)
        self.assertEqual(retry_delay("not-a-number", 429), 5.0)
        self.assertEqual(retry_delay("NaN", 429), 5.0)

        # In end-to-end call: empty headers defaults to 5.0s wait
        limited = Mock(status_code=429, headers={})
        limited.json.return_value = {"error": {"message": "Rate limit reached"}}
        good = Mock(status_code=200)
        good.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-secret", "GROQ_RESUME_ON_RATE_LIMIT": "true"}), patch("requests.post", side_effect=[limited, good]), patch("prompt_lib.backends.request_budget.reserve"), patch("prompt_lib.backends.groq_pacing.wait") as wait_mock:
            result = GroqAPIWrapper.call("test prompt", engine="groq:test")
            self.assertEqual(result["choices"][0]["text"], "ok")
            wait_mock.assert_called_once_with(
                5.0,
                reason="Rate limit exceeded (HTTP 429)",
                attempt=1,
                max_retries=5,
            )

    def test_valid_retry_after_is_respected(self):
        # Server-specified cooldowns must not be replaced by 5s
        self.assertEqual(retry_delay("65", 429), 65.0)
        self.assertEqual(retry_delay("65.5", 429), 65.5)
        self.assertEqual(retry_delay("12", 429), 12.0)
        self.assertEqual(retry_delay("5", 429), 5.0)

    def test_retry_delay_from_json_error_body_fallback(self):
        limited = Mock(status_code=429, headers={})
        limited.json.return_value = {
            "error": {"message": "Rate limit reached. Please try again in 14.5s."}
        }
        good = Mock(status_code=200)
        good.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-secret", "GROQ_RESUME_ON_RATE_LIMIT": "true"}), patch("requests.post", side_effect=[limited, good]), patch("prompt_lib.backends.request_budget.reserve"), patch("prompt_lib.backends.groq_pacing.wait") as wait_mock:
            result = GroqAPIWrapper.call("test prompt", engine="groq:test")
            self.assertEqual(result["choices"][0]["text"], "ok")
            wait_mock.assert_called_once_with(
                14.5,
                reason="Rate limit exceeded (HTTP 429)",
                attempt=1,
                max_retries=5,
            )

    def test_permanent_errors_not_retried(self):
        for status in (400, 401, 403, 404, 500):
            with self.subTest(status=status):
                err_resp = Mock(status_code=status, headers={})
                with patch.dict(os.environ, {"GROQ_API_KEY": "test-secret", "GROQ_RESUME_ON_RATE_LIMIT": "true"}), patch("requests.post", return_value=err_resp) as post, patch("prompt_lib.backends.request_budget.reserve"), patch("prompt_lib.backends.groq_pacing.wait") as wait_mock:
                    with self.assertRaises(InferenceError):
                        GroqAPIWrapper.call("question", engine="groq:test")
                    # Permanent error fails immediately without retrying
                    self.assertEqual(post.call_count, 1)
                    wait_mock.assert_not_called()

    def test_wait_terminal_output_message(self):
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture), patch("time.sleep"):
            wait(5.0, reason="Rate limit exceeded (HTTP 429)", attempt=1, max_retries=5)
        output = stderr_capture.getvalue()
        self.assertIn("Rate limit exceeded (HTTP 429)", output)
        self.assertIn("Attempt 1/5", output)
        self.assertIn("5.0 seconds", output)


if __name__ == "__main__":
    unittest.main()
