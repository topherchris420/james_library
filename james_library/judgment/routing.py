"""Selective bounded proposals over the existing JudgmentProvider contract.

No provider receives a workflow, executor, recorder, or authorization object.
The host supplies deterministic validation and retains all action authority.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from queue import Empty, Queue
import re
from threading import Lock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4

from .calibration import CalibrationProfile, digest_json
from .contracts import (
    AtomicQuestion, JudgmentProvider, JudgmentResult, JudgmentState, QuestionSet,
    QuestionType, StateTruncation, ValidationStatus, bounded_number, valid_answers,
)
from .state import contains_sensitive_material


class EscalationReason(str, Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MARGIN_TOO_SMALL = "MARGIN_TOO_SMALL"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    OUT_OF_DISTRIBUTION = "OUT_OF_DISTRIBUTION"
    POLICY_REQUIRES_REVIEW = "POLICY_REQUIRES_REVIEW"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    HIGH_CONSEQUENCE = "HIGH_CONSEQUENCE"
    ENGINE_DISAGREEMENT = "ENGINE_DISAGREEMENT"
    TIMEOUT = "TIMEOUT"
    INSUFFICIENT_CALIBRATION = "INSUFFICIENT_CALIBRATION"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    DISABLED = "DISABLED"
    SENSITIVE_INPUT = "SENSITIVE_INPUT"


@dataclass(frozen=True)
class DecisionRequest:
    decision_class: str
    state: str
    instructions: str
    choices: tuple[tuple[str, str], ...]
    consequence: str = "high"
    requires_evidence: bool = False
    requires_review: bool = False
    out_of_distribution: bool = False
    remote_allowed: bool = False
    deterministic_choice: str | None = None

    def __post_init__(self):
        if not isinstance(self.decision_class, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.decision_class):
            raise ValueError("invalid decision class")
        if (not isinstance(self.state, str) or not self.state.strip() or len(self.state) > 24_000
                or not isinstance(self.instructions, str) or not self.instructions.strip()
                or len(self.instructions) > 1000):
            raise ValueError("invalid bounded state or instructions")
        if not isinstance(self.choices, tuple) or not 2 <= len(self.choices) <= 16:
            raise ValueError("expected 2 to 16 explicit choices")
        for choice in self.choices:
            if (not isinstance(choice, tuple) or len(choice) != 2
                    or not isinstance(choice[0], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", choice[0])
                    or not isinstance(choice[1], str) or not choice[1].strip() or len(choice[1]) > 500):
                raise ValueError("invalid bounded choice")
        if len(dict(self.choices)) != len(self.choices):
            raise ValueError("duplicate choices")
        if self.consequence not in {"low", "high"}:
            raise ValueError("invalid consequence")
        if any(type(getattr(self, key)) is not bool for key in (
            "requires_evidence", "requires_review", "out_of_distribution", "remote_allowed"
        )):
            raise ValueError("policy flags must be booleans")
        if self.deterministic_choice is not None and self.deterministic_choice not in dict(self.choices):
            raise ValueError("deterministic choice outside candidates")

    @property
    def questions(self):
        return QuestionSet("rain-bounded-choice-1", (
            AtomicQuestion("next_action", QuestionType.CHOICE, self.instructions, choices=self.choices),
        ))

    @property
    def question_hash(self):
        return digest_json({"version": self.questions.version, "questions": self.questions.to_dict()})

    @property
    def request_hash(self):
        return digest_json(asdict(self))


@dataclass(frozen=True)
class DecisionAttempt:
    engine: str
    model: str | None
    selected: str | None
    probabilities: tuple[tuple[str, float], ...]
    confidence: float | None
    latency_ms: float
    reason: EscalationReason | None
    calibration_profile: str | None = None
    threshold: float | None = None
    margin: float | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class DecisionEnvelope:
    decision_id: str
    timestamp: str
    request_hash: str
    question_hash: str
    decision_class: str
    choices: tuple[str, ...]
    selected: str | None
    destination: str
    reason: EscalationReason | None
    attempts: tuple[DecisionAttempt, ...]
    validator_result: bool
    latency_ms: float

    def to_dict(self):
        payload = asdict(self)
        payload.update(schema_version="rain-bounded-decision/v1", final_action=None,
                       policy_version="rain-routing-1")
        payload["envelope_hash"] = digest_json(payload)
        return payload


Validator = Callable[[DecisionRequest, str | None], bool]


def _validate(validator, request, selected):
    try:
        return validator(request, selected) is True
    except Exception:
        return False


class DecisionRouter:
    def __init__(self, *, mode="off", laya: JudgmentProvider | None = None,
                 jev: JudgmentProvider | None = None, profiles: tuple[CalibrationProfile, ...] = (),
                 minimum_samples=100, timeout=30.0, compare=False):
        if mode not in {"off", "laya", "jev", "cascade"}:
            raise ValueError("invalid decision mode")
        if type(minimum_samples) is not int or minimum_samples < 1:
            raise ValueError("invalid minimum calibration samples")
        if not bounded_number(timeout, .01, 300) or type(compare) is not bool:
            raise ValueError("invalid routing configuration")
        self.mode, self.laya, self.jev = mode, laya, jev
        self.profiles, self.minimum_samples = profiles, minimum_samples
        self.timeout, self.compare = timeout, compare
        # One live invocation per engine, even after a timeout. Hung providers
        # cannot accumulate unbounded background calls as a session continues.
        self._locks = {"laya": Lock(), "typesafe": Lock()}

    def decide(self, request: DecisionRequest, *, validator: Validator) -> DecisionEnvelope:
        started = monotonic()
        attempts = []
        sensitive = contains_sensitive_material(json.dumps(asdict(request)))

        def finish(selected=None, destination="rain", reason=None, valid=False):
            return DecisionEnvelope(
                str(uuid4()), datetime.now(timezone.utc).isoformat(), request.request_hash,
                request.question_hash, "withheld" if sensitive else request.decision_class,
                () if sensitive else tuple(dict(request.choices)),
                selected, destination, reason, tuple(attempts), valid, round((monotonic() - started) * 1000, 3),
            )

        if sensitive:
            return finish(destination="rejected", reason=EscalationReason.SENSITIVE_INPUT)
        if not _validate(validator, request, None):
            return finish(destination="rejected", reason=EscalationReason.VALIDATION_FAILED)
        if self.mode == "off":
            return finish(reason=EscalationReason.DISABLED)
        for condition, reason in (
            (request.consequence != "low", EscalationReason.HIGH_CONSEQUENCE),
            (request.requires_review, EscalationReason.POLICY_REQUIRES_REVIEW),
            (request.requires_evidence, EscalationReason.EVIDENCE_REQUIRED),
            (request.out_of_distribution, EscalationReason.OUT_OF_DISTRIBUTION),
        ):
            if condition:
                return finish(reason=reason)
        if request.deterministic_choice is not None:
            if _validate(validator, request, request.deterministic_choice):
                return finish(request.deterministic_choice, "proposal", valid=True)
            return finish(destination="rejected", reason=EscalationReason.VALIDATION_FAILED)
        engines = [("laya", self.laya)] if self.mode == "laya" else [("typesafe", self.jev)]
        if self.mode == "cascade":
            engines = [("laya", self.laya), ("typesafe", self.jev)]
        candidate = None
        for engine, provider in engines:
            if engine == "typesafe" and not request.remote_allowed:
                attempt = DecisionAttempt(engine, None, None, (), None, 0,
                                          EscalationReason.POLICY_REQUIRES_REVIEW)
            else:
                attempt = self._attempt(engine, provider, request)
            attempts.append(attempt)
            # Explicit comparison preserves even an uncertain engine's differing
            # candidate. Never resolve disagreement by comparing confidence.
            outputs = {item.selected for item in attempts if item.selected is not None}
            if self.compare and len(outputs) > 1:
                return finish(reason=EscalationReason.ENGINE_DISAGREEMENT)
            if attempt.reason is None:
                candidate = attempt.selected
                if not self.compare or self.mode != "cascade":
                    break
            elif self.compare:
                candidate = None
        if self.compare and any(item.reason is not None for item in attempts):
            candidate = None
        if candidate is None:
            return finish(reason=next((item.reason for item in reversed(attempts) if item.reason is not None),
                                      EscalationReason.MODEL_UNAVAILABLE))
        if not _validate(validator, request, candidate):
            return finish(destination="rejected", reason=EscalationReason.VALIDATION_FAILED)
        return finish(candidate, "proposal", valid=True)

    def _attempt(self, engine, provider, request):
        started = monotonic()
        result = None
        reason = None
        if provider is None:
            reason = EscalationReason.MODEL_UNAVAILABLE
        else:
            text = request.state
            state = JudgmentState(
                text, sha256(text.encode("utf-8")).hexdigest(),
                StateTruncation(False, (), len(text), len(text), 24_000, 24_000),
                ValidationStatus.NOT_RUN, ValidationStatus.NOT_RUN, False, False,
            )
            lock = self._locks[engine]
            if not lock.acquire(blocking=False):
                reason = EscalationReason.TIMEOUT
            else:
                results = Queue(maxsize=1)

                def evaluate():
                    try:
                        results.put(provider.evaluate(state, request.questions))
                    except Exception:
                        results.put(None)
                    finally:
                        lock.release()

                Thread(target=evaluate, daemon=True).start()
                try:
                    result = results.get(timeout=self.timeout)
                except Empty:
                    reason = EscalationReason.TIMEOUT
            if reason is None:
                try:
                    if not isinstance(result, JudgmentResult):
                        reason = EscalationReason.INVALID_OUTPUT
                    elif result.error_code:
                        reason = {"provider_timeout": EscalationReason.TIMEOUT,
                                  "provider_malformed_response": EscalationReason.INVALID_OUTPUT,
                                  "provider_input_too_large": EscalationReason.OUT_OF_DISTRIBUTION,
                                  "state_contains_secret": EscalationReason.SENSITIVE_INPUT}.get(
                                      result.error_code, EscalationReason.MODEL_UNAVAILABLE)
                    elif (result.provider != engine or not isinstance(result.model, str)
                          or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", result.model)
                          or contains_sensitive_material(result.model)
                          or result.state_hash != state.state_hash
                          or result.question_set_version != request.questions.version
                          or not valid_answers(result, request.questions)):
                        reason = EscalationReason.INVALID_OUTPUT
                except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                    reason = EscalationReason.INVALID_OUTPUT
        latency = round((monotonic() - started) * 1000, 3)
        if reason is not None:
            safe_errors = {
                "provider_not_configured", "provider_timeout", "provider_transport_error",
                "provider_authentication_error", "provider_rate_limited", "provider_overloaded",
                "provider_http_error", "provider_response_too_large", "provider_malformed_response",
                "provider_input_too_large", "provider_runtime_unsupported", "state_contains_secret",
                "provider_internal_error",
            }
            error = result.error_code if isinstance(result, JudgmentResult) else None
            if not isinstance(error, str) or error not in safe_errors:
                error = "provider_timeout" if reason == EscalationReason.TIMEOUT else "provider_internal_error"
            if provider is None:
                error = "provider_not_configured"
            return DecisionAttempt(engine, None, None, (), None, latency, reason, error_code=error)
        answer = result.answers[0]
        profile = next((p for p in self.profiles if (p.engine, p.model, p.decision_class, p.question_hash) ==
                        (engine, result.model, request.decision_class, request.question_hash)), None)
        if profile is None or not profile.supports(self.minimum_samples):
            reason = EscalationReason.INSUFFICIENT_CALIBRATION
        else:
            probabilities = sorted(dict(answer.probabilities).values(), reverse=True)
            if probabilities[0] < profile.threshold:
                reason = EscalationReason.LOW_CONFIDENCE
            elif probabilities[0] - probabilities[1] < profile.margin:
                reason = EscalationReason.MARGIN_TOO_SMALL
        return DecisionAttempt(engine, result.model, answer.value, answer.probabilities, answer.confidence,
                               latency, reason, profile.profile_id if profile else None,
                               profile.threshold if profile else None, profile.margin if profile else None)
