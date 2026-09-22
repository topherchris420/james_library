"""Explicit deterministic evidence and answer fixtures; never service responses."""

from james_library.judgment import (
    ClaimEvidence,
    DeterministicMockJudgmentProvider,
    JudgmentAnswer,
    JudgmentResult,
    JudgmentService,
    QuestionType,
    ValidationStatus,
)


def evidence(**changes):
    fields = dict(
        claim="The measured resonance peak is at 40 Hz in this simulated setup.",
        method="Sweep 30 to 50 Hz with a fixed simulated load.",
        observations="A peak occurred at 40 Hz in each of three runs.",
        quantitative_results="Peak: 40 Hz; resolution: 1 Hz; repeats: 3.",
        tool_evidence="Instrument run fixture-1: peaks [40, 40, 40] Hz.",
        peer_critique="The narrow simulated claim is supported; physical replication is missing.",
        formal_logic_result='{"satisfiable": true}',
        known_limitations="Simulation only; no physical replication.",
        source_identifiers=("fixture-1",),
        formal_status=ValidationStatus.PASSED,
        numerical_status=ValidationStatus.PASSED,
    )
    fields.update(changes)
    return ClaimEvidence(**fields)


def service(*, support="supported", confidence=0.95, error_code=None):
    choices = ("supported", "mixed", "unsupported", "insufficient_evidence")
    result = JudgmentResult(
        provider="deterministic_mock",
        model="fixture-v1",
        error_code=error_code,
        answers=() if error_code else (
            JudgmentAnswer("claim_support", QuestionType.CHOICE, support,
                           tuple((choice, 1.0 if choice == support else 0.0) for choice in choices), confidence),
            JudgmentAnswer("evidence_quality", QuestionType.SCORE, 3.0,
                           (("0", 0.0), ("1", 0.0), ("2", 0.0), ("3", 1.0)), confidence),
            JudgmentAnswer("contradiction_present", QuestionType.NOUL, 0.05),
            JudgmentAnswer("scope_violation", QuestionType.NOUL, 0.05),
            JudgmentAnswer("human_review", QuestionType.NOUL, 0.05),
        ),
    )
    provider = DeterministicMockJudgmentProvider(result)
    return JudgmentService(provider), provider


def prepare(workflow, packet):
    workflow.set_hypothesis(packet.claim)
    workflow.set_simulation_data({"observations": packet.observations})
    workflow.set_synthesis("Bounded simulated result; physical replication is missing.")
    workflow.set_peer_critique("R.A.I.N.Reviewer", 9, packet.peer_critique)
    return workflow
