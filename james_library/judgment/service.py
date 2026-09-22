"""Evaluation orchestration and an auditable envelope; no discovery side effects."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
from time import monotonic
from uuid import uuid4

from .contracts import (
    DEFAULT_QUESTION_SET, ClaimEvidence, DeterministicMockJudgmentProvider, JudgmentProvider,
    JudgmentResult, JudgmentState, QuestionSet,
    valid_answers,
)
from .gate import GateDecision, JudgmentGate
from .state import build_state, contains_sensitive_material
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
        payload = {
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
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        payload["envelope_hash"] = sha256(encoded).hexdigest()
        return payload


class JudgmentService:
    def __init__(self, provider: JudgmentProvider):
        self.provider = provider
        self.questions = DEFAULT_QUESTION_SET
        self.gate = JudgmentGate()

    def evaluate(self, evidence: ClaimEvidence) -> JudgmentEnvelope:
        state = build_state(evidence)
        started = monotonic()
        if contains_sensitive_material(state.canonical_text):
            result = JudgmentResult(
                "unavailable",
                state_hash=state.state_hash,
                question_set_version=self.questions.version,
                error_code="state_contains_secret",
            )
            decision = self.gate.evaluate(result, state, self.questions)
            state, result = _withhold_sensitive_state(state, result)
            return self._envelope(state, result, decision, started, "provider_precheck")
        provider_result = None
        provider_preflight = getattr(self.provider, "preflight", None)
        if callable(provider_preflight):
            try:
                provider_result = provider_preflight(state, self.questions)
            except Exception:
                provider_result = JudgmentResult(
                    "unavailable",
                    state_hash=state.state_hash,
                    question_set_version=self.questions.version,
                    error_code="provider_internal_error",
                )
            if provider_result is not None:
                provider_result = _sanitize_result(provider_result, state, self.questions)
                if provider_result.error_code == "state_contains_secret":
                    decision = self.gate.evaluate(provider_result, state, self.questions)
                    state, provider_result = _withhold_sensitive_state(state, provider_result)
                    return self._envelope(
                        state, provider_result, decision, started, "provider_precheck"
                    )
        preflight = self.gate.preflight(state)
        if preflight is not None:
            result = JudgmentResult(
                "not_called",
                state_hash=state.state_hash,
                question_set_version=self.questions.version,
            )
            return self._envelope(state, result, preflight, started, "deterministic_precheck")
        if provider_result is not None:
            decision = self.gate.evaluate(provider_result, state, self.questions)
            return self._envelope(
                state, provider_result, decision, started, "provider_precheck"
            )
        try:
            result = self.provider.evaluate(state, self.questions)
            result = _sanitize_result(result, state, self.questions)
        except Exception:
            # Third-party providers may raise exceptions containing authorization headers or state.
            result = JudgmentResult("unavailable", state_hash=state.state_hash,
                                    question_set_version=self.questions.version, error_code="provider_internal_error")
        decision = self.gate.evaluate(result, state, self.questions)
        if result.error_code == "state_contains_secret":
            state, result = _withhold_sensitive_state(state, result)
        mode = (
            "deterministic_mock"
            if isinstance(self.provider, DeterministicMockJudgmentProvider)
            else "live_evaluation"
        )
        return self._envelope(state, result, decision, started, mode)

    def _envelope(
        self,
        state: JudgmentState,
        result: JudgmentResult,
        decision: GateDecision,
        started: float,
        mode: str,
    ) -> JudgmentEnvelope:
        return JudgmentEnvelope(
            str(uuid4()),
            datetime.now(timezone.utc).isoformat(),
            self.questions,
            state,
            result,
            decision,
            round((monotonic() - started) * 1000, 3),
            mode,
        )


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


_SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")


def _sanitize_result(
    result: object,
    state: JudgmentState,
    questions: QuestionSet,
) -> JudgmentResult:
    """Copy only policy-safe provider fields into an auditable result."""
    if not isinstance(result, JudgmentResult):
        return _provider_failure(state, questions, "provider_internal_error")
    if result.state_hash != state.state_hash or result.question_set_version != questions.version:
        return _provider_failure(state, questions, "provider_malformed_response")
    if result.error_code:
        if result.error_code not in PROVIDER_ERROR_CODES:
            return _provider_failure(state, questions, "provider_internal_error")
        provider = result.provider if _safe_label(result.provider) else "unavailable"
        model = result.model if result.model is None or _safe_label(result.model) else None
        status = (
            result.error_status
            if type(result.error_status) is int and 100 <= result.error_status <= 599
            else None
        )
        return JudgmentResult(
            provider,
            model=model,
            state_hash=state.state_hash,
            question_set_version=questions.version,
            error_code=result.error_code,
            error_status=status,
        )
    if not _safe_label(result.provider) or (
        result.model is not None and not _safe_label(result.model)
    ) or not valid_answers(result, questions):
        return _provider_failure(state, questions, "provider_malformed_response")
    return result


def _safe_label(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(_SAFE_LABEL.fullmatch(value))
        and not contains_sensitive_material(value)
    )


def _provider_failure(
    state: JudgmentState,
    questions: QuestionSet,
    code: str,
) -> JudgmentResult:
    return JudgmentResult(
        "unavailable",
        state_hash=state.state_hash,
        question_set_version=questions.version,
        error_code=code,
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
