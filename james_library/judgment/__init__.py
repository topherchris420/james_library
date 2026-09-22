"""Independent, opt-in typed judgments and deterministic epistemic routing."""

from .contracts import (
    DEFAULT_QUESTION_SET, AtomicQuestion, ClaimEvidence, DeterministicMockJudgmentProvider,
    GateDisposition, JudgmentAnswer, JudgmentProvider, JudgmentResult, JudgmentState,
    QuestionSet, QuestionType, StateTruncation, ValidationStatus,
)
from .gate import GATE_POLICY_VERSION, GateDecision, JudgmentGate
from .service import JudgmentEnvelope, JudgmentService, create_judgment_service, format_judgment
from .state import build_state, contains_sensitive_material
from .typesafe import TypeSafeJudgmentProvider

__all__ = [
    "DEFAULT_QUESTION_SET", "GATE_POLICY_VERSION", "AtomicQuestion", "ClaimEvidence",
    "DeterministicMockJudgmentProvider", "GateDecision", "GateDisposition", "JudgmentAnswer",
    "JudgmentEnvelope", "JudgmentGate", "JudgmentProvider", "JudgmentResult", "JudgmentService",
    "JudgmentState", "QuestionSet", "QuestionType", "StateTruncation", "TypeSafeJudgmentProvider",
    "ValidationStatus", "build_state", "contains_sensitive_material",
    "create_judgment_service", "format_judgment",
]
