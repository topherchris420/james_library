"""Offline judgment contracts and policy; no model can manufacture local validation."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import pytest

from james_library.judgment import (
    DEFAULT_QUESTION_SET, ClaimEvidence, DeterministicMockJudgmentProvider,
    GateDisposition, JudgmentAnswer, JudgmentGate, JudgmentResult, JudgmentService,
    QuestionType, ValidationStatus, build_state, create_judgment_service, format_judgment,
)


def evidence(**changes):
    packet = ClaimEvidence(
        claim="The measured value exceeds the baseline.", method="Controlled measurement",
        observations="Three measurements exceeded the baseline.", quantitative_results="2, 3, 4; baseline 1",
        tool_evidence="measurement-1: passed", peer_critique="Scope is bounded to these measurements.",
        formal_logic_result="SAT", source_identifiers=("measurement-1",),
        formal_status=ValidationStatus.PASSED, numerical_status=ValidationStatus.PASSED,
    )
    return replace(packet, **changes)


def result(**changes):
    fixture = JudgmentResult(provider="fixture", answers=(
        JudgmentAnswer("claim_support", QuestionType.CHOICE, "supported",
                       (("supported", .91), ("mixed", .03), ("unsupported", .03),
                        ("insufficient_evidence", .03)), .91),
        JudgmentAnswer("evidence_quality", QuestionType.SCORE, 2.5,
                       (("0", .02), ("1", .03), ("2", .4), ("3", .55)), .86),
        JudgmentAnswer("contradiction_present", QuestionType.NOUL, .08),
        JudgmentAnswer("scope_violation", QuestionType.NOUL, .13),
        JudgmentAnswer("human_review", QuestionType.NOUL, .09),
    ))
    return replace(fixture, **changes)


def run(packet=None, fixture=None):
    provider = DeterministicMockJudgmentProvider(fixture or result())
    return JudgmentService(provider).evaluate(packet or evidence())


def changed_answer(question_id, **changes):
    fixture = result()
    return replace(fixture, answers=tuple(
        replace(answer, **changes) if answer.question_id == question_id else answer
        for answer in fixture.answers
    ))


def test_questions_are_atomic_immutable_and_serialize_documented_primitives():
    questions = DEFAULT_QUESTION_SET.to_dict()
    assert list(questions) == ["claim_support", "evidence_quality", "contradiction_present",
                               "scope_violation", "human_review"]
    assert questions["claim_support"]["type"] == "choice"
    assert list(questions["claim_support"]["criteria"]) == ["supported", "mixed", "unsupported",
                                                          "insufficient_evidence"]
    assert len(questions["evidence_quality"]["criteria"]) == 4
    assert questions["human_review"]["type"] == "noul"
    assert "criteria" not in questions["human_review"]
    with pytest.raises(FrozenInstanceError):
        DEFAULT_QUESTION_SET.version = "changed"


def test_state_is_deterministic_and_contains_only_curated_fields(monkeypatch):
    monkeypatch.setenv("PRIVATE_CORPUS", "unrelated private material")
    state = build_state(evidence())
    assert state == build_state(evidence())
    assert state.state_hash == hashlib.sha256(state.canonical_text.encode()).hexdigest()
    assert "unrelated private material" not in state.canonical_text
    assert "CLAIM:" in state.canonical_text and "SOURCE IDENTIFIERS:" in state.canonical_text
    with pytest.raises(TypeError):
        ClaimEvidence(claim="x", corpus="private")


def test_truncation_is_explicit_and_cannot_pass():
    packet = evidence(observations="x" * 50000)
    state = build_state(packet)
    assert len(state.canonical_text) <= 24000
    assert state.truncation.truncated
    assert "observations" in state.truncation.fields
    assert "TRUNCATED" in state.canonical_text
    assert run(packet).decision.disposition == GateDisposition.HUMAN_REVIEW


def test_valid_evidence_and_answers_pass():
    envelope = run()
    assert envelope.decision.disposition == GateDisposition.PASS
    record = envelope.to_dict()
    assert record["state_hash"] == build_state(evidence()).state_hash
    assert record["schema_version"] == 1
    assert record["mode"] == "deterministic_mock"
    assert record["gate_policy_version"]
    assert len(record["answers"]) == 5
    assert "PASS" in format_judgment(envelope)
    json.dumps(record, allow_nan=False)


@pytest.mark.parametrize("question_id,value", [
    ("claim_support", "mixed"), ("claim_support", "unsupported"),
    ("claim_support", "insufficient_evidence"), ("evidence_quality", 1.9),
    ("contradiction_present", .7), ("scope_violation", .7),
])
def test_revise_policy(question_id, value):
    assert run(fixture=changed_answer(question_id, value=value)).decision.disposition == GateDisposition.REVISE


@pytest.mark.parametrize("question_id,changes", [
    ("claim_support", {"confidence": .79}), ("evidence_quality", {"confidence": .79}),
    ("contradiction_present", {"value": .2}), ("scope_violation", {"value": .2}),
    ("human_review", {"value": .99}),
])
def test_uncertainty_requires_human_review(question_id, changes):
    assert run(fixture=changed_answer(question_id, **changes)).decision.disposition == GateDisposition.HUMAN_REVIEW


@pytest.mark.parametrize("field", ["formal_status", "numerical_status"])
def test_judgment_cannot_override_failed_local_validation(field):
    assert run(evidence(**{field: ValidationStatus.FAILED})).decision.disposition == GateDisposition.REVISE


@pytest.mark.parametrize("status", [ValidationStatus.NOT_RUN, ValidationStatus.ERROR])
def test_missing_or_errored_local_validation_requires_review(status):
    assert run(evidence(formal_status=status)).decision.disposition == GateDisposition.HUMAN_REVIEW


def test_missing_measured_evidence_requires_revision():
    packet = evidence(observations="", quantitative_results="", tool_evidence="", source_identifiers=())
    assert run(packet).decision.disposition == GateDisposition.REVISE


@pytest.mark.parametrize(
    "packet",
    [
        evidence(formal_status=ValidationStatus.FAILED),
        evidence(numerical_status=ValidationStatus.FAILED),
        evidence(formal_status=ValidationStatus.NOT_RUN),
        evidence(observations="", quantitative_results="", tool_evidence="", source_identifiers=()),
    ],
)
def test_deterministic_preconditions_skip_provider(packet):
    provider = DeterministicMockJudgmentProvider(result())
    envelope = JudgmentService(provider).evaluate(packet)
    assert provider.calls == []
    assert envelope.mode == "deterministic_precheck"


def test_unavailable_is_explicit_and_sanitized():
    envelope = run(fixture=result(answers=(), error_code="provider_timeout"))
    assert envelope.decision.disposition == GateDisposition.UNAVAILABLE
    assert "provider_timeout" in format_judgment(envelope)


def test_mismatched_or_incomplete_judgments_are_unavailable():
    state = build_state(evidence())
    assert JudgmentGate().evaluate(result(state_hash="other"), state).disposition == GateDisposition.UNAVAILABLE
    assert run(fixture=result(answers=result().answers[:-1])).decision.disposition == GateDisposition.UNAVAILABLE


def test_disabled_is_default_and_bad_configuration_fails_fast(monkeypatch):
    monkeypatch.delenv("RAIN_JUDGMENT_PROVIDER", raising=False)
    assert create_judgment_service() is None
    monkeypatch.setenv("RAIN_JUDGMENT_PROVIDER", "invalid-private-value")
    with pytest.raises(ValueError, match="unsupported judgment provider") as exc:
        create_judgment_service()
    assert "invalid-private-value" not in str(exc.value)


def test_enabled_without_key_is_unavailable_without_network(monkeypatch):
    monkeypatch.setenv("RAIN_JUDGMENT_PROVIDER", "typesafe")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    envelope = create_judgment_service().evaluate(evidence())
    assert envelope.decision.disposition == GateDisposition.UNAVAILABLE
    assert envelope.result.error_code == "provider_not_configured"
