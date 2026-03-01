"""
R.A.I.N. Lab Agents Module

Defines the research agent personas and team creation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Agent:
    name: str
    role: str
    focus: str
    color: str
    tool_instruction: str
    _soul_cache: str = field(default="", repr=False)

    def load_soul(self, library_path: str) -> str:
        """Load soul from external .md file"""
        soul_path = Path(library_path) / f"{self.name.upper()}_SOUL.md"

        if soul_path.exists():
            with open(soul_path, 'r', encoding='utf-8-sig') as f:
                external_soul = f.read()

            # RLM code execution rules
            rlm_rules = f"""

# CODE EXECUTION
You can execute Python code to access the research library and web.
Available functions (already defined):

```python
content = read_paper("keyword")      # Read a paper from the library
results = search_web("query")        # Search the web
papers = list_papers()               # List available papers
search_results = search_library("query") # Keyword search in library
rag_results = semantic_search("query")   # Semantic search in library
visual = visualize_concepts(["a", "b"]) # Create concept diagrams
mermaid = generate_mermaid("graph TD; A-->B") # Generate diagrams
memory = remember_entity("name", "desc") # Remember entities across sessions
```

{self.tool_instruction}

RULES:
- You are ONLY {self.name}. Never speak as another team member.
- Be concise: 80-120 words max per response.
- When you need data, write code to get it.
- Use ONLY research papers from this library (e.g., Coherence Depth, Discrete Celestial Holography, Location is a Dynamic Variable) and web search.
- Only use: read_paper(), search_web(), list_papers(), search_library(), semantic_search(), visualize_concepts(), generate_mermaid(), remember_entity(), recall_entity()
"""
            self._soul_cache = external_soul + rlm_rules
            print(f"     Soul loaded: {self.name.upper()}_SOUL.md")
            return self._soul_cache

        # Fallback: use built-in personality if no soul file
        return self._build_default_personality()

    def _build_default_personality(self) -> str:
        """Build default personality if no soul file exists."""
        return f"""You are {self.name}, {self.role}.

{self.focus}

{self.tool_instruction}

RULES:
- You are ONLY {self.name}. Never speak as another team member.
- Be concise: 80-120 words max per response.
- Use ONLY research papers from this library and web search for evidence.
- Use tools when needed: read_paper(), search_web(), list_papers(), search_library(), semantic_search()
"""

    @property
    def soul(self) -> str:
        return self._soul_cache if self._soul_cache else f"You are {self.name}."


def create_team(mode: str = "standard") -> List[Agent]:
    """Create the research council. Modes: 'standard', 'extended', 'critique', 'synthesis'"""
    if mode == "extended":
        return create_extended_team()
    elif mode == "critique":
        return create_critique_team()
    elif mode == "synthesis":
        return create_synthesis_team()
    else:
        return create_standard_team()


def create_standard_team() -> List[Agent]:
    """Create the 4-agent research council (default)"""
    return [
        Agent(
            name="James",
            role="Lead Scientist/Technician",
            focus="Physics simulations and research analysis",
            color="\033[92m",  # Green
            tool_instruction="""
AVAILABLE: read_paper(), search_web(), list_papers()
BANNED: llm_query(), FINAL_VAR(), FINAL(), SHOW_VARS(), context
RESPOND: 50-100 words, conversational, as a scientist.
"""
        ),
        Agent(
            name="Jasmine",
            role="Hardware Architect",
            focus="Check 'Feasibility', 'Energy Requirements', 'Material Constraints'. Can we build this?",
            color="\033[93m",  # Yellow
            tool_instruction="JASMINE: You MUST use search_web() to find real-world energy constraints and hardware specifications."
        ),
        Agent(
            name="Elena",
            role="Quantum Information Theorist",
            focus="Check 'Information Bounds', 'Computational Limits'. Demand mathematical rigor.",
            color="\033[95m",  # Magenta
            tool_instruction="ELENA: Audit the code for computational feasibility. Challenge hand-waving with math."
        ),
        Agent(
            name="Luca",
            role="Field Tomographer / Theorist",
            focus="Analyze 'Topology', 'Fields', 'Gradients'. Describe geometry of the theory.",
            color="\033[96m",  # Cyan
            tool_instruction="LUCA: Audit the theoretical consistency. Look for mathematical beauty in the structure."
        ),
    ]


def create_extended_team() -> List[Agent]:
    """Create the 7-agent extended research council with new roles"""
    base = create_standard_team()
    base.extend([
        Agent(
            name="Alex",
            role="External Reviewer / Skeptic",
            focus="Brings outside perspective, challenges assumptions, represents peer review",
            color="\033[91m",  # Red
            tool_instruction="ALEX: Act as a peer reviewer. Challenge assumptions, identify gaps, question methodology."
        ),
        Agent(
            name="Sarah",
            role="Experimentalist",
            focus="Lab feasibility, measurement methodologies, data validation, practical testing",
            color="\033[94m",  # Blue
            tool_instruction="SARAH: Focus on experimental validation. How would we measure this? What controls are needed?"
        ),
        Agent(
            name="Diana",
            role="Futurist",
            focus="Projects applications 10-50 years out, speculative scenarios, long-term impact",
            color="\033[97m",  # White
            tool_instruction="DIANA: Project into the future. What are the long-term implications? How might this evolve?"
        ),
    ])
    return base


def create_critique_team() -> List[Agent]:
    """Create a critique-focused team with Devil's Advocate"""
    base = create_standard_team()
    base.append(
        Agent(
            name="Eve",
            role="Devil's Advocate",
            focus="Systematically tears down proposals to find weaknesses",
            color="\033[90m",  # Gray
            tool_instruction="EVE: Find every flaw. Challenge every assumption. What could possibly go wrong?"
        )
    )
    return base


def create_synthesis_team() -> List[Agent]:
    """Create a synthesis-focused team with integrator"""
    base = create_standard_team()
    base.append(
        Agent(
            name="Ryan",
            role="The Synthesizer",
            focus="Combines viewpoints, identifies consensus, highlights disagreements",
            color="\033[93m",  # Bright Yellow
            tool_instruction="RYAN: Integrate perspectives. What do agents agree on? Where do they disagree? Connect the dots."
        )
    )
    return base
