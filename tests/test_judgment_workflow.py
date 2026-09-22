"""Promotion regressions and independent judgment integration; entirely offline."""

import pytest

from james_library.launcher.meeting_workflow import MeetingStage, MeetingWorkflow


@pytest.mark.parametrize("score,accepted", [(1, False), (7, False), (8, True), (10, True)])
def test_disabled_workflow_preserves_peer_score_gate(score, accepted):
    workflow = MeetingWorkflow()
    workflow.set_hypothesis("A bounded hypothesis")
    workflow.set_simulation_data({"observed": 1})
    workflow.set_synthesis("A bounded synthesis")
    workflow.set_peer_critique("R.A.I.N.Reviewer", score, "Peer critique")
    assert workflow.finalize_discovery_gate() is accepted
    assert workflow.history[-1]["score"] == score
    assert workflow.history[-1]["accepted"] is accepted
    assert workflow.current_stage is (MeetingStage.DISCOVERY if accepted else MeetingStage.HYPOTHESIS)


def test_discovery_without_peer_critique_fails():
    with pytest.raises(ValueError, match="peer critique"):
        MeetingWorkflow().finalize_discovery_gate()


def test_enabled_workflow_requires_explicit_evidence():
    workflow = MeetingWorkflow(judgment_service=object())
    workflow.set_peer_critique("R.A.I.N.Reviewer", 9, "Peer critique")
    with pytest.raises(ValueError, match="evidence"):
        workflow.finalize_discovery_gate()


@pytest.mark.parametrize("score", [1, 7])
def test_failed_peer_score_never_calls_judgment_provider(score):
    from tests.judgment_helpers import evidence, prepare, service

    evaluator, provider = service()
    packet = evidence()
    workflow = prepare(MeetingWorkflow(judgment_service=evaluator), packet)
    workflow.set_peer_critique("R.A.I.N.Reviewer", score, packet.peer_critique)
    assert not workflow.finalize_discovery_gate(evidence=packet)
    assert provider.calls == []
    assert workflow.history[-1]["gate_disposition"] == "REVISE"


@pytest.mark.parametrize(
    "provider_options,expected,stage",
    [({}, "PASS", MeetingStage.DISCOVERY),
     ({"support": "mixed"}, "REVISE", MeetingStage.HYPOTHESIS),
     ({"confidence": 0.5}, "HUMAN_REVIEW", MeetingStage.PEER_CRITIQUE),
     ({"error_code": "provider_timeout"}, "UNAVAILABLE", MeetingStage.PEER_CRITIQUE)],
)
def test_enabled_gate_controls_promotion_and_preserves_peer_score(provider_options, expected, stage):
    from tests.judgment_helpers import evidence, prepare, service

    evaluator, provider = service(**provider_options)
    packet = evidence()
    recorded = []
    workflow = prepare(MeetingWorkflow(judgment_service=evaluator, judgment_recorder=recorded.append), packet)
    assert workflow.finalize_discovery_gate(evidence=packet) is (expected == "PASS")
    assert workflow.current_stage is stage
    assert workflow.history[-1]["score"] == 9
    assert workflow.history[-1]["gate_disposition"] == expected
    assert len(recorded) == len(provider.calls) == 1
    assert workflow.record.judgment is recorded[0]
    assert workflow.finalize_discovery_gate(evidence=packet) is (expected == "PASS")
    assert len(provider.calls) == len(recorded) == len(workflow.history) == 1


@pytest.mark.parametrize("field", ["claim", "peer_critique"])
def test_evidence_cannot_judge_a_different_claim_or_critique(field):
    from dataclasses import replace
    from tests.judgment_helpers import evidence, prepare, service

    evaluator, provider = service()
    packet = evidence()
    workflow = prepare(MeetingWorkflow(judgment_service=evaluator), packet)
    with pytest.raises(ValueError, match="match"):
        workflow.finalize_discovery_gate(evidence=replace(packet, **{field: "Different content"}))
    assert provider.calls == []


def test_new_hypothesis_clears_enabled_cycle_evidence_and_previous_judgment():
    from tests.judgment_helpers import evidence, prepare, service

    evaluator, provider = service()
    packet = evidence()
    workflow = prepare(MeetingWorkflow(judgment_service=evaluator), packet)
    assert workflow.finalize_discovery_gate(evidence=packet)
    workflow.set_hypothesis("A revised hypothesis")
    assert workflow.record.judgment is None
    assert workflow.record.critique_score is None
    assert workflow.record.simulation_data == {}
    with pytest.raises(ValueError, match="peer critique"):
        workflow.finalize_discovery_gate(evidence=packet)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("field", ["formal_status", "numerical_status"])
def test_judgment_cannot_override_failed_validation(field):
    from james_library.judgment import ValidationStatus
    from tests.judgment_helpers import evidence, prepare, service

    evaluator, _ = service()
    packet = evidence(**{field: ValidationStatus.FAILED})
    workflow = prepare(MeetingWorkflow(judgment_service=evaluator), packet)
    assert not workflow.finalize_discovery_gate(evidence=packet)
    assert workflow.history[-1]["gate_disposition"] == "REVISE"
