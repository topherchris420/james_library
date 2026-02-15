"""Tests for the rain_metrics eval framework.

Validates that a mock session produces all three measurable signals:
  1. citation_accuracy   (float, 0–1, 2 decimal places)
  2. novel_claim_density  (float, 0–1, 2 decimal places)
  3. critique_change_rate (float, 0–1, 2 decimal places)

Also confirms JSONL persistence and edge-case behaviour.
"""

import json
from pathlib import Path

from rain_metrics import (
    MetricsTracker,
    compute_citation_accuracy,
    compute_critique_change_rate,
    compute_novel_claim_density,
    extract_claims,
    extract_quotes,
)

# ── fixtures ──────────────────────────────────────────────────────────────

SAMPLE_CORPUS = {
    "DRR_paper.md": (
        "Dynamic Resonance Rooting shows that heat flux scales as U-cubed "
        "at high frequencies. The geometric coupling between frequency and "
        "spatial pattern produces self-similar structures. Thermal limits "
        "are reached above 100 kHz under continuous load."
    ),
    "Coherence_Depth.md": (
        "The coherence depth function C_alpha(u) measures how deep patterns "
        "persist in oscillatory fields. Spectral spacing reveals hidden "
        "geometric structure in the data."
    ),
}

AGENT_RESPONSE_WITH_CITATIONS = (
    'James, that\'s fascinating. The DRR paper says "heat flux scales as '
    'U-cubed at high frequencies" which implies the thermal ceiling is '
    "real. But Elena, the energy density you'd need suggests this is "
    "impractical at scale."
)

AGENT_RESPONSE_NOVEL = (
    "I think the resonance lattice produces a phase-locked harmonic cascade "
    "that results in spontaneous symmetry restoration. This implies a new "
    "class of topological insulators."
)


# ── extract helpers ───────────────────────────────────────────────────────


def test_extract_quotes_finds_double_quoted():
    quotes = extract_quotes(AGENT_RESPONSE_WITH_CITATIONS)
    assert len(quotes) >= 1
    assert any("heat flux" in q.lower() for q in quotes)


def test_extract_quotes_skips_short():
    assert extract_quotes('She said "yes" and left.') == []


def test_extract_claims_finds_declarative():
    claims = extract_claims(AGENT_RESPONSE_NOVEL)
    assert len(claims) >= 1
    assert any("implies" in c.lower() or "results in" in c.lower() for c in claims)


# ── signal 1: citation accuracy ───────────────────────────────────────────


def test_citation_accuracy_matched():
    quotes = ["heat flux scales as U-cubed at high frequencies"]
    acc = compute_citation_accuracy(quotes, SAMPLE_CORPUS)
    assert acc > 0.0, "exact corpus quote should match"


def test_citation_accuracy_unmatched():
    quotes = ["quantum gravity unifies all four fundamental forces"]
    acc = compute_citation_accuracy(quotes, SAMPLE_CORPUS)
    assert acc == 0.0


def test_citation_accuracy_empty():
    assert compute_citation_accuracy([], SAMPLE_CORPUS) == 0.0


def test_citation_accuracy_precision():
    """Value must round to two decimal places."""
    quotes = ["heat flux scales as U-cubed at high frequencies", "totally made up"]
    acc = compute_citation_accuracy(quotes, SAMPLE_CORPUS)
    assert acc == round(acc, 2)


# ── signal 2: novel-claim density ─────────────────────────────────────────


def test_novel_claim_density_novel():
    claims = ["This implies a new class of topological insulators."]
    density = compute_novel_claim_density(claims, SAMPLE_CORPUS)
    assert density > 0.0, "novel claim should not match corpus"


def test_novel_claim_density_grounded():
    claims = ["heat flux scales as U-cubed at high frequencies."]
    density = compute_novel_claim_density(claims, SAMPLE_CORPUS)
    assert density == 0.0, "verbatim corpus claim should NOT be novel"


def test_novel_claim_density_empty():
    assert compute_novel_claim_density([], SAMPLE_CORPUS) == 0.0


# ── signal 3: critique change rate ────────────────────────────────────────


def test_critique_change_rate_changed():
    pairs = [("The sky is blue.", "The sky is a deep cerulean hue caused by scattering.")]
    rate = compute_critique_change_rate(pairs)
    assert rate > 0.0


def test_critique_change_rate_unchanged():
    pairs = [("The sky is blue.", "The sky is blue.")]
    rate = compute_critique_change_rate(pairs)
    assert rate == 0.0


def test_critique_change_rate_empty():
    assert compute_critique_change_rate([]) == 0.0


# ── MetricsTracker integration ────────────────────────────────────────────


def test_tracker_full_session(tmp_path):
    """A mock session must produce all three signals in the JSONL record."""
    log_file = tmp_path / "metrics_log.jsonl"

    tracker = MetricsTracker(
        session_id="test-001",
        topic="DRR thermal limits",
        model="qwen2.5-coder-7b-instruct",
        recursive_depth=2,
        log_path=log_file,
    )
    tracker.set_corpus(SAMPLE_CORPUS)

    # Simulate turns
    tracker.record_turn("James", AGENT_RESPONSE_WITH_CITATIONS)
    tracker.record_turn("Elena", AGENT_RESPONSE_NOVEL)

    # Simulate critique passes
    tracker.record_critique(
        "The thermal limits are real.",
        "The thermal limits are real, confirmed by DRR heat flux U^3 scaling.",
    )
    tracker.record_critique(
        "I think this works.",
        "I think this works.",  # unchanged
    )

    record = tracker.finalize()

    # -- structure checks
    assert log_file.exists()
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    persisted = json.loads(lines[0])

    for key in (
        "session_id",
        "timestamp",
        "topic",
        "turns",
        "citation_accuracy",
        "novel_claim_density",
        "critique_change_rate",
        "model",
        "recursive_depth",
    ):
        assert key in record, f"Missing key: {key}"
        assert key in persisted, f"Missing key in JSONL: {key}"

    # -- value checks
    assert record["session_id"] == "test-001"
    assert record["turns"] == 2
    assert record["model"] == "qwen2.5-coder-7b-instruct"
    assert record["recursive_depth"] == 2
    assert 0.0 <= record["citation_accuracy"] <= 1.0
    assert 0.0 <= record["novel_claim_density"] <= 1.0
    assert 0.0 <= record["critique_change_rate"] <= 1.0

    # precision — two decimal places
    for key in ("citation_accuracy", "novel_claim_density", "critique_change_rate"):
        assert record[key] == round(record[key], 2), f"{key} not 2dp"


def test_tracker_appends_multiple_sessions(tmp_path):
    """Each finalize() call should append exactly one JSONL line."""
    log_file = tmp_path / "metrics_log.jsonl"

    for i in range(3):
        t = MetricsTracker(
            session_id=f"s-{i}",
            topic="test",
            log_path=log_file,
        )
        t.record_turn("James", "Hello team.")
        t.finalize()

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 3


def test_tracker_summary_does_not_write(tmp_path):
    """summary() should return metrics without writing to disk."""
    log_file = tmp_path / "metrics_log.jsonl"
    t = MetricsTracker(session_id="x", topic="t", log_path=log_file)
    t.record_turn("Elena", "Test.")
    result = t.summary()
    assert "citation_accuracy" in result
    assert not log_file.exists()
