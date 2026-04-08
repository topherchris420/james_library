from __future__ import annotations

from copy import deepcopy

import pytest

from james_library.utilities.context_manager import (
    ContextCompactionResult,
    calculate_tokens,
    compact_history,
)


def _message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def _build_history() -> list[dict[str, str]]:
    return [
        _message("system", "You are the R.A.I.N. Lab orchestrator."),
        _message("user", "Old safe turn 1: inspect src/agent/history.rs and summarize it."),
        _message("assistant", "Old safe reply 1: history handles trimming and memory context."),
        _message(
            "tool",
            "[Tool results]\n"
            '<tool_result name="shell" status="ok">\n'
            "DANGEROUS: flash confirmed on /dev/ttyUSB0\n"
            "</tool_result>",
        ),
        _message(
            "assistant",
            "Hardware state confirmation: MCU voltage rail verified at 3.3V and watchdog armed.",
        ),
        _message("user", "Middle safe turn 2: scan launcher code for LLM call sites."),
        _message("assistant", "Middle safe reply 2: _call_llm_async is the main LLM boundary."),
        _message("user", "Recent turn A"),
        _message("assistant", "Recent reply A"),
        _message("user", "Recent turn B"),
        _message("assistant", "Recent reply B"),
        _message("user", "Recent turn C"),
        _message("assistant", "Recent reply C"),
    ]


def test_calculate_tokens_counts_non_empty_text() -> None:
    messages = [
        _message("system", "System prompt"),
        _message("user", "Inspect src/tools/lsp_tool.rs"),
    ]

    token_count = calculate_tokens(messages)

    assert token_count > 0


def test_compact_history_preserves_system_prompt_and_recent_three_turns() -> None:
    history = _build_history()

    result = compact_history(history, max_tokens=120)

    assert isinstance(result, ContextCompactionResult)
    assert result.compacted_messages[0] == history[0]
    recent_slice = history[-6:]
    assert result.compacted_messages[-6:] == recent_slice


def test_compact_history_preserves_dangerous_and_hardware_messages_verbatim() -> None:
    history = _build_history()

    result = compact_history(history, max_tokens=120)
    contents = [message["content"] for message in result.compacted_messages]

    assert any("DANGEROUS: flash confirmed on /dev/ttyUSB0" in content for content in contents)
    assert any("MCU voltage rail verified at 3.3V" in content for content in contents)


def test_compact_history_summarizes_safe_middle_before_pruning() -> None:
    history = _build_history()

    result = compact_history(history, max_tokens=140)
    contents = [message["content"] for message in result.compacted_messages]

    assert result.summary_count >= 1
    assert any(content.startswith("[SUMMARY]") for content in contents)
    assert not any("Old safe reply 1: history handles trimming" in content for content in contents)


def test_compact_history_prunes_oldest_safe_content_if_still_over_budget() -> None:
    ancient_reply = "Ancient safe reply 3 " * 40
    history = _build_history()[:-6] + [
        _message("user", "Ancient safe turn 3 " * 40),
        _message("assistant", ancient_reply),
    ] + _build_history()[-6:]

    result = compact_history(history, max_tokens=60)

    assert result.pruned_count >= 1
    assert result.compacted_tokens < result.original_tokens
    contents = [message["content"] for message in result.compacted_messages]
    assert ancient_reply not in contents


def test_compact_history_does_not_mutate_original_history() -> None:
    history = _build_history()
    snapshot = deepcopy(history)

    compact_history(history, max_tokens=120)

    assert history == snapshot


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "[Tool results]\n"
            '<tool_result name="shell">DANGEROUS: erase confirmed</tool_result>',
            True,
        ),
        ("Hardware state confirmation: servo locked and power rail stable.", True),
        ("Normal tool output: grep matched 3 files.", False),
    ],
)
def test_safety_classification_drives_exact_preservation(
    content: str,
    expected: bool,
) -> None:
    history = [
        _message("system", "System prompt"),
        _message("user", "Old turn"),
        _message("assistant", content),
        _message("user", "Recent turn A"),
        _message("assistant", "Recent reply A"),
        _message("user", "Recent turn B"),
        _message("assistant", "Recent reply B"),
        _message("user", "Recent turn C"),
        _message("assistant", "Recent reply C"),
    ]

    result = compact_history(history, max_tokens=20)
    contents = [message["content"] for message in result.compacted_messages]

    if expected:
        assert content in contents
    else:
        assert content not in contents or any(text.startswith("[SUMMARY]") for text in contents)
