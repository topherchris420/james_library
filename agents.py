"""R.A.I.N. Lab Agents Module.

Defines research agent personas and stage-aware prompt scaffolding.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


STAGE_PROTOCOL = """
# 5-STAGE RESEARCH PROTOCOL (MANDATORY)
The meeting follows this strict sequence:
1) HYPOTHESIS: propose concrete resonance parameters.
2) SIMULATION: trigger Godot/local physics verification.
3) SYNTHESIS: produce structured summary from raw data.
4) PEER CRITIQUE: secondary reviewer scores 1-10.
5) DISCOVERY: score >=8 persists; score <8 mutates hypothesis.

Human interruptions are always allowed. Keep conversational tone while still satisfying stage outputs.
"""


PEER_REVIEW_PROTOCOL = """
# PEER REVIEWER MODE (STAGE 4)
When assigned as reviewer, output format is mandatory:
- reviewer: <your name>
- score: <integer 1-10>
- physical_viability: <short assessment>
- novelty: <short assessment>
- coherence: <short assessment>
- verdict: <accept if >=8 else reject>
- required_mutations: <what must change when score <8>

Anti-grade-inflation rules:
- Do not assign >=8 without concrete support in simulation and synthesis evidence.
- Penalize missing quantitative evidence.
- Penalize contradictions or vague claims.
"""


@dataclass
class Agent:
    name: str
    role: str
    focus: str
    color: str
    tool_instruction: str
    _soul_cache: str = field(default="", repr=False)

    def load_soul(self, library_path: str) -> str:
        """Load soul from external .md file."""
        soul_path = Path(library_path) / f"{self.name.upper()}_SOUL.md"

        if soul_path.exists():
            with open(soul_path, "r", encoding="utf-8-sig") as file:
                external_soul = file.read()

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
report = invoke_peer_review(document, topic, rounds=6) # Adversarial swarm review
result = verify_logic("(H1 OR H2) AND (NOT H1)")       # Formal SAT verification
```

## Formal Logic Engine — verify_logic()
You have access to a **deterministic formal verification tool** called `verify_logic`.
When debating a hypothesis, translate your core logical argument into a boolean
formula and pass it to this tool.  It runs a DPLL SAT solver — no hallucination,
no approximation, only math.

**JSON schema:**
```json
Input:  {"formula": "(A OR B) AND (NOT A OR C) AND (NOT C)"}
Output: {"satisfiable": true, "model": {"A": false, "B": true, "C": false}}
   or:  {"satisfiable": false}
   or:  {"error": "parse error: ..."}
```

**Operators:** AND, OR, NOT (case-insensitive). Variables: alphanumeric identifiers.
**When to use:** hypothesis consistency checks, contradiction detection, constraint satisfaction.

{STAGE_PROTOCOL}

{PEER_REVIEW_PROTOCOL}

{self.tool_instruction}

RULES:
- You are ONLY {self.name}. Never speak as another team member.
- Be concise: 80-120 words max per response unless structured output requires more.
- When you need data, write code to get it.
- Use ONLY research papers from this library and web search.
- Only use: read_paper(), search_web(), list_papers(), search_library(), semantic_search(),
  visualize_concepts(), generate_mermaid(), remember_entity(), recall_entity(), invoke_peer_review(),
  verify_logic()
"""
            self._soul_cache = external_soul + rlm_rules
            print(f"     Soul loaded: {self.name.upper()}_SOUL.md")
            return self._soul_cache

        return self._build_default_personality()

    def _build_default_personality(self) -> str:
        """Build default personality if no soul file exists."""
        return f"""You are {self.name}, {self.role}.

{self.focus}

{STAGE_PROTOCOL}

{PEER_REVIEW_PROTOCOL}

{self.tool_instruction}

RULES:
- You are ONLY {self.name}. Never speak as another team member.
- Be concise: 80-120 words max per response unless structured output requires more.
- Use ONLY research papers from this library and web search for evidence.
- Use tools when needed: read_paper(), search_web(), list_papers(), search_library(), semantic_search()
"""

    @property
    def soul(self) -> str:
        return self._soul_cache if self._soul_cache else f"You are {self.name}."


def create_team(mode: str = "standard") -> List[Agent]:
    """Create the research council. Modes: standard, extended, critique, synthesis."""
    if mode == "extended":
        return create_extended_team()
    if mode == "critique":
        return create_critique_team()
    if mode == "synthesis":
        return create_synthesis_team()
    return create_standard_team()


def create_standard_team() -> List[Agent]:
    """Create the 4-agent research council (default)."""
    return [
        Agent(
            name="James",
            role="Lead Scientist/Technician",
            focus="Physics simulations and research analysis",
            color="\033[92m",
            tool_instruction="""
AVAILABLE: read_paper(), search_web(), list_papers()
BANNED: llm_query(), FINAL_VAR(), FINAL(), SHOW_VARS(), context
RESPOND: 50-100 words, conversational, as a scientist.
""",
        ),
        Agent(
            name="Jasmine",
            role="Hardware Architect",
            focus="Check feasibility, energy requirements, and material constraints.",
            color="\033[93m",
            tool_instruction=(
                "JASMINE: In Stage 4 peer critique, score strictly and reduce points for unsupported hardware claims. "
                "Outside Stage 4, use search_web() for real-world constraints and hardware specs."
            ),
        ),
        Agent(
            name="Elena",
            role="Quantum Information Theorist / Librarian of Resonance",
            focus=(
                "Check information bounds and computational limits with mathematical rigor. "
                "Maintain the experimental knowledge vault."
            ),
            color="\033[95m",
            tool_instruction=(
                "ELENA: Audit computational feasibility. Challenge hand-waving with math. "
                "Use verify_logic() to formally verify logical consistency of hypotheses "
                "before accepting them.\n\n"
                "VAULT OPERATIONS (unrestricted): file_read(), file_write(), file_edit(), "
                "glob_search() — use these to navigate and maintain the papers/ vault. "
                "After Resonance Validation sessions, synthesize findings into papers/ using "
                "bidirectional wikilinks [[Document Name]]. "
                "Preserve all existing physics equations — never delete them."
            ),
        ),
        Agent(
            name="Luca",
            role="Field Tomographer / Theorist",
            focus="Analyze topology, fields, and gradients for theoretical consistency.",
            color="\033[96m",
            tool_instruction=(
                "LUCA: In Stage 4 peer critique, avoid grade inflation and justify every point with evidence. "
                "Outside Stage 4, audit theoretical consistency and structure."
            ),
        ),
    ]


def create_extended_team() -> List[Agent]:
    """Create the 7-agent extended research council with new roles."""
    base = create_standard_team()
    base.extend(
        [
            Agent(
                name="Alex",
                role="External Reviewer / Skeptic",
                focus="Brings outside perspective and challenges assumptions.",
                color="\033[91m",
                tool_instruction=(
                    "ALEX: Act as a peer reviewer. Challenge assumptions, identify gaps, question methodology."
                ),
            ),
            Agent(
                name="Sarah",
                role="Experimentalist",
                focus="Lab feasibility, measurement methodology, and practical testing design.",
                color="\033[94m",
                tool_instruction="SARAH: Focus on experimental validation. Define measurements and controls.",
            ),
            Agent(
                name="Diana",
                role="Futurist",
                focus="Projects long-term applications and impact scenarios.",
                color="\033[97m",
                tool_instruction="DIANA: Project long-term implications while preserving evidence-grounded claims.",
            ),
        ]
    )
    return base


def create_critique_team() -> List[Agent]:
    """Create a critique-focused team with Devil's Advocate."""
    base = create_standard_team()
    base.append(
        Agent(
            name="Eve",
            role="Devil's Advocate",
            focus="Systematically tears down proposals to find weaknesses.",
            color="\033[90m",
            tool_instruction="EVE: Find every flaw. Challenge every assumption. Stress-test methodology and evidence.",
        )
    )
    return base


def create_synthesis_team() -> List[Agent]:
    """Create a synthesis-focused team with integrator."""
    base = create_standard_team()
    base.append(
        Agent(
            name="Ryan",
            role="The Synthesizer",
            focus="Combines viewpoints, identifies consensus, and highlights disagreements.",
            color="\033[93m",
            tool_instruction="RYAN: Integrate perspectives and produce structured synthesis summaries.",
        )
    )
    return base
