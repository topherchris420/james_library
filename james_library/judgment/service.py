"""Evaluation orchestration and an auditable envelope; no discovery side effects."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import os
from time import monotonic
from uuid import uuid4

from .contracts import (
    DEFAULT_QUESTION_SET, ClaimEvidence, DeterministicMockJudgmentProvider, JudgmentProvider,
    JudgmentResult, JudgmentState, QuestionSet,
)
from .gate import GateDecision, JudgmentGate
from .state import build_state
from .typesafe import PROVIDER_ERROR_CODES, TypeSafeJudgmentProvider


@dataclass(frozen=True)
class JudgmentEnvelope:
    judgment_id: str
    timestamp: str
    question_set: QuestionSet
    state: JudgmentState
    result: JudgmentResult
    decision: GateDecision
    latency_ms: float
    mode: str
    schema_version: int = 1

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "judgment_id": self.judgment_id,
            "timestamp": self.timestamp, "mode": self.mode,
            "provider": self.result.provider, "model": self.result.model,
            "question_set_version": self.question_set.version, "questions": self.question_set.to_dict(),
            "state_hash": self.state.state_hash, "state": self.state.canonical_text,
            "state_truncation": self.state.truncation.to_dict(),
            "local_validation": {"formal": self.state.formal_status.value,
                                 "numerical": self.state.numerical_status.value},
            "answers": [answer.to_dict() for answer in self.result.answers],
            "disposition": self.decision.disposition.value, "gate_policy_version": self.decision.policy_version,
            "reason_codes": list(self.decision.reason_codes), "latency_ms": self.latency_ms,
            "provider_error": {"code": self.result.error_code, "status": self.result.error_status}
            if self.result.error_code else None,
        }


class JudgmentService:
    def __init__(self, provider: JudgmentProvider):
        self.provider = provider
        self.questions = DEFAULT_QUESTION_SET
        self.gate = JudgmentGate()

    def evaluate(self, evidence: ClaimEvidence) -> JudgmentEnvelope:
        state = build_state(evidence)
        started = monotonic()
        provider_preflight = getattr(self.provider, "preflight", None)
        if callable(provider_preflight):
            result = provider_preflight(state, self.questions)
            if result is not None:
                decision = self.gate.evaluate(result, state, self.questions)
                if result.error_code == "state_contains_secret":
                    state, result = _withhold_sensitive_state(state, result)
                return JudgmentEnvelope(
                    str(uuid4()),
                    datetime.now(timezone.utc).isoformat(),
                    self.questions,
                    state,
                    result,
                    decision,
                    round((monotonic() - started) * 1000, 3),
                    "provider_precheck",
                )
        preflight = self.gate.preflight(state)
        if preflight is not None:
            result = JudgmentResult(
                "not_called",
                state_hash=state.state_hash,
                question_set_version=self.questions.version,
            )
            return JudgmentEnvelope(
                str(uuid4()),
                datetime.now(timezone.utc).isoformat(),
                self.questions,
                state,
                result,
                preflight,
                round((monotonic() - started) * 1000, 3),
                "deterministic_precheck",
            )
        try:
            result = self.provider.evaluate(state, self.questions)
            if not isinstance(result, JudgmentResult):
                raise ValueError("invalid judgment result")
            if result.error_code and result.error_code not in PROVIDER_ERROR_CODES:
                result = replace(result, answers=(), error_code="provider_internal_error", error_status=None)
        except Exception:
            # Third-party providers may raise exceptions containing authorization headers or state.
            result = JudgmentResult("unavailable", state_hash=state.state_hash,
                                    question_set_version=self.questions.version, error_code="provider_internal_error")
        decision = self.gate.evaluate(result, state, self.questions)
        if result.error_code == "state_contains_secret":
            state, result = _withhold_sensitive_state(state, result)
        return JudgmentEnvelope(str(uuid4()), datetime.now(timezone.utc).isoformat(), self.questions,
                                state, result, decision, round((monotonic() - started) * 1000, 3),
                                "deterministic_mock" if isinstance(self.provider, DeterministicMockJudgmentProvider)
                                else "live_evaluation")


def _withhold_sensitive_state(
    state: JudgmentState,
    result: JudgmentResult,
) -> tuple[JudgmentState, JudgmentResult]:
    canonical_text = "[WITHHELD: credential detected; no remote request sent]"
    state_hash = sha256(canonical_text.encode("utf-8")).hexdigest()
    return (
        replace(state, canonical_text=canonical_text, state_hash=state_hash),
        replace(result, state_hash=state_hash, model=None),
    )


def create_judgment_service() -> JudgmentService | None:
    provider = os.getenv("RAIN_JUDGMENT_PROVIDER", "off").strip().lower()
    if provider == "off":
        return None
    if provider != "typesafe":
        raise ValueError("unsupported judgment provider; expected off or typesafe")
    return JudgmentService(TypeSafeJudgmentProvider(os.getenv("TYPESAFE_API_KEY"),
                                                   os.getenv("TYPESAFE_MODEL", "jev-latest")))


def format_judgment(envelope: JudgmentEnvelope) -> str:
    if envelope.result.error_code:
        return f"Typed Judgment: UNAVAILABLE\nReason: {envelope.result.error_code}"
    labels = {"claim_support": "Claim support", "evidence_quality": "Evidence quality",
              "contradiction_present": "Contradiction", "scope_violation": "Scope violation",
              "human_review": "Human review"}
    lines = ["Typed Judgment", "--------------"]
    for answer in envelope.result.answers:
        value = str(answer.value)
        if answer.question_id == "evidence_quality":
            value += " / 3"
        confidence = f" confidence {answer.confidence:.2f}" if answer.confidence is not None else ""
        lines.append(f"{labels.get(answer.question_id, answer.question_id):<20} {value:<20}{confidence}")
    lines.append(f"Gate                 {envelope.decision.disposition.value}")
    if envelope.decision.disposition.value != "PASS":
        lines.append("Reasons: " + ", ".join(envelope.decision.reason_codes))
    return "\n".join(lines)
