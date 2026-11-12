import tempfile
import unittest
from pathlib import Path

from src.conversation_manager import (
    ConversationManager,
    TRUNCATION_NOTICE,
    generate_title_from_query,
)


class ConversationManagerTests(unittest.TestCase):
    def test_create_conversation_creates_unique_txt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            conv_id = manager.create_conversation("Newton's Laws")

            self.assertEqual(conv_id, "chat_001")
            expected_path = Path(tmpdir) / "chat_001.txt"
            self.assertTrue(expected_path.exists())

            raw = expected_path.read_text(encoding="utf-8")
            self.assertIn("Conversation ID: chat_001", raw)
            self.assertIn("Title: Newton's Laws", raw)
            self.assertIn("Created:", raw)
            self.assertIn("Last Updated:", raw)

    def test_create_multiple_conversations_increments_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            id1 = manager.create_conversation("First")
            id2 = manager.create_conversation("Second")
            id3 = manager.create_conversation("Third")

            self.assertEqual([id1, id2, id3], ["chat_001", "chat_002", "chat_003"])
            self.assertEqual(len(list(Path(tmpdir).glob("*.txt"))), 3)

    def test_save_and_load_user_and_assistant_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            conv_id = manager.create_conversation("Physics")
            manager.save_message(conv_id, "user", "Explain Newton's third law.")
            manager.save_message(
                conv_id,
                "assistant",
                "For every action, there is an equal and opposite reaction.",
            )
            manager.save_message(conv_id, "user", "Give an example.\nIn everyday life.")

            loaded = manager.load_conversation(conv_id)
            self.assertEqual(loaded["id"], conv_id)
            self.assertEqual(loaded["title"], "Physics")
            self.assertEqual(len(loaded["messages"]), 3)
            self.assertEqual(loaded["messages"][0]["role"], "user")
            self.assertEqual(loaded["messages"][0]["content"], "Explain Newton's third law.")
            self.assertEqual(loaded["messages"][1]["role"], "assistant")
            self.assertIn("equal and opposite", loaded["messages"][1]["content"])
            self.assertEqual(
                loaded["messages"][2]["content"], "Give an example.\nIn everyday life."
            )

    def test_list_conversations_empty_and_populated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            self.assertEqual(manager.list_conversations(), [])

            manager.create_conversation("Alpha")
            manager.create_conversation("Beta")
            listed = manager.list_conversations()

            self.assertEqual(len(listed), 2)
            for item in listed:
                self.assertIn("id", item)
                self.assertIn("title", item)
                self.assertIn("created", item)
                self.assertIn("updated", item)
            titles = {item["title"] for item in listed}
            self.assertEqual(titles, {"Alpha", "Beta"})

    def test_separate_conversation_histories_do_not_mix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            c1 = manager.create_conversation("Topic A")
            c2 = manager.create_conversation("Topic B")

            manager.save_message(c1, "user", "Message only in A")
            manager.save_message(c2, "user", "Message only in B")

            d1 = manager.load_conversation(c1)
            d2 = manager.load_conversation(c2)
            self.assertEqual([m["content"] for m in d1["messages"]], ["Message only in A"])
            self.assertEqual([m["content"] for m in d2["messages"]], ["Message only in B"])

    def test_persistence_across_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager1 = ConversationManager(tmpdir)
            conv_id = manager1.create_conversation("Persistent Chat")
            manager1.save_message(conv_id, "user", "Hello before restart")
            manager1.save_message(conv_id, "assistant", "Hi! Saved to disk.")

            # Simulate application restart with a fresh ConversationManager instance.
            manager2 = ConversationManager(tmpdir)
            listed = manager2.list_conversations()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], conv_id)

            loaded = manager2.load_conversation(conv_id)
            self.assertEqual(len(loaded["messages"]), 2)
            self.assertEqual(loaded["messages"][0]["content"], "Hello before restart")
            self.assertEqual(loaded["messages"][1]["content"], "Hi! Saved to disk.")

    def test_context_restoration_and_truncation_preserves_full_txt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            conv_id = manager.create_conversation("Long Chat")
            for i in range(10):
                manager.save_message(conv_id, "user", f"User question {i}: " + ("x" * 100))
                manager.save_message(conv_id, "assistant", f"Assistant answer {i}: " + ("y" * 100))

            full_context = manager.get_context_for_llm(conv_id, max_chars=20000)
            self.assertIn("User question 0:", full_context)
            self.assertIn("Assistant answer 9:", full_context)

            short_context = manager.get_context_for_llm(conv_id, max_chars=500)
            self.assertLessEqual(len(short_context), 500)
            self.assertIn(TRUNCATION_NOTICE, short_context)
            self.assertIn("Assistant answer 9:", short_context)
            self.assertNotIn("User question 0:", short_context)

            # Original saved TXT file must remain complete and untruncated.
            loaded = manager.load_conversation(conv_id)
            self.assertEqual(len(loaded["messages"]), 20)
            self.assertTrue(loaded["messages"][0]["content"].startswith("User question 0:"))

    def test_title_generation_from_query(self):
        self.assertEqual(generate_title_from_query("Explain gravity"), "Explain gravity")
        long_q = "Can you explain in great detail how Newton's laws of motion apply to orbital mechanics?"
        generated = generate_title_from_query(long_q, max_length=40)
        self.assertLessEqual(len(generated), 40)
        self.assertTrue(generated.endswith("..."))
        self.assertTrue(generate_title_from_query("").startswith("Chat "))

    def test_save_and_load_mode_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConversationManager(tmpdir)
            conv_id = manager.create_conversation("Modes Test")
            manager.save_message(conv_id, "user", "Message 1", mode="standard")
            manager.save_message(conv_id, "assistant", "Answer 1")
            manager.save_message(conv_id, "user", "Message 2", mode="self_refine")
            manager.save_message(conv_id, "assistant", "Answer 2")

            loaded = manager.load_conversation(conv_id)
            messages = loaded["messages"]
            self.assertEqual(len(messages), 4)
            self.assertEqual(messages[0].get("mode"), "standard")
            self.assertIsNone(messages[1].get("mode"))
            self.assertEqual(messages[2].get("mode"), "self_refine")
            self.assertIsNone(messages[3].get("mode"))

            raw_txt = (Path(tmpdir) / f"{conv_id}.txt").read_text(encoding="utf-8")
            self.assertIn("USER [mode: standard]:", raw_txt)
            self.assertIn("USER [mode: self_refine]:", raw_txt)
            self.assertIn("ASSISTANT:", raw_txt)

    def test_backward_compatibility_with_older_txt_without_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_legacy = (
                "========================================\n"
                "Conversation ID: chat_099\n"
                "Title: Legacy Chat\n"
                "Created: 2026-11-10 10:00:00\n"
                "Last Updated: 2026-11-10 10:05:00\n"
                "========================================\n\n"
                "[2026-11-10 10:00:00] USER:\n"
                "Old message\n\n"
                "[2026-11-10 10:00:05] ASSISTANT:\n"
                "Old response\n\n"
            )
            chat_file = Path(tmpdir) / "chat_099.txt"
            chat_file.write_text(raw_legacy, encoding="utf-8")

            manager = ConversationManager(tmpdir)
            loaded = manager.load_conversation("chat_099")
            self.assertEqual(loaded["title"], "Legacy Chat")
            self.assertEqual(len(loaded["messages"]), 2)
            self.assertEqual(loaded["messages"][0]["content"], "Old message")
            self.assertIsNone(loaded["messages"][0].get("mode"))


if __name__ == "__main__":
    unittest.main()
