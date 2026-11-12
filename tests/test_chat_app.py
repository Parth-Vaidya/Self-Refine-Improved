import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch

from src.chat_app import ChatApp, default_generate_response
from src.conversation_manager import ConversationManager


class ChatAppTests(unittest.TestCase):
    def test_exit_from_main_menu(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            app = ChatApp(manager=manager, response_fn=lambda ctx: "unused")

            out = io.StringIO()
            with patch("builtins.input", side_effect=["3"]), contextlib.redirect_stdout(out):
                app.run()

            output = out.getvalue()
            self.assertIn("SELF-REFINE AI", output)
            self.assertIn("1. Start a New Chat", output)
            self.assertIn("2. Continue Previous Chat", output)
            self.assertIn("3. Exit", output)
            self.assertIn("Goodbye!", output)

    def test_continue_when_no_previous_conversations_returns_to_menu(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            app = ChatApp(manager=manager, response_fn=lambda ctx: "unused")

            out = io.StringIO()
            with patch("builtins.input", side_effect=["2", "3"]), contextlib.redirect_stdout(out):
                app.run()

            output = out.getvalue()
            self.assertIn("No previous conversations found.", output)
            self.assertIn("Goodbye!", output)

    def test_start_new_chat_auto_title_saves_messages_and_returns_to_menu(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            seen_contexts = []

            def fake_llm(context: str) -> str:
                seen_contexts.append(context)
                return f"Mock reply #{len(seen_contexts)}"

            app = ChatApp(manager=manager, response_fn=fake_llm)
            inputs = [
                "1",  # Start a New Chat
                "",  # Blank title -> auto-generate from first query
                "What is self-refine?",
                "Tell me more.",
                "menu",  # Return to main menu
                "3",  # Exit
            ]

            out = io.StringIO()
            with patch("builtins.input", side_effect=inputs), contextlib.redirect_stdout(out):
                app.run()

            convs = manager.list_conversations()
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0]["title"], "What is self-refine?")

            loaded = manager.load_conversation(convs[0]["id"])
            self.assertEqual(len(loaded["messages"]), 4)
            self.assertEqual(loaded["messages"][0]["content"], "What is self-refine?")
            self.assertEqual(loaded["messages"][1]["content"], "Mock reply #1")
            self.assertEqual(loaded["messages"][2]["content"], "Tell me more.")
            self.assertEqual(loaded["messages"][3]["content"], "Mock reply #2")

            # Second turn must include the first turn in LLM context.
            self.assertIn("User: What is self-refine?", seen_contexts[1])
            self.assertIn("Assistant: Mock reply #1", seen_contexts[1])
            self.assertIn("User: Tell me more.", seen_contexts[1])

    def test_continue_previous_chat_restores_context_after_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # First session creates a conversation and saves a turn.
            manager1 = ConversationManager(tmpdir)
            app1 = ChatApp(manager=manager1, response_fn=lambda ctx: "Initial answer")
            with patch("builtins.input", side_effect=["1", "Orbital Physics", "Hello", "menu", "3"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                app1.run()

            # Second session ("restart") continues the existing conversation.
            manager2 = ConversationManager(tmpdir)
            captured_contexts = []

            def fake_llm_after_restart(context: str) -> str:
                captured_contexts.append(context)
                return "Follow-up answer"

            app2 = ChatApp(manager=manager2, response_fn=fake_llm_after_restart)
            out = io.StringIO()
            with patch("builtins.input", side_effect=["2", "1", "Follow-up question", "quit"]), \
                 contextlib.redirect_stdout(out):
                app2.run()

            self.assertEqual(len(captured_contexts), 1)
            self.assertIn("User: Hello", captured_contexts[0])
            self.assertIn("Assistant: Initial answer", captured_contexts[0])
            self.assertIn("User: Follow-up question", captured_contexts[0])

            loaded = manager2.load_conversation("chat_001")
            self.assertEqual(len(loaded["messages"]), 4)
            self.assertEqual(loaded["messages"][3]["content"], "Follow-up answer")
            self.assertIn("Orbital Physics", out.getvalue())

    def test_default_generate_response_calls_chat_pipeline(self):
        with patch("src.chat_app.ChatResponsePipeline.generate_chat_response", return_value="Refined response") as mock_gen:
            reply = default_generate_response("User: Hi")

        self.assertEqual(reply, "Refined response")
        mock_gen.assert_called_once_with("User: Hi")

    def test_rate_limit_error_handling_and_conversation_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            from prompt_lib.backends.huggingface_api import InferenceError

            def fail_with_rate_limit(ctx):
                raise InferenceError("Groq rate limit exceeded.", status_code=429)

            app = ChatApp(manager=manager, response_fn=fail_with_rate_limit)
            inputs = [
                "1",
                "Rate Limit Test",
                "Hello when busy",
                "menu",
                "3",
            ]
            out = io.StringIO()
            with patch("builtins.input", side_effect=inputs), contextlib.redirect_stdout(out):
                app.run()

            output = out.getvalue()
            self.assertIn("Groq rate limit reached", output)

            # User message should still be saved even if model generation failed
            convs = manager.list_conversations()
            self.assertEqual(len(convs), 1)
            loaded = manager.load_conversation(convs[0]["id"])
            self.assertEqual(len(loaded["messages"]), 1)
            self.assertEqual(loaded["messages"][0]["content"], "Hello when busy")


if __name__ == "__main__":
    unittest.main()

