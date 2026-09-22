"""R.A.I.N. Lab 5-stage peer critique workflow."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from james_library.judgment import ClaimEvidence, JudgmentEnvelope, JudgmentService


class MeetingStage(Enum):
    """Strict research state machine stages."""

    HYPOTHESIS = "hypothesis"
    SIMULATION = "simulation"
    SYNTHESIS = "synthesis"
    PEER_CRITIQUE = "peer_critique"
    DISCOVERY = "discovery"


@dataclass
class StageConfig:
    """Configuration and prompt contract for each stage."""

    name: str
    description: str
    prompt_template: str
    required_tools: list[str] = field(default_factory=list)
    allow_interruptions: bool = True


STAGE_CONFIGS: dict[MeetingStage, StageConfig] = {
    MeetingStage.HYPOTHESIS: StageConfig(
        name="Stage 1: Hypothesis",
        description="Propose specific acoustic resonance parameters.",
        prompt_template=(
            "STAGE 1 — HYPOTHESIS\n"
            "Propose concrete resonance parameters (frequency, amplitude, geometry, medium).\n"
            "Be specific and measurable."
        ),
    ),
    MeetingStage.SIMULATION: StageConfig(
        name="Stage 2: Simulation",
        description="Verify the hypothesis via Godot/local physics tools.",
        prompt_template=(
            "STAGE 2 — SIMULATION\n"
            "Run simulation checks against the current hypothesis.\n"
            "Trigger Godot visualization and capture raw outputs."
        ),
        required_tools=["physics_tools"],
    ),
    MeetingStage.SYNTHESIS: StageConfig(
        name="Stage 3: Synthesis",
        description="Compile raw outputs into a structured research summary.",
        prompt_template=("STAGE 3 — SYNTHESIS\nSummarize method, observations, quantitative outputs, and limitations."),
    ),
    MeetingStage.PEER_CRITIQUE: StageConfig(
        name="Stage 4: Peer Critique",
        description="Secondary agent scores physical viability, novelty, and coherence.",
        prompt_template=(
            "STAGE 4 — PEER CRITIQUE\n"
            "Reviewer MUST produce a score from 1 to 10 with rationale for:\n"
            "- physical viability\n"
            "- novelty\n"
            "- coherence"
        ),
    ),
    MeetingStage.DISCOVERY: StageConfig(
        name="Stage 5: Discovery",
        description="Gate outcomes to truth layer + P2P publish or loopback mutation.",
        prompt_template=(
            "STAGE 5 — DISCOVERY\n"
            "If score < 8: mutate the hypothesis and repeat from Stage 1.\n"
            "If score >= 8: apply every configured promotion gate. Persist and notify "
            "only when all enabled gates pass; disabled gates preserve score-only behavior."
        ),
    ),
}


@dataclass
class CycleRecord:
    """Data accumulated across one critique loop iteration."""

    iteration: int = 1
    hypothesis: str = ""
    simulation_data: dict[str, Any] = field(default_factory=dict)
    synthesis_summary: str = ""
    reviewer: str = ""
    critique_score: int | None = None
    critique_feedback: str = ""
    discovery_accepted: bool = False
    mutation_notes: str = ""
    judgment: JudgmentEnvelope | None = None


@dataclass
class MeetingWorkflow:
    """State manager for the strict 5-stage peer critique pipeline."""

    current_stage: MeetingStage = MeetingStage.HYPOTHESIS
    stage_configs: dict[MeetingStage, StageConfig] = field(default_factory=lambda: STAGE_CONFIGS.copy())
    history: list[dict[str, Any]] = field(default_factory=list)
    record: CycleRecord = field(default_factory=CycleRecord)
    judgment_service: JudgmentService | None = field(default=None, repr=False)
    judgment_recorder: Callable[[JudgmentEnvelope], None] | None = field(default=None, repr=False)
    _gate_snapshot: tuple[Any, ...] | None = field(default=None, init=False, repr=False)
    _gate_accepted: bool = field(default=False, init=False, repr=False)

    def _invalidate_judgment(self) -> None:
        self.record.judgment = None
        self.record.discovery_accepted = False
        self._gate_snapshot = None

    def get_current_stage_config(self) -> StageConfig:
        return self.stage_configs[self.current_stage]

    def get_stage_prompt(self) -> str:
        return self.get_current_stage_config().prompt_template

    def can_interrupt(self) -> bool:
        return self.get_current_stage_config().allow_interruptions

    def set_hypothesis(self, hypothesis: str) -> None:
        self._invalidate_judgment()
        if self.judgment_service is not None:
            self.record.simulation_data = {}
            self.record.synthesis_summary = ""
            self.record.critique_score = None
            self.record.critique_feedback = ""
            self.record.reviewer = ""
        self.record.hypothesis = hypothesis.strip()
        self.current_stage = MeetingStage.SIMULATION

    def set_simulation_data(self, payload: dict[str, Any]) -> None:
        self._invalidate_judgment()
        if self.judgment_service is not None:
            self.record.critique_score = None
            self.record.synthesis_summary = ""
        self.record.simulation_data = deepcopy(payload)
        self.current_stage = MeetingStage.SYNTHESIS

    def set_synthesis(self, summary: str) -> None:
        self._invalidate_judgment()
        if self.judgment_service is not None:
            self.record.critique_score = None
        self.record.synthesis_summary = summary.strip()
        self.current_stage = MeetingStage.PEER_CRITIQUE

    def set_peer_critique(self, reviewer: str, score: int, feedback: str) -> None:
        normalized = int(score)
        if normalized < 1 or normalized > 10:
            raise ValueError("Peer critique score must be between 1 and 10")
        self._invalidate_judgment()
        self.record.reviewer = reviewer.strip()
        self.record.critique_score = normalized
        self.record.critique_feedback = feedback.strip()
        self.current_stage = MeetingStage.DISCOVERY

    def finalize_discovery_gate(self, *, evidence: ClaimEvidence | None = None) -> bool:
        """Promote on peer score and, when enabled, independent bounded judgment.

        Evidence is deliberately supplied by the host, never extracted from chat,
        loaded papers, or private memory. A held result requires an explicit new
        critique/evidence submission; repeated reads do not repeat remote calls.
        """

        score = self.record.critique_score
        if score is None:
            raise ValueError("Cannot gate discovery before peer critique score is set")

        if self.judgment_service is not None:
            return self._finalize_typed_gate(score, evidence)

        accepted = score >= 8
        self.record.discovery_accepted = accepted
        self.history.append(
            {
                "iteration": self.record.iteration,
                "hypothesis": self.record.hypothesis,
                "score": score,
                "accepted": accepted,
                "reviewer": self.record.reviewer,
            }
        )

        if accepted:
            return True

        self.record.iteration += 1
        self.record.mutation_notes = self.record.critique_feedback
        self.current_stage = MeetingStage.HYPOTHESIS
        return False

    def _finalize_typed_gate(self, score: int, evidence: ClaimEvidence | None) -> bool:
        from james_library.judgment import GateDisposition

        snapshot = (
            self.record.hypothesis, score, self.record.reviewer,
            self.record.critique_feedback, self.record.synthesis_summary,
            deepcopy(self.record.simulation_data), evidence,
        )
        if self._gate_snapshot == snapshot:
            return self._gate_accepted

        judgment = None
        reasons: tuple[str, ...]
        if score < 8:
            disposition = GateDisposition.REVISE
            reasons = ("peer_score_below_threshold",)
        else:
            if evidence is None:
                raise ValueError("Enabled judgment requires explicit claim evidence")
            if (evidence.claim.strip() != self.record.hypothesis
                    or evidence.peer_critique.strip() != self.record.critique_feedback):
                raise ValueError("Judgment evidence must match the current claim and peer critique")
            service = self.judgment_service
            if service is None:
                raise ValueError("Enabled judgment requires a judgment service")
            judgment = service.evaluate(evidence)
            # Persistence must succeed before discovery can be accepted.
            if self.judgment_recorder is not None:
                self.judgment_recorder(judgment)
            disposition = judgment.decision.disposition
            reasons = judgment.decision.reason_codes

        accepted = disposition is GateDisposition.PASS
        self.record.judgment = judgment
        self.record.discovery_accepted = accepted
        self.history.append({
            "iteration": self.record.iteration,
            "hypothesis": self.record.hypothesis,
            "score": score,
            "accepted": accepted,
            "reviewer": self.record.reviewer,
            "gate_disposition": disposition.value,
            "reason_codes": list(reasons),
            "judgment_id": judgment.judgment_id if judgment is not None else None,
        })
        self._gate_snapshot = snapshot
        self._gate_accepted = accepted
        if accepted:
            self.current_stage = MeetingStage.DISCOVERY
        elif disposition is GateDisposition.REVISE:
            self.record.iteration += 1
            self.record.mutation_notes = self.record.critique_feedback
            self.current_stage = MeetingStage.HYPOTHESIS
        else:
            # A human review or provider failure is held, never an automatic retry.
            self.current_stage = MeetingStage.PEER_CRITIQUE
        return accepted

    def get_meeting_summary(self) -> str:
        lines = ["RESEARCH PIPELINE:", "=" * 40]
        for stage in MeetingStage:
            config = self.stage_configs[stage]
            marker = "→ " if stage == self.current_stage else "   "
            lines.append(f"{marker}{config.name}: {config.description}")
        return "\n".join(lines)


def create_workflow(
    mode: str = "strict", *, judgment_service: JudgmentService | None = None,
    judgment_recorder: Callable[[JudgmentEnvelope], None] | None = None,
) -> MeetingWorkflow:
    """Create a strict 5-stage workflow.

    Args:
        mode: Reserved for compatibility with older callers.
    """

    _ = mode
    return MeetingWorkflow(judgment_service=judgment_service, judgment_recorder=judgment_recorder)
