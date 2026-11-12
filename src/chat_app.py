"""Simple terminal-based conversation manager CLI for Self-Refine AI."""

from __future__ import annotations

import contextlib
import io
import os
import sys
from typing import Callable, Optional

from src.conversation_manager import (
    ConversationManager,
    DEFAULT_MAX_CONTEXT_CHARS,
    generate_title_from_query,
)
from src.chat_pipeline import ChatResponsePipeline
from prompt_lib.backends.huggingface_api import InferenceError


DEFAULT_CONFIG_PATH = "experiments/B-qwen-groq.json"
DEFAULT_ATTEMPTS = 2
DEFAULT_ENGINE = "groq:qwen/qwen3.8-27b"


def print_main_menu() -> None:
    print(
        "\n========================================\n"
        "          SELF-REFINE AI\n"
        "========================================\n\n"
        "1. Start a New Chat\n"
        "2. Continue Previous Chat\n"
        "3. Exit\n"
    )


def default_generate_response(
    context: str,
    mode: str = "self_refine",
    engine: str = DEFAULT_ENGINE,
    attempts: int = DEFAULT_ATTEMPTS,
) -> str:
    """Generate response using dedicated interactive chat pipeline in chosen mode."""
    pipeline = ChatResponsePipeline(engine=engine, max_attempts=attempts)
    return pipeline.generate_chat_response(context, mode=mode)


class ChatApp:
    """Interactive terminal application for starting and continuing chats."""

    def __init__(
        self,
        manager: Optional[ConversationManager] = None,
        response_fn: Optional[Callable[[str], str]] = None,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ) -> None:
        self.manager = manager or ConversationManager()
        self.response_fn = response_fn or default_generate_response
        self.max_context_chars = max_context_chars

    @staticmethod
    def _prompt(text: str) -> Optional[str]:
        try:
            return input(text)
        except (EOFError, KeyboardInterrupt):
            return None

    def _prompt_response_mode(self) -> Optional[str]:
        """Prompt user for Standard vs Self-Refine generation mode."""
        print("\nHow would you like to generate your response?")
        print("1. Standard Response")
        print("2. Self-Refine Response")
        while True:
            choice = self._prompt("Select an option (1 or 2): ")
            if choice is None:
                return None
            choice = choice.strip()
            if choice == "1":
                return "standard"
            elif choice == "2":
                return "self_refine"
            else:
                print("Invalid choice. Please enter 1 for Standard Response or 2 for Self-Refine Response.")

    def _call_response_fn(self, context: str, mode: str) -> str:
        """Invoke response function, passing mode if accepted, else falling back to context only."""
        try:
            return self.response_fn(context, mode=mode)
        except TypeError:
            try:
                return self.response_fn(context, mode)
            except TypeError:
                return self.response_fn(context)

    def _chat_loop(self, conv_id: str, auto_title_pending: bool = False) -> bool:
        """Run interactive turn loop. Returns False if user requested full app exit."""
        print("Type your message below. Enter 'menu' to return to the main menu, or 'quit' to exit.\n")
        while True:
            user_input = self._prompt("You: ")
            if user_input is None:
                print("\nGoodbye!")
                return False

            stripped = user_input.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered in ("menu", "/menu", "back"):
                return True
            if lowered in ("quit", "exit"):
                print("Goodbye!")
                return False

            # Prompt user for response mode for this message
            mode = self._prompt_response_mode()
            if mode is None:
                print("\nGoodbye!")
                return False

            if auto_title_pending:
                self.manager.update_title(conv_id, generate_title_from_query(stripped))
                auto_title_pending = False

            self.manager.save_message(conv_id, "user", stripped, mode=mode)
            context = self.manager.get_context_for_llm(
                conv_id, max_chars=self.max_context_chars
            )

            try:
                reply = self._call_response_fn(context, mode=mode)
            except InferenceError as err:
                if "rate limit" in str(err).lower():
                    print("Assistant: [Notice] Groq rate limit reached. The service is temporarily busy; please wait a moment and try again.\n")
                elif "not configured" in str(err).lower():
                    print("Assistant: [Notice] Groq API key is not configured. Please set GROQ_API_KEY in .env.\n")
                else:
                    print(f"Assistant: [Notice] Provider inference error: {err}\n")
                continue
            except Exception as exc:
                print(f"Assistant: [Error] Could not generate response ({exc}). Please try again.\n")
                continue

            print(f"Assistant: {reply}\n")
            self.manager.save_message(conv_id, "assistant", reply)

    def start_new_chat(self) -> bool:
        title_input = self._prompt(
            "Enter a title for this conversation (or press Enter to auto-generate): "
        )
        if title_input is None:
            print("\nGoodbye!")
            return False

        cleaned_title = title_input.strip()
        auto_title_pending = not bool(cleaned_title)
        conv_id = self.manager.create_conversation(title=cleaned_title or None)
        data = self.manager.load_conversation(conv_id)
        print(f"\nStarted new conversation: {conv_id} - {data['title']}")
        return self._chat_loop(conv_id, auto_title_pending=auto_title_pending)

    def continue_previous_chat(self) -> bool:
        conversations = self.manager.list_conversations()
        if not conversations:
            print("\nNo previous conversations found.")
            return True

        print("\nAvailable conversations:")
        print("-" * 60)
        for idx, conv in enumerate(conversations, start=1):
            print(
                f"[{idx}] {conv['id']} | {conv['title']} | Last updated: {conv['updated']}"
            )
        print("-" * 60)

        choice = self._prompt("Select a conversation number (or 0 to go back): ")
        if choice is None:
            print("\nGoodbye!")
            return False

        choice = choice.strip()
        if choice == "0" or choice == "":
            return True
        if not choice.isdigit():
            print("Invalid selection. Returning to main menu.")
            return True

        selected_idx = int(choice)
        if not (1 <= selected_idx <= len(conversations)):
            print("Selection out of range. Returning to main menu.")
            return True

        conv_id = conversations[selected_idx - 1]["id"]
        data = self.manager.load_conversation(conv_id)
        print(f"\nResuming {conv_id}: {data['title']}")
        messages = list(data["messages"])  # type: ignore[arg-type]
        if messages:
            print("--- Recent history ---")
            for msg in messages[-6:]:
                speaker = "You" if msg["role"] == "user" else "Assistant"
                mode_str = f" [{msg['mode']}]" if msg.get("mode") else ""
                print(f"{speaker}{mode_str}: {msg['content']}")
            print("----------------------\n")
        else:
            print("(No messages in this conversation yet.)\n")

        return self._chat_loop(conv_id, auto_title_pending=False)

    def run(self) -> None:
        while True:
            print_main_menu()
            option = self._prompt("Select an option: ")
            if option is None:
                print("\nGoodbye!")
                break

            option = option.strip()
            if option == "1":
                if not self.start_new_chat():
                    break
            elif option == "2":
                if not self.continue_previous_chat():
                    break
            elif option == "3":
                print("Goodbye!")
                break
            else:
                print("Invalid option. Please choose 1, 2, or 3.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Enable Groq automatic rate-limit cooldown and recovery by default in chat
    if "GROQ_RESUME_ON_RATE_LIMIT" not in os.environ:
        os.environ["GROQ_RESUME_ON_RATE_LIMIT"] = "true"
    app = ChatApp()
    app.run()


if __name__ == "__main__":
    main()
