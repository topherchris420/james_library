"""R.A.I.N. Lab 5-stage peer critique workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
        required_tools=["godot_event_bridge", "physics_tools"],
    ),
    MeetingStage.SYNTHESIS: StageConfig(
        name="Stage 3: Synthesis",
        description="Compile raw outputs into a structured research summary.",
        prompt_template=(
            "STAGE 3 — SYNTHESIS\n"
            "Summarize method, observations, quantitative outputs, and limitations."
        ),
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
            "If score >= 8: persist discovery and notify human.\n"
            "If score < 8: mutate hypothesis and repeat from Stage 1."
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


@dataclass
class MeetingWorkflow:
    """State manager for the strict 5-stage peer critique pipeline."""

    current_stage: MeetingStage = MeetingStage.HYPOTHESIS
    stage_configs: dict[MeetingStage, StageConfig] = field(default_factory=lambda: STAGE_CONFIGS.copy())
    history: list[dict[str, Any]] = field(default_factory=list)
    record: CycleRecord = field(default_factory=CycleRecord)

    def get_current_stage_config(self) -> StageConfig:
        return self.stage_configs[self.current_stage]

    def get_stage_prompt(self) -> str:
        return self.get_current_stage_config().prompt_template

    def can_interrupt(self) -> bool:
        return self.get_current_stage_config().allow_interruptions

    def set_hypothesis(self, hypothesis: str) -> None:
        self.record.hypothesis = hypothesis.strip()
        self.current_stage = MeetingStage.SIMULATION

    def set_simulation_data(self, payload: dict[str, Any]) -> None:
        self.record.simulation_data = payload
        self.current_stage = MeetingStage.SYNTHESIS

    def set_synthesis(self, summary: str) -> None:
        self.record.synthesis_summary = summary.strip()
        self.current_stage = MeetingStage.PEER_CRITIQUE

    def set_peer_critique(self, reviewer: str, score: int, feedback: str) -> None:
        normalized = int(score)
        if normalized < 1 or normalized > 10:
            raise ValueError("Peer critique score must be between 1 and 10")
        self.record.reviewer = reviewer.strip()
        self.record.critique_score = normalized
        self.record.critique_feedback = feedback.strip()
        self.current_stage = MeetingStage.DISCOVERY

    def finalize_discovery_gate(self) -> bool:
        """Return True when accepted (score >= 8), else False and loop to hypothesis."""

        score = self.record.critique_score
        if score is None:
            raise ValueError("Cannot gate discovery before peer critique score is set")

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

    def get_meeting_summary(self) -> str:
        lines = ["RESEARCH PIPELINE:", "=" * 40]
        for stage in MeetingStage:
            config = self.stage_configs[stage]
            marker = "→ " if stage == self.current_stage else "   "
            lines.append(f"{marker}{config.name}: {config.description}")
        return "\n".join(lines)


def create_workflow(mode: str = "strict") -> MeetingWorkflow:
    """Create a strict 5-stage workflow.

    Args:
        mode: Reserved for compatibility with older callers.
    """

    _ = mode
    return MeetingWorkflow()
