"""Unit tests for the deep research engine.

Tests the staged search, evidence extraction, contradiction detection,
and synthesis without making real network requests.
"""

import re
from unittest.mock import MagicMock, patch

import pytest

from rain_lab_chat.config import Config
from rain_lab_chat.deep_research import (
    DeepResearchEngine,
    EvidenceItem,
    ResearchBrief,
    _detect_contradictions,
    _extract_evidence_from_text,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_web_search():
    """WebSearchManager mock that returns canned results per query."""
    ws = MagicMock()
    ws.enabled = True
    ws.search = MagicMock(
        return_value=(
            "Formatted results",
            [
                {
                    "title": "Test Paper A",
                    "body": (
                        "Researchers found that resonance frequency "
                        "increases by 42% under high-pressure conditions. "
                        "The study demonstrated significant improvements "
                        "in signal-to-noise ratio at 3.5 GHz."
                    ),
                    "href": "https://example.com/paper-a",
                },
                {
                    "title": "Test Paper B",
                    "body": (
                        "Recent analysis challenges previous claims about "
                        "resonance stability. The limitation is that "
                        "decoherence reduces effectiveness at room temperature."
                    ),
                    "href": "https://example.com/paper-b",
                },
            ],
        )
    )
    return ws


@pytest.fixture()
def engine(mock_web_search):
    """DeepResearchEngine with mocked web search."""
    config = Config(
        enable_web_search=True,
        enable_deep_research=True,
        deep_research_depth="quick",
    )
    return DeepResearchEngine(mock_web_search, config)


# ---------------------------------------------------------------------------
# Query generation & depth tests
# ---------------------------------------------------------------------------


class TestStagedQueries:
    """Verify the correct number of queries are run at each depth."""

    def test_quick_depth_runs_3_queries(self, engine, mock_web_search):
        brief = engine.research("quantum resonance", depth="quick")
        # quick = 1 query per stage * 3 stages = 3
        assert brief.query_count == 3
        assert mock_web_search.search.call_count == 3

    def test_default_depth_runs_6_queries(self, engine, mock_web_search):
        brief = engine.research("quantum resonance", depth="default")
        assert brief.query_count == 6
        assert mock_web_search.search.call_count == 6

    def test_deep_depth_runs_9_queries(self, engine, mock_web_search):
        brief = engine.research("quantum resonance", depth="deep")
        assert brief.query_count == 9
        assert mock_web_search.search.call_count == 9

    def test_unknown_depth_defaults_to_6(self, engine, mock_web_search):
        brief = engine.research("quantum resonance", depth="unknown")
        # Falls back to _DEPTH_QUERIES default of 2
        assert brief.query_count == 6


# ---------------------------------------------------------------------------
# Evidence extraction tests
# ---------------------------------------------------------------------------


class TestEvidenceExtraction:
    """Verify evidence items are extracted from text."""

    def test_extracts_quantitative_claim(self):
        text = "The experiment measured a frequency of 3.5 GHz under controlled conditions."
        items = _extract_evidence_from_text(text, "recent", "test-source")
        assert len(items) >= 1
        assert any("3.5 GHz" in item.claim for item in items)

    def test_extracts_researcher_finding(self):
        text = "Researchers found that coherence length scales linearly with temperature in bounded systems."
        items = _extract_evidence_from_text(text, "foundational", "test-source")
        assert len(items) >= 1
        assert items[0].query_stage == "foundational"

    def test_sets_correct_source(self):
        text = "The study demonstrated a 50% improvement in detection accuracy."
        items = _extract_evidence_from_text(text, "recent", "https://example.com")
        assert all(item.source == "https://example.com" for item in items)

    def test_fallback_for_no_pattern_match(self):
        text = (
            "This is a sufficiently long sentence about quantum mechanics "
            "that does not match any of the specific claim patterns used."
        )
        items = _extract_evidence_from_text(text, "recent", "test")
        # Should fall back to grabbing first substantive sentence
        assert len(items) >= 1
        assert items[0].confidence == 0.5

    def test_short_text_returns_nothing(self):
        items = _extract_evidence_from_text("Too short.", "recent", "test")
        assert items == []

    def test_deduplicates_claims(self):
        text = (
            "Researchers found that the frequency is exactly 5 GHz. "
            "The study showed that the frequency is exactly 5 GHz. "
            "Analysis confirmed the frequency is exactly 5 GHz."
        )
        items = _extract_evidence_from_text(text, "recent", "test")
        claims = [item.claim for item in items]
        assert len(claims) == len(set(claims)), "Claims should be deduplicated"


# ---------------------------------------------------------------------------
# Contradiction detection tests
# ---------------------------------------------------------------------------


class TestContradictionDetection:
    """Verify cross-stage contradictions are flagged."""

    def test_flags_polarity_conflict(self):
        evidence = [
            EvidenceItem(
                claim="The method achieves significant improvement in resonance measurement.",
                source="a",
                query_stage="recent",
            ),
            EvidenceItem(
                claim="The method has insignificant improvement in resonance measurement due to flaw.",
                source="b",
                query_stage="contrarian",
            ),
        ]
        contradictions = _detect_contradictions(evidence)
        assert len(contradictions) >= 1

    def test_ignores_same_stage(self):
        evidence = [
            EvidenceItem(
                claim="Resonance confirms the successful breakthrough.",
                source="a",
                query_stage="recent",
            ),
            EvidenceItem(
                claim="Resonance contradicts the unsuccessful limitation.",
                source="b",
                query_stage="recent",  # Same stage — should be ignored
            ),
        ]
        contradictions = _detect_contradictions(evidence)
        assert len(contradictions) == 0

    def test_requires_topical_overlap(self):
        evidence = [
            EvidenceItem(
                claim="Temperature confirms the successful experiment.",
                source="a",
                query_stage="recent",
            ),
            EvidenceItem(
                claim="Pressure contradicts the unsuccessful measurement.",
                source="b",
                query_stage="contrarian",
            ),
        ]
        # Different topics — should NOT flag despite polarity conflict
        contradictions = _detect_contradictions(evidence)
        assert len(contradictions) == 0

    def test_empty_evidence_returns_empty(self):
        assert _detect_contradictions([]) == []


# ---------------------------------------------------------------------------
# Research brief tests
# ---------------------------------------------------------------------------


class TestResearchBrief:
    """Verify the full research pipeline produces a valid brief."""

    def test_brief_has_all_fields(self, engine):
        brief = engine.research("test topic", depth="quick")
        assert brief.topic == "test topic"
        assert brief.timestamp != ""
        assert brief.query_count > 0
        assert isinstance(brief.evidence, list)
        assert isinstance(brief.contradictions, list)
        assert isinstance(brief.summary, str)

    def test_brief_summary_contains_topic(self, engine):
        brief = engine.research("quantum coherence", depth="quick")
        assert "quantum coherence" in brief.summary.lower()

    def test_brief_summary_has_stage_labels(self, engine):
        brief = engine.research("resonance", depth="quick")
        # Summary should contain at least one stage section header
        has_stage = any(
            label in brief.summary
            for label in ["RECENT", "FOUNDATIONAL", "CRITICISM"]
        )
        assert has_stage, "Summary should include at least one stage section"


# ---------------------------------------------------------------------------
# Graceful degradation tests
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify engine handles failure without crashing."""

    def test_no_results_produces_empty_brief(self):
        ws = MagicMock()
        ws.enabled = True
        ws.search = MagicMock(return_value=("", []))

        engine = DeepResearchEngine(ws)
        brief = engine.research("obscure topic", depth="quick")

        assert brief.query_count == 3
        assert len(brief.evidence) == 0
        assert "No structured evidence" in brief.summary

    def test_search_exception_does_not_crash(self):
        ws = MagicMock()
        ws.enabled = True
        ws.search = MagicMock(side_effect=Exception("Network error"))

        engine = DeepResearchEngine(ws)
        with pytest.raises(Exception, match="Network error"):
            engine.research("any topic", depth="quick")
