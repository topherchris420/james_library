"""
R.A.I.N. Lab Meeting Workflow Module

Structured meeting phases for more productive research discussions.
"""

from enum import Enum
from typing import List, Dict, Callable, Optional
from dataclasses import dataclass, field


class MeetingPhase(Enum):
    """Meeting phase enumeration."""
    OPENING = "opening"           # Topic framing + paper survey
    INVESTIGATION = "investigation"  # Deep dives into specific papers
    DEBATE = "debate"            # Organized pro/con discussions
    SYNTHESIS = "synthesis"       # Integration of viewpoints
    ACTION_ITEMS = "action"       # Specific next steps


@dataclass
class PhaseConfig:
    """Configuration for a meeting phase."""
    name: str
    description: str
    turns: int
    prompt_template: str
    required_tools: List[str] = field(default_factory=list)


# Default phase configurations
PHASE_CONFIGS = {
    MeetingPhase.OPENING: PhaseConfig(
        name="Opening",
        description="Topic framing and initial paper survey",
        turns=2,
        prompt_template="""
PHASE: OPENING

The meeting has just begun. Your task is to:
1. Frame the topic for the team
2. Survey available literature quickly
3. Identify key papers or resources
4. Open the discussion naturally

Format your response as a meeting opener.
Start with: "Hey team, today we're looking into..."
""",
        required_tools=["list_papers", "search_library", "read_paper"]
    ),
    MeetingPhase.INVESTIGATION: PhaseConfig(
        name="Investigation",
        description="Deep dives into specific papers and data",
        turns=4,
        prompt_template="""
PHASE: INVESTIGATION

Dive deeper into specific papers or concepts. Your task is to:
1. Read and analyze specific papers in detail
2. Extract key findings, metrics, or claims
3. Compare across sources
4. Identify connections to the topic

Use tools extensively. Be specific about what you find.
""",
        required_tools=["read_paper", "search_web", "semantic_search"]
    ),
    MeetingPhase.DEBATE: PhaseConfig(
        name="Debate",
        description="Organized discussion of different viewpoints",
        turns=4,
        prompt_template="""
PHASE: DEBATE

Engage in structured debate. Your task is to:
1. Present your perspective on the topic
2. Agree or disagree with previous points
3. Bring evidence to support your position
4. Challenge weak arguments

Focus on substantive disagreement, not nitpicking.
""",
        required_tools=[]
    ),
    MeetingPhase.SYNTHESIS: PhaseConfig(
        name="Synthesis",
        description="Integration of different viewpoints",
        turns=2,
        prompt_template="""
PHASE: SYNTHESIS

Integrate the discussion. Your task is to:
1. Summarize key points from the discussion
2. Identify areas of consensus
3. Highlight remaining disagreements
4. Connect different perspectives

What do we collectively understand now that we didn't before?
""",
        required_tools=[]
    ),
    MeetingPhase.ACTION_ITEMS: PhaseConfig(
        name="Action Items",
        description="Specific next steps and follow-ups",
        turns=2,
        prompt_template="""
PHASE: ACTION ITEMS

Define next steps. Your task is to:
1. Summarize key conclusions
2. Identify specific follow-up actions
3. Note papers to read later
4. Suggest future meeting topics

Be concrete and actionable.
""",
        required_tools=[]
    ),
}


@dataclass
class MeetingWorkflow:
    """Manages structured meeting workflow."""

    current_phase: MeetingPhase = MeetingPhase.OPENING
    phase_turn: int = 0
    phase_configs: Dict[MeetingPhase, PhaseConfig] = field(default_factory=dict)
    phase_history: List[Dict] = field(default_factory=list)

    def __post_init__(self):
        """Initialize with default configs."""
        self.phase_configs = PHASE_CONFIGS.copy()

    def get_current_phase_config(self) -> PhaseConfig:
        """Get configuration for current phase."""
        return self.phase_configs.get(self.current_phase)

    def advance_phase(self):
        """Move to the next phase."""
        phases = list(MeetingPhase)
        try:
            current_idx = phases.index(self.current_phase)
            if current_idx < len(phases) - 1:
                self.current_phase = phases[current_idx + 1]
                self.phase_turn = 0
        except ValueError:
            pass

    def should_advance_phase(self) -> bool:
        """Check if it's time to advance to next phase."""
        config = self.get_current_phase_config()
        if config:
            return self.phase_turn >= config.turns
        return False

    def advance_turn(self):
        """Advance the turn counter and check for phase change."""
        self.phase_turn += 1

        if self.should_advance_phase():
            # Record phase in history
            self.phase_history.append({
                "phase": self.current_phase.value,
                "turns": self.phase_turn
            })
            self.advance_phase()

    def get_phase_prompt(self) -> str:
        """Get the prompt for current phase."""
        config = self.get_current_phase_config()
        if config:
            return config.prompt_template
        return ""

    def get_meeting_summary(self) -> str:
        """Get summary of the meeting workflow."""
        lines = ["MEETING PHASES:", "=" * 40]
        for phase in MeetingPhase:
            config = self.phase_configs.get(phase)
            if config:
                marker = "→ " if phase == self.current_phase else "   "
                lines.append(f"{marker}{config.name}: {config.description}")
        return "\n".join(lines)


def create_workflow(mode: str = "standard") -> MeetingWorkflow:
    """Create a meeting workflow based on mode.

    Args:
        mode: Workflow mode ('standard', 'quick', 'deep', 'debate')

    Returns:
        Configured MeetingWorkflow
    """
    workflow = MeetingWorkflow()

    if mode == "quick":
        # Short meeting: skip some phases
        workflow.phase_configs = {
            MeetingPhase.OPENING: PhaseConfig("Opening", "Quick topic framing", 1, ""),
            MeetingPhase.INVESTIGATION: PhaseConfig("Investigation", "Quick scan", 1, ""),
            MeetingPhase.SYNTHESIS: PhaseConfig("Synthesis", "Quick summary", 1, ""),
        }
    elif mode == "deep":
        # Extended meeting: more investigation
        workflow.phase_configs = {
            MeetingPhase.OPENING: PhaseConfig("Opening", "Topic framing", 2, ""),
            MeetingPhase.INVESTIGATION: PhaseConfig("Investigation", "Deep analysis", 6, ""),
            MeetingPhase.DEBATE: PhaseConfig("Debate", "Extended debate", 4, ""),
            MeetingPhase.SYNTHESIS: PhaseConfig("Synthesis", "Full synthesis", 2, ""),
            MeetingPhase.ACTION_ITEMS: PhaseConfig("Action Items", "Next steps", 2, ""),
        }
    elif mode == "debate":
        # Debate-focused: more debate time
        workflow.phase_configs = {
            MeetingPhase.OPENING: PhaseConfig("Opening", "Topic framing", 1, ""),
            MeetingPhase.INVESTIGATION: PhaseConfig("Investigation", "Background", 2, ""),
            MeetingPhase.DEBATE: PhaseConfig("Debate", "Extended debate", 6, ""),
            MeetingPhase.SYNTHESIS: PhaseConfig("Synthesis", "Resolution", 2, ""),
        }
    else:
        # Standard workflow
        workflow.phase_configs = PHASE_CONFIGS.copy()

    return workflow
