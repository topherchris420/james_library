"""Offline research meeting: the no-model instant demo."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from james_library.launcher.offline_meeting import (
    AGENT_ROLES,
    DEFAULT_QUESTION,
    GROUNDING_NONE,
    GROUNDING_STRONG,
    build_offline_meeting,
)
from james_library.launcher.offline_meeting_view import render_markdown, share_highlight, stream_meeting
from james_library.utilities.citation_corpus import find_quote_span

QUESTION = "Does phase coherence in coupled oscillators predict synchronization?"

OSCILLATOR_PAPER = """Coupled Oscillators and Phase Coherence
R.A.I.N._project
Abstract
We study phase coherence in networks of coupled oscillators under weak periodic driving.
In a benchtop array of 64 oscillators, phase coherence rose to 0.91 within 12 seconds of
coupling onset.
The coupling strength required for synchronization scales with the spread of natural frequencies
across the array.
This result does not establish that phase coherence causes synchronization in larger coupled
networks.
A preregistered test would compare phase coherence in the coupled array against an uncoupled
control array under identical driving.
The oscilla-
tors in the phase coherence array were never observed to synchronize without coupling at all.
References
Example, A. Coupled oscillators and phase coherence in synchronization studies. Journal, 1999.
"""

GEOMETRY_PAPER = """Field Geometry of Synchronization
Abstract
The geometry of the phase field shapes how synchronization spreads through coupled oscillator
networks.
# This paper argues that phase coherence concentrates where the natural frequencies of
neighbouring oscillators overlap across the array.
"""


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "papers"
    root.mkdir()
    (root / "Coupled Oscillators.md").write_text(OSCILLATOR_PAPER, encoding="utf-8")
    (root / "Field Geometry.md").write_text(GEOMETRY_PAPER, encoding="utf-8")
    return root


def _speakers(meeting) -> set[str]:
    return {turn.speaker for turn in meeting.turns}


def test_every_quote_is_verbatim_at_its_cited_line(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)

    assert meeting.grounding == GROUNDING_STRONG
    assert meeting.quotes
    for quote in meeting.quotes:
        content = (corpus / quote.source).read_text(encoding="utf-8")
        span = find_quote_span(content, quote.text)
        assert span == (quote.span_start, quote.span_end)
        first_word = quote.text.split()[0]
        assert first_word in content.splitlines()[quote.line - 1]
    assert meeting.audit.passed
    assert meeting.audit.checked == len(meeting.quotes)


def test_all_four_agents_speak_in_their_roles(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)

    assert _speakers(meeting) == set(AGENT_ROLES)
    assert meeting.turns[0].speaker == "James"
    assert meeting.turns[-1].move == "next move"


def test_lenses_choose_role_appropriate_evidence(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)
    by_move = {turn.move: turn for turn in meeting.turns}

    james = by_move["frame"].quotes[0].text
    assert "0.91" in james, "James anchors on the measured result"
    elena = by_move["counter-argument"].quotes[0].text
    assert "does not establish" in elena, "Elena quotes the paper's own caveat"
    luca = by_move["connection"].quotes
    assert len(luca) == 2 and luca[0].source != luca[1].source, "Luca bridges two different papers"
    test = by_move["next move"].quotes[0].text
    assert "preregistered test" in test


def test_extraction_skips_pdf_debris_and_references(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)
    quoted = " ".join(quote.text for quote in meeting.quotes)

    assert "oscilla- tors" not in quoted
    assert "Journal" not in quoted
    # A body sentence mislabelled as a markdown heading is still quotable, minus the marker.
    from james_library.launcher.offline_meeting import _load_corpus

    texts = [sentence.text for sentence in _load_corpus(corpus).sentences]
    assert any(text.startswith("This paper argues that phase coherence") for text in texts)
    assert not any("oscilla- tors" in text or text.startswith("Example, A.") for text in texts)


def test_elena_finds_a_low_ranked_caveat_in_a_cited_paper(tmp_path: Path):
    (tmp_path / "Single Paper.md").write_text(
        "Abstract\n"
        "In a benchtop array of 64 oscillators, phase coherence rose to 0.91 within 12 seconds of coupling.\n"
        "This result does not establish that phase coherence causes synchronization in larger networks.\n"
        "Phase coherence across the oscillators decayed within seconds once the coupling was switched off.\n",
        encoding="utf-8",
    )

    meeting = build_offline_meeting("phase coherence in oscillators", tmp_path)

    elena = next(turn for turn in meeting.turns if turn.move == "counter-argument")
    assert elena.quotes and "does not establish" in elena.quotes[0].text


def test_meeting_is_deterministic(corpus: Path):
    assert build_offline_meeting(QUESTION, corpus) == build_offline_meeting(QUESTION, corpus)


def test_off_topic_question_is_not_dressed_up_as_evidence(corpus: Path):
    meeting = build_offline_meeting("a social app for roommates who never answer texts", corpus)

    assert meeting.grounding == GROUNDING_NONE
    assert meeting.quotes == ()
    assert meeting.audit.checked == 0
    assert "not in our active research context" in meeting.turns[0].coda
    assert meeting.suggestions
    assert all(question.startswith("What do we really know about") for question in meeting.suggestions)


def test_empty_library_runs_without_evidence(tmp_path: Path):
    meeting = build_offline_meeting(None, tmp_path)

    assert meeting.question == DEFAULT_QUESTION
    assert meeting.grounding == GROUNDING_NONE
    assert meeting.corpus_files == 0
    assert meeting.suggestions == ()
    assert "no paper library" in meeting.turns[0].lead


def test_default_question_falls_back_to_one_the_library_covers(corpus: Path, tmp_path: Path):
    meeting = build_offline_meeting(None, corpus)

    assert meeting.question != DEFAULT_QUESTION
    assert meeting.question.startswith("What do we really know about")
    assert meeting.grounding != GROUNDING_NONE
    assert build_offline_meeting(None, tmp_path / "missing").question == DEFAULT_QUESTION


def test_repository_library_grounds_the_default_question(repo_root: Path):
    meeting = build_offline_meeting(None, repo_root / "papers")

    assert meeting.question == DEFAULT_QUESTION
    assert meeting.grounding == GROUNDING_STRONG
    assert _speakers(meeting) == set(AGENT_ROLES)
    assert len({quote.source for quote in meeting.quotes}) >= 2
    assert meeting.audit.passed and meeting.audit.checked == len(meeting.quotes) >= 3


def test_stream_meeting_plain_output_for_pipes(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)
    out = io.StringIO()

    stream_meeting(meeting, out=out)

    text = out.getvalue()
    assert "\033[" not in text
    assert "OFFLINE RESEARCH MEETING" in text
    assert "VERDICT" in text
    assert f"{meeting.audit.verified}/{meeting.audit.checked} quotes re-verified verbatim" in text
    for agent in AGENT_ROLES:
        assert agent in text


def test_stream_meeting_falls_back_to_ascii_glyphs(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="ascii", errors="strict", write_through=True)

    stream_meeting(meeting, out=out, color=False, pace=False, width=80)

    text = raw.getvalue().decode("ascii")
    assert "ok verbatim" in text
    assert "| " in text


def test_render_markdown_is_honest_about_the_missing_model(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)

    markdown = render_markdown(meeting, timestamp="2026-01-01 00:00:00", preset_title="Idea Roast")

    assert markdown.startswith("# R.A.I.N. Lab Offline Meeting")
    assert "No model ran." in markdown
    assert "| Preset | Idea Roast |" in markdown
    for quote in meeting.quotes:
        assert f"`{quote.citation}`" in markdown
    assert meeting.audit.corpus_sha256 in markdown


def test_share_highlight_prefers_the_counter_argument(corpus: Path):
    meeting = build_offline_meeting(QUESTION, corpus)

    assert share_highlight(meeting).startswith("Elena, citing Coupled Oscillators:")
