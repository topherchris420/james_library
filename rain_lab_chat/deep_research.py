"""Deep research engine — multi-stage, evidence-first search protocol.

Replaces single-shot web search with a staged pipeline:
  1. Recent/bleeding-edge queries
  2. Foundational/review queries
  3. Contrarian/limitation queries

Then extracts evidence, detects contradictions, and synthesizes a
structured research brief for agent context.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from rain_lab_chat._logging import get_logger
from rain_lab_chat._sanitize import sanitize_text
from rain_lab_chat.config import Config

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class EvidenceItem:
    """A single piece of extracted evidence from search results."""

    claim: str
    source: str
    query_stage: str  # "recent", "foundational", or "contrarian"
    confidence: float = 0.7


@dataclass
class ResearchBrief:
    """Structured output of a deep research run."""

    topic: str
    evidence: List[EvidenceItem] = field(default_factory=list)
    contradictions: List[Tuple[EvidenceItem, EvidenceItem, str]] = field(
        default_factory=list
    )
    summary: str = ""
    query_count: int = 0
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Query templates per stage
# ---------------------------------------------------------------------------

_STAGE_TEMPLATES: Dict[str, List[str]] = {
    "recent": [
        "{topic} recent advances 2025 2026",
        "{topic} latest research findings",
        "{topic} new developments breakthroughs",
    ],
    "foundational": [
        "{topic} theory fundamentals review",
        "{topic} established principles overview",
        "{topic} foundational papers key results",
    ],
    "contrarian": [
        "{topic} criticism limitations problems",
        "{topic} challenges open questions debate",
        "{topic} counterarguments alternative explanations",
    ],
}

# How many templates to use per stage at each depth level
_DEPTH_QUERIES: Dict[str, int] = {
    "quick": 1,     # 3 total queries (1 per stage)
    "default": 2,   # 6 total queries (2 per stage)
    "deep": 3,      # 9 total queries (3 per stage)
}


# ---------------------------------------------------------------------------
# Evidence extraction helpers
# ---------------------------------------------------------------------------

# Patterns that signal a factual/quantitative claim
_CLAIM_PATTERNS = [
    # Sentences with numbers + units
    re.compile(
        r"([A-Z][^.!?]{10,}?\d+\.?\d*\s*(?:Hz|kHz|MHz|GHz|eV|keV|MeV|GeV|"
        r"nm|µm|mm|cm|m|km|K|°C|°F|W|kW|MW|GW|J|kg|g|mol|s|ms|µs|ns|"
        r"Pa|bar|atm|dB|%|percent|fold|times|order[s]? of magnitude)[^.!?]*\.)",
        re.IGNORECASE,
    ),
    # "X found/showed/demonstrated that ..." sentences
    re.compile(
        r"((?:researchers?|study|studies|team|group|analysis|experiment|results?|data|evidence)\s+"
        r"(?:found|showed?|demonstrated?|revealed?|indicated?|confirmed?|suggested?)\s+"
        r"[^.!?]{15,}\.)",
        re.IGNORECASE,
    ),
    # Comparative claims
    re.compile(
        r"((?:compared to|relative to|in contrast|unlike|whereas|however)\s+[^.!?]{15,}\.)",
        re.IGNORECASE,
    ),
]


def _extract_evidence_from_text(
    text: str, stage: str, source: str
) -> List[EvidenceItem]:
    """Pull claim-like sentences from a search result body."""
    items: List[EvidenceItem] = []
    seen: set = set()

    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            claim = match.group(1).strip()
            # Skip very short or duplicate claims
            if len(claim) < 30 or claim in seen:
                continue
            seen.add(claim)
            items.append(
                EvidenceItem(
                    claim=claim,
                    source=source,
                    query_stage=stage,
                    confidence=0.7,
                )
            )

    # Fallback: if no patterns matched, grab the first substantive sentence
    if not items and len(text) > 50:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for sent in sentences[:3]:
            sent = sent.strip()
            if len(sent) > 40:
                items.append(
                    EvidenceItem(
                        claim=sent,
                        source=source,
                        query_stage=stage,
                        confidence=0.5,
                    )
                )
                break

    return items


# ---------------------------------------------------------------------------
# Contradiction detection
# ---------------------------------------------------------------------------

# Word sets that commonly indicate opposing positions
_POSITIVE_SIGNALS = {
    "confirms", "supports", "validates", "demonstrates", "proves",
    "increases", "enhances", "improves", "enables", "achieves",
    "successful", "effective", "significant", "breakthrough",
}
_NEGATIVE_SIGNALS = {
    "refutes", "contradicts", "disproves", "challenges", "undermines",
    "decreases", "reduces", "limits", "prevents", "fails",
    "unsuccessful", "ineffective", "insignificant", "overstated",
    "criticism", "limitation", "problem", "flaw", "weakness",
}


def _detect_contradictions(
    evidence: List[EvidenceItem],
) -> List[Tuple[EvidenceItem, EvidenceItem, str]]:
    """Find pairs of evidence items that appear to contradict each other."""
    contradictions: List[Tuple[EvidenceItem, EvidenceItem, str]] = []

    for i, a in enumerate(evidence):
        a_words = set(a.claim.lower().split())
        a_positive = a_words & _POSITIVE_SIGNALS
        a_negative = a_words & _NEGATIVE_SIGNALS

        for b in evidence[i + 1 :]:
            # Only flag cross-stage contradictions (same-stage is just noise)
            if a.query_stage == b.query_stage:
                continue

            b_words = set(b.claim.lower().split())
            b_positive = b_words & _POSITIVE_SIGNALS
            b_negative = b_words & _NEGATIVE_SIGNALS

            # Check for sentiment polarity flip
            if (a_positive and b_negative) or (a_negative and b_positive):
                # Require some topical overlap (at least 2 shared content words)
                shared = (a_words & b_words) - {
                    "the", "a", "an", "is", "are", "was", "were", "in", "on",
                    "of", "to", "and", "or", "that", "this", "it", "for",
                    "with", "by", "from", "at", "as", "not", "be", "has",
                    "have", "had", "but", "if", "they", "their", "than",
                }
                if len(shared) >= 2:
                    reason = (
                        f"Polarity conflict on '{', '.join(list(shared)[:3])}': "
                        f"[{a.query_stage}] vs [{b.query_stage}]"
                    )
                    contradictions.append((a, b, reason))

    return contradictions


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class DeepResearchEngine:
    """Multi-stage research engine that wraps WebSearchManager."""

    def __init__(self, web_search_manager, config: Optional[Config] = None):
        self._ws = web_search_manager
        self._config = config

    def research(
        self,
        topic: str,
        depth: str = "default",
    ) -> ResearchBrief:
        """Run staged research on *topic* and return a structured brief.

        Parameters
        ----------
        topic : str
            The research question or subject.
        depth : str
            One of ``"quick"`` (3 queries), ``"default"`` (6), ``"deep"`` (9).
        """
        queries_per_stage = _DEPTH_QUERIES.get(depth, 2)

        brief = ResearchBrief(
            topic=topic,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        all_evidence: List[EvidenceItem] = []

        # --- Stage 1-3: run queries ---
        for stage_name, templates in _STAGE_TEMPLATES.items():
            stage_queries = templates[:queries_per_stage]
            for template in stage_queries:
                query = template.format(topic=topic)
                log.debug("Deep research [%s]: %s", stage_name, query)

                formatted, raw_results = self._ws.search(query, verbose=False)
                brief.query_count += 1

                # Extract evidence from each result
                for result in raw_results:
                    body = result.get("body", "")
                    title = result.get("title", "")
                    source = result.get("href", title)
                    if body:
                        items = _extract_evidence_from_text(body, stage_name, source)
                        all_evidence.extend(items)

                # Small delay between queries to avoid rate-limiting
                if brief.query_count < queries_per_stage * 3:
                    time.sleep(0.3)

        brief.evidence = all_evidence

        # --- Contradiction check ---
        brief.contradictions = _detect_contradictions(all_evidence)

        # --- Synthesize ---
        brief.summary = self._synthesize(topic, all_evidence, brief.contradictions)

        log.info(
            "Deep research complete: %d queries, %d evidence items, %d contradictions",
            brief.query_count,
            len(all_evidence),
            len(brief.contradictions),
        )

        return brief

    def _synthesize(
        self,
        topic: str,
        evidence: List[EvidenceItem],
        contradictions: List[Tuple[EvidenceItem, EvidenceItem, str]],
    ) -> str:
        """Build a formatted research brief string for agent context."""
        sections: List[str] = []
        sections.append(f"\n### DEEP RESEARCH BRIEF: {topic}")
        sections.append(
            f"*Searched {len(evidence)} evidence items across 3 research angles*\n"
        )

        # Group evidence by stage
        for stage_name, stage_label in [
            ("recent", "RECENT / BLEEDING-EDGE"),
            ("foundational", "FOUNDATIONAL / ESTABLISHED"),
            ("contrarian", "CRITICISM / LIMITATIONS"),
        ]:
            stage_items = [e for e in evidence if e.query_stage == stage_name]
            if not stage_items:
                continue

            sections.append(f"**{stage_label}** ({len(stage_items)} items)")
            for item in stage_items[:5]:  # Cap per-stage to avoid context bloat
                source_short = item.source[:60] if item.source else "unknown"
                sections.append(f"- {item.claim} [source: {source_short}]")
            if len(stage_items) > 5:
                sections.append(f"  *(+{len(stage_items) - 5} more)*")
            sections.append("")

        # Contradictions section
        if contradictions:
            sections.append(
                f"**⚠ CONTRADICTIONS DETECTED** ({len(contradictions)} conflicts)"
            )
            for a, b, reason in contradictions[:3]:
                sections.append(f"- {reason}")
                sections.append(f"  A: \"{a.claim[:80]}...\"")
                sections.append(f"  B: \"{b.claim[:80]}...\"")
            if len(contradictions) > 3:
                sections.append(f"  *(+{len(contradictions) - 3} more)*")
            sections.append("")

        if not evidence:
            sections.append(
                "*No structured evidence extracted. "
                "Web search may be unavailable or the topic too niche.*"
            )

        return "\n".join(sections)
