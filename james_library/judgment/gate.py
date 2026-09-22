"""Versioned deterministic routing. Typed judgments do not prove scientific truth."""

from dataclasses import dataclass

from .contracts import (
    DEFAULT_QUESTION_SET, GateDisposition, JudgmentResult, JudgmentState, QuestionSet,
    ValidationStatus, valid_answers,
)

GATE_POLICY_VERSION = "rain-gate-1"
MIN_CONFIDENCE = .8
MIN_EVIDENCE_QUALITY = 2
REVISION_PROBABILITY = .7
REVIEW_PROBABILITY = .2


@dataclass(frozen=True)
class GateDecision:
    disposition: GateDisposition
    reason_codes: tuple[str, ...]
    policy_version: str = GATE_POLICY_VERSION


class JudgmentGate:
    def preflight(self, state: JudgmentState) -> GateDecision | None:
        """Route deterministic evidence failures before any provider is called."""
        revise: list[str] = []
        review: list[str] = []
        for channel, status in (("formal", state.formal_status), ("numerical", state.numerical_status)):
            if status == ValidationStatus.FAILED:
                revise.append(f"{channel}_validation_failed")
            elif status != ValidationStatus.PASSED:
                review.append(f"{channel}_validation_{status.value}")
        if not state.has_measured_evidence or not state.has_source_identifiers:
            revise.append("insufficient_evidence_packet")
        if state.truncation.truncated:
            review.append("state_truncated")
        if revise:
            return GateDecision(GateDisposition.REVISE, tuple(revise + review))
        if review:
            return GateDecision(GateDisposition.HUMAN_REVIEW, tuple(review))
        return None

    def evaluate(self, result: JudgmentResult, state: JudgmentState,
                 questions: QuestionSet = DEFAULT_QUESTION_SET) -> GateDecision:
        if result.error_code:
            return GateDecision(GateDisposition.UNAVAILABLE, (result.error_code,))
        preflight = self.preflight(state)
        if preflight is not None:
            return preflight
        if result.state_hash != state.state_hash or result.question_set_version != questions.version:
            return GateDecision(GateDisposition.UNAVAILABLE, ("judgment_binding_mismatch",))
        if questions != DEFAULT_QUESTION_SET or not valid_answers(result, questions):
            return GateDecision(GateDisposition.UNAVAILABLE, ("judgment_malformed",))
        answers = {answer.question_id: answer for answer in result.answers}
        revise: list[str] = []
        review: list[str] = []
        if answers["claim_support"].value != "supported":
            revise.append("claim_not_supported")
        if float(answers["evidence_quality"].value) < MIN_EVIDENCE_QUALITY:
            revise.append("evidence_quality_low")
        for question_id in ("contradiction_present", "scope_violation"):
            if float(answers[question_id].value) >= REVISION_PROBABILITY:
                revise.append(question_id)
        for question_id in ("claim_support", "evidence_quality"):
            confidence = answers[question_id].confidence
            if confidence is None or confidence < MIN_CONFIDENCE:
                review.append(f"{question_id}_low_confidence")
        for question_id in ("contradiction_present", "scope_violation", "human_review"):
            if float(answers[question_id].value) >= REVIEW_PROBABILITY:
                review.append(f"{question_id}_uncertainty")
        if revise:
            return GateDecision(GateDisposition.REVISE, tuple(revise + review))
        if review:
            return GateDecision(GateDisposition.HUMAN_REVIEW, tuple(review))
        return GateDecision(GateDisposition.PASS, ("bounded_support_requirements_met",))
