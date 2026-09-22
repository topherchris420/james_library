"""Provider-neutral values for bounded evaluation, separate from chat providers."""

from dataclasses import dataclass, replace
from enum import Enum
from math import isfinite
from typing import Protocol


class ValidationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    ERROR = "error"


class QuestionType(str, Enum):
    CHOICE = "choice"
    SCORE = "score"
    NOUL = "noul"


class GateDisposition(str, Enum):
    PASS = "PASS"
    REVISE = "REVISE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ClaimEvidence:
    claim: str
    method: str = ""
    observations: str = ""
    quantitative_results: str = ""
    tool_evidence: str = ""
    peer_critique: str = ""
    formal_logic_result: str = ""
    known_limitations: str = ""
    source_identifiers: tuple[str, ...] = ()
    formal_status: ValidationStatus = ValidationStatus.NOT_RUN
    numerical_status: ValidationStatus = ValidationStatus.NOT_RUN

    def __post_init__(self) -> None:
        for name in ("claim", "method", "observations", "quantitative_results", "tool_evidence",
                     "peer_critique", "formal_logic_result", "known_limitations"):
            if not isinstance(getattr(self, name), str):
                raise ValueError("evidence fields must be strings")
        if not self.claim.strip():
            raise ValueError("claim is required")
        if not isinstance(self.source_identifiers, tuple) or not all(
            isinstance(source, str) for source in self.source_identifiers
        ):
            raise ValueError("source identifiers must be a tuple of strings")
        if not isinstance(self.formal_status, ValidationStatus) or not isinstance(
            self.numerical_status, ValidationStatus
        ):
            raise ValueError("validation statuses must be typed")


@dataclass(frozen=True)
class StateTruncation:
    truncated: bool
    fields: tuple[str, ...]
    original_characters: int
    submitted_characters: int
    max_field_characters: int
    max_state_characters: int

    def to_dict(self) -> dict:
        return {"truncated": self.truncated, "fields": list(self.fields),
                "original_characters": self.original_characters, "submitted_characters": self.submitted_characters,
                "max_field_characters": self.max_field_characters, "max_state_characters": self.max_state_characters}


@dataclass(frozen=True)
class JudgmentState:
    canonical_text: str
    state_hash: str
    truncation: StateTruncation
    formal_status: ValidationStatus
    numerical_status: ValidationStatus
    has_measured_evidence: bool
    has_source_identifiers: bool


@dataclass(frozen=True)
class AtomicQuestion:
    question_id: str
    type: QuestionType
    instructions: str
    choices: tuple[tuple[str, str], ...] = ()
    levels: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        value = {"type": self.type.value, "instructions": self.instructions}
        if self.type == QuestionType.CHOICE:
            value["criteria"] = dict(self.choices)
        elif self.type == QuestionType.SCORE:
            value["criteria"] = list(self.levels)
        return value


@dataclass(frozen=True)
class QuestionSet:
    version: str
    questions: tuple[AtomicQuestion, ...]

    def to_dict(self) -> dict:
        return {question.question_id: question.to_dict() for question in self.questions}


DEFAULT_QUESTION_SET = QuestionSet("rain-atomic-1", (
    AtomicQuestion("claim_support", QuestionType.CHOICE,
                   "Given only the supplied evidence, how well is the claim supported?",
                   choices=(("supported", "The supplied evidence directly supports the bounded claim."),
                            ("mixed", "The evidence includes both support and meaningful counterevidence."),
                            ("unsupported", "The supplied evidence does not support the claim."),
                            ("insufficient_evidence", "There is insufficient evidence to evaluate the claim."))),
    AtomicQuestion("evidence_quality", QuestionType.SCORE,
                   "How strong is the supplied evidence for evaluating this specific claim?",
                   levels=("Insufficient to evaluate", "Weak or indirect evidence",
                           "Adequate evidence with meaningful limitations", "Strong, directly relevant evidence")),
    AtomicQuestion("contradiction_present", QuestionType.NOUL,
                   "The supplied evidence contains a meaningful contradiction of the claim."),
    AtomicQuestion("scope_violation", QuestionType.NOUL,
                   "The claim goes materially beyond what the supplied evidence establishes."),
    AtomicQuestion("human_review", QuestionType.NOUL,
                   "The evidence or uncertainty warrants explicit human review before this claim is promoted."),
))


@dataclass(frozen=True)
class JudgmentAnswer:
    question_id: str
    type: QuestionType
    value: str | float
    probabilities: tuple[tuple[str, float], ...] = ()
    confidence: float | None = None

    def to_dict(self) -> dict:
        return {"question_id": self.question_id, "type": self.type.value, "answer": self.value,
                "probabilities": dict(self.probabilities) if self.probabilities else None,
                "confidence": self.confidence}


@dataclass(frozen=True)
class JudgmentResult:
    provider: str
    model: str | None = None
    answers: tuple[JudgmentAnswer, ...] = ()
    state_hash: str = ""
    question_set_version: str = ""
    error_code: str | None = None
    error_status: int | None = None


class JudgmentProvider(Protocol):
    def evaluate(self, state: JudgmentState, questions: QuestionSet) -> JudgmentResult: ...


class DeterministicMockJudgmentProvider:
    """Explicit fixture only: an unconfigured mock cannot accidentally approve anything."""

    def __init__(self, result: JudgmentResult):
        self.result = result
        self.calls: list[tuple[JudgmentState, QuestionSet]] = []

    def evaluate(self, state: JudgmentState, questions: QuestionSet) -> JudgmentResult:
        self.calls.append((state, questions))
        return replace(self.result, state_hash=state.state_hash, question_set_version=questions.version)


def bounded_number(value: object, low: float, high: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and low <= value <= high


def valid_answers(result: JudgmentResult, questions: QuestionSet) -> bool:
    """Validate every provider at the policy boundary, including local implementations."""
    if not isinstance(result.answers, tuple) or len(result.answers) != len(questions.questions):
        return False
    by_id = {answer.question_id: answer for answer in result.answers if isinstance(answer, JudgmentAnswer)}
    if set(by_id) != {question.question_id for question in questions.questions}:
        return False
    for question in questions.questions:
        answer = by_id[question.question_id]
        if answer.type != question.type:
            return False
        if question.type == QuestionType.NOUL:
            if not bounded_number(answer.value, 0, 1) or answer.confidence is not None or answer.probabilities:
                return False
            continue
        if not bounded_number(answer.confidence, 0, 1):
            return False
        if question.type == QuestionType.CHOICE:
            expected = {key for key, _ in question.choices}
            if not isinstance(answer.value, str) or answer.value not in expected:
                return False
        else:
            expected = {str(index) for index in range(len(question.levels))}
            if not bounded_number(answer.value, 0, len(question.levels) - 1):
                return False
        probabilities = dict(answer.probabilities)
        if len(answer.probabilities) != len(expected) or set(probabilities) != expected:
            return False
        if not all(bounded_number(value, 0, 1) for value in probabilities.values()):
            return False
        if abs(sum(probabilities.values()) - 1) > .01:
            return False
    return True
