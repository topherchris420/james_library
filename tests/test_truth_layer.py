import pytest

from truth_layer import Evidence, assert_grounded, build_grounded_response


def test_grounded_response_with_evidence_passes():
    payload = build_grounded_response(
        answer="Claim",
        confidence=1.2,
        provenance=["paper.md"],
        evidence=[Evidence(source="paper.md", quote="Exact quote", span_start=0, span_end=11)],
        repro_steps=["read paper.md"],
    )
    assert payload["confidence"] == 1.0
    assert payload["red_badge"] is False
    assert_grounded(payload)


def test_grounded_response_without_evidence_fails_assertion():
    payload = build_grounded_response(
        answer="Claim",
        confidence=0.4,
        provenance=[],
        evidence=[],
        repro_steps=["query X"],
    )
    assert payload["red_badge"] is True
    with pytest.raises(ValueError):
        assert_grounded(payload)
