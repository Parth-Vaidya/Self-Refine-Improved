import json
import tempfile
import unittest
from pathlib import Path

from src.conversation_manager import ConversationManager
from src.preference_extractor import (
    UserProfileManager,
    detect_preferences_in_text,
)


class PreferenceExtractorTests(unittest.TestCase):
    def test_detect_preferences_in_text_keywords(self):
        self.assertIn("prefers_step_by_step", detect_preferences_in_text("Please explain step by step."))
        self.assertIn("prefers_step_by_step", detect_preferences_in_text("Can you break it down for me?"))
        self.assertIn("prefers_concise_answers", detect_preferences_in_text("Keep it short and to the point."))
        self.assertIn("prefers_concise_answers", detect_preferences_in_text("Give a brief explanation."))
        self.assertIn("prefers_simple_code", detect_preferences_in_text("Use simple code without external libraries."))
        self.assertIn("prefers_examples", detect_preferences_in_text("Please give examples."))
        self.assertIn("prefers_examples", detect_preferences_in_text("Show me an example in everyday life."))
        self.assertIn("prefers_examples", detect_preferences_in_text("Provide an example please."))
        self.assertIn("prefers_examples", detect_preferences_in_text("Give me an example."))

        # Messages without matching preference keywords
        self.assertEqual(detect_preferences_in_text("What is Newton's second law?"), set())

    def test_extract_from_conversations_creates_user_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chats_dir = Path(tmpdir) / "chats"
            profile_path = Path(tmpdir) / "user_profile.json"

            conv_mgr = ConversationManager(chats_dir=chats_dir)
            c1 = conv_mgr.create_conversation("Physics")
            conv_mgr.save_message(c1, "user", "Explain Newton's laws step by step.")
            conv_mgr.save_message(c1, "assistant", "Sure, step 1 is...")

            c2 = conv_mgr.create_conversation("Python")
            conv_mgr.save_message(c2, "user", "How do I reverse a list? Use simple code and give examples.")
            conv_mgr.save_message(c2, "assistant", "Here is simple code...")

            extractor = UserProfileManager(chats_dir=chats_dir, profile_path=profile_path)
            profile = extractor.extract_from_conversations()

            self.assertTrue(profile_path.exists())
            prefs = profile["preferences"]
            self.assertIn("prefers_step_by_step", prefs)
            self.assertIn("prefers_simple_code", prefs)
            self.assertIn("prefers_examples", prefs)
            self.assertNotIn("prefers_concise_answers", prefs)

    def test_update_profile_without_duplicates_or_overwriting_manual_edits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chats_dir = Path(tmpdir) / "chats"
            profile_path = Path(tmpdir) / "user_profile.json"

            conv_mgr = ConversationManager(chats_dir=chats_dir)
            c1 = conv_mgr.create_conversation("First Chat")
            conv_mgr.save_message(c1, "user", "Keep it short.")
            conv_mgr.save_message(c1, "assistant", "Short response.")

            extractor = UserProfileManager(chats_dir=chats_dir, profile_path=profile_path)
            profile1 = extractor.extract_from_conversations()
            self.assertIn("prefers_concise_answers", profile1["preferences"])

            # Simulate manual user edit: adding custom note / toggling enabled
            saved_data = json.loads(profile_path.read_text(encoding="utf-8"))
            saved_data["preferences"]["prefers_concise_answers"]["user_note"] = "Always under 3 sentences"
            saved_data["preferences"]["prefers_concise_answers"]["enabled"] = False
            profile_path.write_text(json.dumps(saved_data), encoding="utf-8")

            # Add a second conversation that also asks to keep it short + give examples
            c2 = conv_mgr.create_conversation("Second Chat")
            conv_mgr.save_message(c2, "user", "Keep it short and give examples.")
            conv_mgr.save_message(c2, "assistant", "Response.")

            # Second extraction run
            profile2 = extractor.extract_from_conversations()
            prefs = profile2["preferences"]

            # Newly detected preference is added
            self.assertIn("prefers_examples", prefs)
            # Existing preference was updated without duplicating or wiping manual user edit
            self.assertIn("prefers_concise_answers", prefs)
            self.assertEqual(prefs["prefers_concise_answers"].get("user_note"), "Always under 3 sentences")
            self.assertEqual(prefs["prefers_concise_answers"].get("enabled"), False)

    def test_sensitive_tokens_redacted_from_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chats_dir = Path(tmpdir) / "chats"
            profile_path = Path(tmpdir) / "user_profile.json"

            extractor = UserProfileManager(chats_dir=chats_dir, profile_path=profile_path)
            profile = {
                "preferences": {
                    "custom_pref": {
                        "description": "Prefers secret key hf_abcdefghijklmnopqrstuvwxyz12345",
                    }
                }
            }
            extractor.save_profile(profile)

            raw_text = profile_path.read_text(encoding="utf-8")
            self.assertNotIn("hf_abcdefghijklmnopqrstuvwxyz12345", raw_text)
            self.assertIn("[REDACTED]", raw_text)


if __name__ == "__main__":
    unittest.main()

