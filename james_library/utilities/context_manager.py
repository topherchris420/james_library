"""Token-aware history compaction for Python launcher flows.

This module intentionally operates on transient in-memory buffers only.
It must never mutate or truncate durable episodic logs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import importlib
import re
from typing import Any, Iterable


def _load_tiktoken() -> Any | None:
    try:
        return importlib.import_module("tiktoken")
    except ImportError:  # pragma: no cover - local environments may omit the package
        return None


tiktoken = _load_tiktoken()


SUMMARY_PREFIX = "[SUMMARY]"
RECENT_TURNS_TO_KEEP = 3

_DANGEROUS_PATTERNS = (
    re.compile(r"\bDANGEROUS\b", re.IGNORECASE),
    re.compile(r"<tool_result[^>]*>", re.IGNORECASE),
    re.compile(r"\bconfirmed\b", re.IGNORECASE),
)

_HARDWARE_PATTERNS = (
    re.compile(r"\bhardware state confirmation\b", re.IGNORECASE),
    re.compile(r"\bpower rail\b", re.IGNORECASE),
    re.compile(r"\bwatchdog\b", re.IGNORECASE),
    re.compile(r"\bvoltage\b", re.IGNORECASE),
    re.compile(r"\bservo\b", re.IGNORECASE),
    re.compile(r"\bmcu\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class ContextCompactionResult:
    compacted_messages: list[dict[str, str]]
    original_tokens: int
    compacted_tokens: int
    tokens_saved: int
    summary_count: int
    pruned_count: int


@dataclass
class _Entry:
    message: dict[str, str]
    protected: bool
    prunable: bool


def calculate_tokens(messages: Iterable[dict[str, str]], model: str = "cl100k_base") -> int:
    """Estimate token count using tiktoken when available.

    Falls back to a simple heuristic only if `tiktoken` is unavailable.
    """

    joined = []
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        joined.append(f"{role}:{content}")
    payload = "\n".join(joined)

    if tiktoken is not None:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            if model != "cl100k_base":
                try:
                    encoding = tiktoken.encoding_for_model(model)
                except KeyError:
                    pass
        except Exception:
            encoding = None
        if encoding is not None:
            return len(encoding.encode(payload))

    return max(1, len(payload) // 4)


def compact_history(
    messages: list[dict[str, str]],
    max_tokens: int,
    model: str = "cl100k_base",
) -> ContextCompactionResult:
    """Compact a message history using summarize-then-prune.

    Rules:
    - Keep the system prompt intact.
    - Keep the most recent three user turns and their following replies intact.
    - Keep dangerous tool outputs and hardware confirmations exact.
    - Summarize older safe middle history first.
    - Prune oldest remaining safe summaries/messages if still over budget.
    """

    history = [deepcopy(message) for message in messages]
    original_tokens = calculate_tokens(history, model=model)
    if not history or original_tokens <= max_tokens:
        return ContextCompactionResult(
            compacted_messages=history,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            tokens_saved=0,
            summary_count=0,
            pruned_count=0,
        )

    recent_start = _recent_boundary_index(history)
    entries = _build_entries(history, recent_start)
    entries, summary_count = _summarize_safe_middle(entries)
    compacted_tokens = calculate_tokens((entry.message for entry in entries), model=model)
    entries, pruned_count, compacted_tokens = _prune_to_budget(entries, max_tokens, model=model)

    compacted_messages = [entry.message for entry in entries]
    return ContextCompactionResult(
        compacted_messages=compacted_messages,
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
        tokens_saved=max(0, original_tokens - compacted_tokens),
        summary_count=summary_count,
        pruned_count=pruned_count,
    )


def _recent_boundary_index(messages: list[dict[str, str]]) -> int:
    user_indices = [
        index for index, message in enumerate(messages) if str(message.get("role", "")).lower() == "user"
    ]
    if len(user_indices) < RECENT_TURNS_TO_KEEP:
        return 1 if _has_system_prompt(messages) else 0
    return user_indices[-RECENT_TURNS_TO_KEEP]


def _build_entries(messages: list[dict[str, str]], recent_start: int) -> list[_Entry]:
    entries: list[_Entry] = []
    for index, message in enumerate(messages):
        protected = index == 0 and _has_system_prompt(messages)
        protected = protected or index >= recent_start or _must_preserve_exact(message)
        entries.append(
            _Entry(
                message=message,
                protected=protected,
                prunable=not protected,
            )
        )
    return entries


def _summarize_safe_middle(entries: list[_Entry]) -> tuple[list[_Entry], int]:
    summarized: list[_Entry] = []
    buffer: list[dict[str, str]] = []
    summary_count = 0

    def flush_buffer() -> None:
        nonlocal summary_count
        if not buffer:
            return
        summarized.append(
            _Entry(
                message={"role": "assistant", "content": _summarize_messages(buffer)},
                protected=False,
                prunable=True,
            )
        )
        buffer.clear()
        summary_count += 1

    for entry in entries:
        if entry.protected:
            flush_buffer()
            summarized.append(entry)
        else:
            buffer.append(entry.message)

    flush_buffer()
    return summarized, summary_count


def _prune_to_budget(
    entries: list[_Entry],
    max_tokens: int,
    model: str,
) -> tuple[list[_Entry], int, int]:
    current = list(entries)
    pruned = 0
    compacted_tokens = calculate_tokens((entry.message for entry in current), model=model)
    while compacted_tokens > max_tokens:
        prune_index = next((index for index, entry in enumerate(current) if entry.prunable), None)
        if prune_index is None:
            break
        del current[prune_index]
        pruned += 1
        compacted_tokens = calculate_tokens((entry.message for entry in current), model=model)
    return current, pruned, compacted_tokens


def _summarize_messages(messages: list[dict[str, str]]) -> str:
    focus_messages = [
        message
        for message in messages
        if str(message.get("role", "")).strip().lower() == "user"
    ]
    if not focus_messages:
        focus_messages = [message for message in messages if _normalize_whitespace(str(message.get("content", "")))]

    fragments: list[str] = []
    for message in focus_messages[:2]:
        role = str(message.get("role", "")).strip().lower() or "message"
        content = _normalize_whitespace(str(message.get("content", "")))
        if not content:
            continue
        fragments.append(f"{role}:{_truncate(content, 18)}")

    if not fragments:
        return SUMMARY_PREFIX
    return f"{SUMMARY_PREFIX} {'; '.join(fragments)}"


def _must_preserve_exact(message: dict[str, str]) -> bool:
    content = str(message.get("content", ""))
    if not content:
        return False
    return _is_dangerous_tool_output(content) or _is_hardware_confirmation(content)


def _is_dangerous_tool_output(content: str) -> bool:
    return any(pattern.search(content) for pattern in _DANGEROUS_PATTERNS) and (
        "tool_result" in content.lower() or "dangerous" in content.lower()
    )


def _is_hardware_confirmation(content: str) -> bool:
    return any(pattern.search(content) for pattern in _HARDWARE_PATTERNS)


def _has_system_prompt(messages: list[dict[str, str]]) -> bool:
    if not messages:
        return False
    return str(messages[0].get("role", "")).lower() == "system"


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


__all__ = [
    "ContextCompactionResult",
    "calculate_tokens",
    "compact_history",
]
