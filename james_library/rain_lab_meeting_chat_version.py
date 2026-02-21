"""Meeting chat scaffolding with OpenClaw-inspired architecture.

This module is intentionally small and focuses on patterns that scale:
- dependency injection for model + channel adapters
- command routing separated from chat handling
- retry + timeout wrapper for model calls
- transcript persistence for debugging and audits
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable, Protocol


class ChatModel(Protocol):
    """Minimal protocol for LLM model backends."""

    def complete(self, prompt: str, *, timeout_s: float) -> str:
        """Return a model response."""


class ChannelAdapter(Protocol):
    """Protocol for chat channels (terminal, telegram, discord, etc.)."""

    def send(self, text: str) -> None:
        """Send a text response to the channel."""


@dataclass(slots=True)
class ChatMessage:
    role: str
    text: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class MeetingChatConfig:
    model_timeout_s: float = 45.0
    max_retries: int = 2
    max_history: int = 14
    transcript_path: Path = Path("meeting_archives/meeting_chat_transcript.jsonl")


@dataclass(slots=True)
class MeetingChatService:
    config: MeetingChatConfig
    model: ChatModel
    channel: ChannelAdapter
    _history: list[ChatMessage] = field(default_factory=list)
    _commands: dict[str, Callable[[str], str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._commands.update(
            {
                "/help": lambda _: "Commands: /help, /summary, /reset",
                "/summary": self._cmd_summary,
                "/reset": self._cmd_reset,
            }
        )

    def handle_user_message(self, text: str) -> str:
        clean = self._sanitize(text)
        if clean.startswith("/"):
            reply = self._run_command(clean)
            self.channel.send(reply)
            self._record("assistant", reply)
            return reply

        self._record("user", clean)
        prompt = self._build_prompt()
        reply = self._complete_with_retries(prompt)
        self.channel.send(reply)
        self._record("assistant", reply)
        self._persist_transcript()
        return reply

    def _sanitize(self, text: str) -> str:
        return text.replace("<|im_start|>", "").replace("<|im_end|>", "").strip()

    def _run_command(self, text: str) -> str:
        command, _, arg = text.partition(" ")
        handler = self._commands.get(command)
        if not handler:
            return f"Unknown command: {command}. Use /help"
        return handler(arg.strip())

    def _cmd_summary(self, _arg: str) -> str:
        if not self._history:
            return "No messages yet."
        last_messages = self._history[-4:]
        return " | ".join(f"{msg.role}:{msg.text[:30]}" for msg in last_messages)

    def _cmd_reset(self, _arg: str) -> str:
        self._history.clear()
        return "Conversation reset."

    def _record(self, role: str, text: str) -> None:
        self._history.append(ChatMessage(role=role, text=text))
        if len(self._history) > self.config.max_history:
            self._history = self._history[-self.config.max_history :]

    def _build_prompt(self) -> str:
        lines = [f"{msg.role}: {msg.text}" for msg in self._history]
        return "\n".join(lines + ["assistant:"])

    def _complete_with_retries(self, prompt: str) -> str:
        error: Exception | None = None
        for _ in range(self.config.max_retries + 1):
            try:
                return self.model.complete(prompt, timeout_s=self.config.model_timeout_s)
            except Exception as exc:  # noqa: BLE001
                error = exc
        return f"Model unavailable: {error}"

    def _persist_transcript(self) -> None:
        self.config.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config.transcript_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(asdict(self._history[-1]), ensure_ascii=False) + "\n")


class StdoutChannel:
    def send(self, text: str) -> None:
        print(text)
