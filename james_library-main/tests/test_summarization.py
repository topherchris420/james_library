"""Tests for rain_lab_chat.summarization — auto-compaction of meeting history."""

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from rain_lab_chat.summarization import (
    _SUMMARY_PREFIX,
    estimate_history_tokens,
    estimate_tokens,
    maybe_summarize,
)


# ── Helpers ──────────────────────────────────────────────────────────────


@dataclass
class _MinimalConfig:
    """Minimal stand-in for ``Config`` with only the fields summarization needs."""

    summarization_enabled: bool = True
    summarization_trigger_tokens: int = 100
    summarization_keep_recent: int = 2
    model_name: str = "test-model"


def _make_mock_client(summary_text: str = "Summary of earlier discussion."):
    """Return a mock ``openai.OpenAI`` that returns *summary_text*."""
    client = MagicMock()
    choice = SimpleNamespace(message=SimpleNamespace(content=summary_text), finish_reason="stop")
    response = SimpleNamespace(choices=[choice])
    client.chat.completions.create.return_value = response
    return client


def _long_history(n: int = 20) -> list[str]:
    """Generate a history list whose token count will exceed any small threshold."""
    return [f"Agent{i % 4}: " + ("word " * 80) for i in range(n)]


# ── Tests ────────────────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 1  # min of 1

    def test_approximation(self):
        text = "a" * 400
        # Expect ~100 tokens for 400 chars
        assert 90 <= estimate_tokens(text) <= 110

    def test_history_sum(self):
        history = ["hello world", "foo bar baz"]
        total = estimate_history_tokens(history)
        assert total == estimate_tokens("hello world") + estimate_tokens("foo bar baz")


class TestMaybeSummarize:
    def test_no_summarize_below_threshold(self, tmp_path):
        """Short history stays unchanged."""
        config = _MinimalConfig(summarization_trigger_tokens=99999)
        client = _make_mock_client()
        history = ["James: Hello", "Jasmine: Hi"]

        result = maybe_summarize(client, config, history, archive_dir=tmp_path)

        assert result == history
        client.chat.completions.create.assert_not_called()

    def test_summarizes_above_threshold(self, tmp_path):
        """History above threshold is summarized; archive file is created."""
        config = _MinimalConfig(summarization_trigger_tokens=50, summarization_keep_recent=2)
        client = _make_mock_client("Condensed summary of the meeting.")
        history = _long_history(10)

        result = maybe_summarize(client, config, history, archive_dir=tmp_path)

        # Should start with summary and end with the 2 most recent entries
        assert len(result) == 3  # 1 summary + 2 kept
        assert _SUMMARY_PREFIX in result[0]
        assert "Condensed summary" in result[0]
        assert result[1] == history[-2]
        assert result[2] == history[-1]

        # LLM was called once
        client.chat.completions.create.assert_called_once()

        # Archive file was created
        archives = list(tmp_path.glob("evicted_history_*.md"))
        assert len(archives) == 1
        archive_content = archives[0].read_text(encoding="utf-8")
        assert "Agent0:" in archive_content

    def test_summarize_disabled(self, tmp_path):
        """When disabled, history is returned unchanged."""
        config = _MinimalConfig(summarization_enabled=False, summarization_trigger_tokens=1)
        client = _make_mock_client()
        history = _long_history(10)

        result = maybe_summarize(client, config, history, archive_dir=tmp_path)

        assert result is history  # exact same object
        client.chat.completions.create.assert_not_called()

    def test_llm_failure_returns_original(self, tmp_path):
        """If LLM call fails, history is returned unchanged (no crash)."""
        config = _MinimalConfig(summarization_trigger_tokens=50, summarization_keep_recent=2)
        client = _make_mock_client()
        client.chat.completions.create.side_effect = Exception("connection refused")
        history = _long_history(10)

        result = maybe_summarize(client, config, history, archive_dir=tmp_path)

        assert result is history  # unchanged

    def test_empty_summary_returns_original(self, tmp_path):
        """If LLM returns empty string, history is unchanged."""
        config = _MinimalConfig(summarization_trigger_tokens=50, summarization_keep_recent=2)
        client = _make_mock_client("")
        history = _long_history(10)

        result = maybe_summarize(client, config, history, archive_dir=tmp_path)

        assert result is history
