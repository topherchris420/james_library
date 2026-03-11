"""Auto-summarization for long meeting transcripts.

When the conversation history grows past a configurable token threshold,
older turns are summarized into a compact paragraph via the LLM and the
full evicted transcript is archived to ``meeting_archives/``.

Inspired by the SummarizationMiddleware pattern in LangChain DeepAgents.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    import openai

    from rain_lab_chat.config import Config

log = logging.getLogger(__name__)

# ── Token estimation ─────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Fast approximate token count (≈ 1 token per 4 characters)."""
    return max(1, len(text) // 4)


def estimate_history_tokens(history: List[str]) -> int:
    """Estimate total token count across all history entries."""
    return sum(estimate_tokens(entry) for entry in history)


# ── Summarization prompt ─────────────────────────────────────────────────

_SUMMARIZE_PROMPT = (
    "Summarize the following meeting transcript concisely. "
    "Preserve ALL of the following:\n"
    "- Speaker names and their key positions\n"
    "- Factual claims and cited sources\n"
    "- Key disagreements and open questions\n"
    "- Action items or next steps mentioned\n\n"
    "Return ONLY the summary paragraph, nothing else."
)

_SUMMARY_PREFIX = "[MEETING SUMMARY — earlier turns condensed]"


# ── Archive helper ───────────────────────────────────────────────────────

def _archive_evicted(evicted: List[str], archive_dir: Path) -> Optional[Path]:
    """Write evicted transcript entries to a timestamped file."""
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = archive_dir / f"evicted_history_{ts}.md"
        content = (
            f"# Evicted Meeting History — {ts}\n\n"
            + "\n\n".join(evicted)
        )
        path.write_text(content, encoding="utf-8")
        log.info("Archived %d evicted turns to %s", len(evicted), path)
        return path
    except Exception as exc:
        log.warning("Failed to archive evicted history: %s", exc)
        return None


# ── Core entry point ─────────────────────────────────────────────────────

def maybe_summarize(
    client: openai.OpenAI,
    config: Config,
    history_log: List[str],
    archive_dir: Path,
    model_name: Optional[str] = None,
) -> List[str]:
    """Summarize older history if token count exceeds the configured threshold.

    Returns a new list that should replace ``history_log``.  If no
    summarization is needed (or if the LLM call fails), the original list
    is returned unchanged.

    Args:
        client: OpenAI-compatible client for the summarization LLM call.
        config: RAIN Lab config with summarization settings.
        history_log: The mutable list of ``"Speaker: text"`` entries.
        archive_dir: Directory to write evicted history files.
        model_name: Override model name (uses ``config.model_name`` by default).
    """
    if not getattr(config, "summarization_enabled", True):
        return history_log

    trigger = getattr(config, "summarization_trigger_tokens", 3000)
    keep = getattr(config, "summarization_keep_recent", 4)

    total_tokens = estimate_history_tokens(history_log)
    if total_tokens < trigger:
        return history_log

    # Never summarize if there's nothing to evict
    if len(history_log) <= keep:
        return history_log

    evicted = history_log[:-keep]
    recent = history_log[-keep:]

    log.info(
        "Summarizing: %d total tokens, evicting %d turns, keeping %d recent",
        total_tokens,
        len(evicted),
        len(recent),
    )

    # Archive the full evicted text before summarizing
    _archive_evicted(evicted, archive_dir)

    # Build the text to summarize
    evicted_text = "\n\n".join(evicted)

    try:
        response = client.chat.completions.create(
            model=model_name or config.model_name,
            messages=[
                {"role": "system", "content": _SUMMARIZE_PROMPT},
                {"role": "user", "content": evicted_text},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        summary = response.choices[0].message.content.strip()
    except Exception as exc:
        log.warning("Summarization LLM call failed (%s); keeping full history", exc)
        return history_log

    if not summary:
        log.warning("LLM returned empty summary; keeping full history")
        return history_log

    summary_entry = f"{_SUMMARY_PREFIX}\n{summary}"

    log.info("Summarization complete — compressed %d turns into 1 summary", len(evicted))

    return [summary_entry] + recent
