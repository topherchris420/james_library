# -*- coding: utf-8 -*-
"""rain_metrics — session-level eval signals for R.A.I.N. Lab meetings.

Three measurable signals are tracked per session:

1. **Citation accuracy rate** — % of quoted spans that fuzzy-match a loaded
   paper at >= 80% similarity.
2. **Novel-claim density** — proportion of agent claims *not* traceable to
   any loaded paper (agent-generated hypotheses).
3. **Critique-to-accept ratio** — in recursive-intellect mode, the fraction
   of critique passes that actually changed the output.

Usage
-----
>>> tracker = MetricsTracker(session_id="abc", topic="DRR", model="qwen2.5")
>>> tracker.record_turn("Elena", response, citation_analysis)
>>> tracker.record_critique(pre_text, post_text)
>>> tracker.finalize()          # writes one line to metrics_log.jsonl
>>> tracker.summary()           # returns a dict
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

__all__ = [
    "MetricsTracker",
    "compute_citation_accuracy",
    "compute_novel_claim_density",
    "compute_critique_change_rate",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLAIM_PATTERN = re.compile(
    r"(?:^|\.\s+)"           # start of text or sentence boundary
    r"("
    r"[A-Z][^.!?]*?"         # sentence starting with uppercase
    r"(?:"
    r"scales?\s+as"          # "scales as X^3"
    r"|implies?\b"
    r"|predicts?\b"
    r"|suggests?\b"
    r"|requires?\b"
    r"|yields?\b"
    r"|produces?\b"
    r"|causes?\b"
    r"|leads?\s+to"
    r"|results?\s+in"
    r"|means?\s+that"
    r"|shows?\s+that"
    r"|is\s+proportional"
    r"|demonstrates?\b"
    r")"
    r"[^.!?]+"               # rest of the sentence
    r"[.!?]"
    r")",
    re.MULTILINE,
)


def _similarity(a: str, b: str) -> float:
    """Return SequenceMatcher ratio between two strings (0..1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def extract_quotes(text: str) -> List[str]:
    """Pull quoted spans (>3 words) from *text*."""
    quotes = re.findall(r'"([^"]+)"', text)
    quotes.extend(re.findall(r"\u201c([^\u201d]+)\u201d", text))  # smart quotes
    return [q for q in quotes if len(q.split()) > 3]


def extract_claims(text: str) -> List[str]:
    """Heuristically extract declarative claim sentences from *text*."""
    return [m.strip() for m in _CLAIM_PATTERN.findall(text) if len(m.split()) > 4]


# ---------------------------------------------------------------------------
# Signal 1 — Citation accuracy
# ---------------------------------------------------------------------------


def compute_citation_accuracy(
    quotes: List[str],
    corpus_texts: Dict[str, str],
    threshold: float = 0.80,
) -> float:
    """Return fraction of *quotes* that fuzzy-match any corpus document.

    Parameters
    ----------
    quotes : list[str]
        Quoted spans extracted from an agent response.
    corpus_texts : dict[str, str]
        ``{paper_name: full_text}`` mapping of loaded papers.
    threshold : float
        Minimum ``SequenceMatcher.ratio()`` to count as a match (0–1).

    Returns
    -------
    float
        Value in ``[0.0, 1.0]``, or ``0.0`` when no quotes are present.
    """
    if not quotes:
        return 0.0
    matched = 0
    for quote in quotes:
        for _name, text in corpus_texts.items():
            # Sliding-window fuzzy search in the paper text
            words = text.lower().split()
            q_words = quote.lower().split()
            q_len = len(q_words)
            if q_len == 0:
                continue
            for i in range(max(1, len(words) - q_len + 1)):
                window = " ".join(words[i : i + q_len])
                if _similarity(quote, window) >= threshold:
                    matched += 1
                    break
            else:
                continue
            break  # already matched this quote
    return round(matched / len(quotes), 2)


# ---------------------------------------------------------------------------
# Signal 2 — Novel-claim density
# ---------------------------------------------------------------------------


def compute_novel_claim_density(
    claims: List[str],
    corpus_texts: Dict[str, str],
    threshold: float = 0.80,
) -> float:
    """Return fraction of *claims* NOT traceable to any loaded paper.

    A claim is considered novel if no sliding window in the corpus matches it
    above *threshold*.
    """
    if not claims:
        return 0.0
    novel = 0
    for claim in claims:
        found_in_corpus = False
        for _name, text in corpus_texts.items():
            words = text.lower().split()
            c_words = claim.lower().split()
            c_len = len(c_words)
            if c_len == 0:
                continue
            for i in range(max(1, len(words) - c_len + 1)):
                window = " ".join(words[i : i + c_len])
                if _similarity(claim, window) >= threshold:
                    found_in_corpus = True
                    break
            if found_in_corpus:
                break
        if not found_in_corpus:
            novel += 1
    return round(novel / len(claims), 2)


# ---------------------------------------------------------------------------
# Signal 3 — Critique-to-accept ratio
# ---------------------------------------------------------------------------


def compute_critique_change_rate(
    critique_pairs: List[tuple[str, str]],
    change_threshold: float = 0.05,
) -> float:
    """Return fraction of (pre, post) critique pairs where the text changed.

    Parameters
    ----------
    critique_pairs : list[tuple[str, str]]
        Each element is ``(text_before_critique, text_after_critique)``.
    change_threshold : float
        Minimum ``1 - similarity`` to count as a meaningful change.
    """
    if not critique_pairs:
        return 0.0
    changed = sum(
        1
        for pre, post in critique_pairs
        if (1.0 - _similarity(pre, post)) >= change_threshold
    )
    return round(changed / len(critique_pairs), 2)


# ---------------------------------------------------------------------------
# Session tracker
# ---------------------------------------------------------------------------


class MetricsTracker:
    """Accumulates per-turn data and writes a single JSONL record on finalize."""

    def __init__(
        self,
        session_id: str,
        topic: str,
        model: str = "unknown",
        recursive_depth: int = 0,
        log_path: Optional[Path] = None,
    ):
        self.session_id = session_id
        self.topic = topic
        self.model = model
        self.recursive_depth = recursive_depth
        self.log_path = log_path or Path("metrics_log.jsonl")

        self._turn_count = 0
        self._all_quotes: List[str] = []
        self._all_claims: List[str] = []
        self._corpus_texts: Dict[str, str] = {}
        self._critique_pairs: List[tuple[str, str]] = []

    # -- recording API -----------------------------------------------------

    def set_corpus(self, corpus_texts: Dict[str, str]) -> None:
        """Provide the loaded paper corpus for citation/novelty checks."""
        self._corpus_texts = corpus_texts

    def record_turn(
        self,
        agent_name: str,
        response: str,
        citation_analysis: Optional[Dict] = None,
    ) -> None:
        """Record one agent turn."""
        self._turn_count += 1
        self._all_quotes.extend(extract_quotes(response))
        self._all_claims.extend(extract_claims(response))

    def record_critique(self, pre_text: str, post_text: str) -> None:
        """Record one critique→revision pass."""
        self._critique_pairs.append((pre_text, post_text))

    # -- computation -------------------------------------------------------

    def summary(self) -> Dict:
        """Compute and return the metrics dict (does NOT write to disk)."""
        return {
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topic": self.topic,
            "turns": self._turn_count,
            "citation_accuracy": compute_citation_accuracy(
                self._all_quotes, self._corpus_texts
            ),
            "novel_claim_density": compute_novel_claim_density(
                self._all_claims, self._corpus_texts
            ),
            "critique_change_rate": compute_critique_change_rate(
                self._critique_pairs
            ),
            "model": self.model,
            "recursive_depth": self.recursive_depth,
        }

    # -- persistence -------------------------------------------------------

    def finalize(self) -> Dict:
        """Compute metrics, append one JSONL line, and return the dict."""
        record = self.summary()
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
