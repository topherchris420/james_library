import io
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Add the RLM library to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "rlm-main", "rlm-main"))

from rlm import RLM

# --- 1. FORCE UTF-8 ---
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

@dataclass
class AppConfig:
    library_path: Path = Path(os.environ.get("JAMES_LIBRARY_PATH", os.path.dirname(__file__)))
    model_name: str = os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct")
    base_url: str = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    max_paper_chars: int = 6000
    max_history_messages: int = 20


@dataclass
class JamesChatApp:
    config: AppConfig
    conversation_history: List[Tuple[str, str]] = field(default_factory=list)
    loaded_papers: List[Tuple[str, str]] = field(default_factory=list)

    def __post_init__(self):
        self.james_rlm = RLM(
            backend="openai",
            backend_kwargs={
                "model_name": self.config.model_name,
                "base_url": self.config.base_url,
            },
            environment="local",
            verbose=True,
        )
        self.james_personality = self._load_personality()
        self.base_context = self._build_base_context()

    def _load_personality(self) -> str:
        default_personality = "You are James, a visionary scientist at Vers3Dynamics. You are intense, curious, and precise."
        soul_paths = [
            self.config.library_path / "JAMES_SOUL.md",
            Path("james_library") / "JAMES_SOUL.md",
            Path("JAMES_SOUL.md"),
        ]

        for path in soul_paths:
            if path.exists():
                personality = path.read_text(encoding="utf-8")
                print(f"🧬 Soul Loaded from: {path}")
                return personality

        return default_personality

    def _build_base_context(self) -> str:
        return f"""INTERNAL SYSTEM COMMAND: Activate Persona 'JAMES'.

PROFILE:
{self.james_personality}

USER: Christopher (Lead Researcher).

INSTRUCTION: Stay in character. You have access to a library. When the user loads a paper, analyze it.
You can write and execute Python code to perform calculations, analysis, or any other task.
When asked to calculate or compute something, write Python code to do so.
"""

    def list_papers(self) -> str:
        if not self.config.library_path.exists():
            return "❌ Library folder not found."

        files = [f.name for f in self.config.library_path.iterdir() if f.suffix in {".md", ".txt"}]
        if not files:
            return "❌ Library is empty."

        return "\n".join(f"📄 {file_name}" for file_name in files)

    def read_paper(self, keyword: str) -> Tuple[Optional[str], str]:
        if not self.config.library_path.exists():
            return None, "Library not found."

        files = [f for f in self.config.library_path.iterdir() if f.suffix in {".md", ".txt"}]
        match = next((f for f in files if keyword.lower() in f.name.lower()), None)

        if not match:
            return None, "File not found."

        content = match.read_text(encoding="utf-8")[: self.config.max_paper_chars]
        return match.name, content

    def build_prompt(self, user_message: str) -> str:
        prompt_parts = [self.base_context]

        if self.loaded_papers:
            prompt_parts.append("\n--- LOADED RESEARCH PAPERS ---")
            for paper_name, paper_content in self.loaded_papers:
                prompt_parts.append(f"\n[{paper_name}]:\n{paper_content}\n")

        if self.conversation_history:
            prompt_parts.append("\n--- CONVERSATION HISTORY ---")
            for role, content in self.conversation_history[-self.config.max_history_messages :]:
                speaker = "Christopher" if role == "user" else "James"
                prompt_parts.append(f"\n{speaker}: {content}")

        prompt_parts.append(f"\nChristopher: {user_message}")
        prompt_parts.append("\nJames:")

        return "\n".join(prompt_parts)

    def process_command(self, user_input: str) -> Optional[str]:
        command = user_input.lower().strip()
        if command == "/list":
            print(f"\n📚 Library Contents:\n{self.list_papers()}")
            return None

        if command.startswith("/read"):
            keyword = user_input.replace("/read", "", 1).strip()
            if not keyword:
                print("⚠️ Please specify a name (e.g., '/read friction')")
                return None

            fname, content = self.read_paper(keyword)
            if not fname:
                print(f"❌ Could not find a paper matching '{keyword}'")
                return None

            print(f"📖 Reading '{fname}' into memory...", end="", flush=True)
            self.loaded_papers.append((fname, content))
            print(" Done.")
            return f"I have just loaded the paper '{fname}'. Please analyze it briefly."

        return user_input

    def run(self):
        print("\n⚡ James is listening. (RLM Mode - Can execute Python code!)")
        print("Commands:\n  /list  -> Show available research papers")
        print("  /read [name] -> Load a paper into James's memory (e.g., '/read friction')")
        print("  quit   -> Exit\n")

        while True:
            try:
                user_input = input("\n👤 Christopher: ")
                if user_input.lower() in {"quit", "exit"}:
                    break

                processed_input = self.process_command(user_input)
                if processed_input is None:
                    continue

                self.conversation_history.append(("user", processed_input))
                print("⚡ James: ", end="", flush=True)

                full_prompt = self.build_prompt(processed_input)
                result = self.james_rlm.completion(full_prompt)
                response = result.response if hasattr(result, "response") else str(result)

                print(response)
                self.conversation_history.append(("assistant", response))

            except KeyboardInterrupt:
                break

        print("\n👋 James signing off.")


def main():
    app = JamesChatApp(AppConfig())
    app.run()


if __name__ == "__main__":
    main()
