"""Research agent definitions and factory."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class Agent:

    """Agent data structure"""

    name: str

    role: str

    personality: str

    focus: str

    color: str

    agreeableness: float = 0.5  # 0.0 = combative, 1.0 = very agreeable

    opinion_strength: str = "moderate"  # weak, moderate, strong

    citations_made: int = 0

    _soul_cache: str = field(default="", repr=False)  # Cached soul content

    def load_soul(self, library_path: str, verbose: bool = False) -> str:

        """Load soul from external file, with fallback to generated soul"""

        soul_filename = f"{self.name.upper()}_SOUL.md"

        soul_path = Path(library_path) / soul_filename

        if soul_path.exists():

            try:

                with open(soul_path, 'r', encoding='utf-8') as f:

                    external_soul = f.read()

                # Append critical meeting rules to external soul

                meeting_rules = f"""

# MEETING RULES (CRITICAL)

- You are ONLY {self.name}. Never speak as another team member.

- Never write dialogue for others (no "James:" or "Jasmine would say...")

- Never echo or repeat what colleagues just said - use your OWN words

- Be concise: 50-80 words max per response

- Cite sources: [from filename.md]

"""

                self._soul_cache = external_soul + meeting_rules

                if verbose:

                    print(f"     ✓ Loaded soul: {soul_filename}")

                return self._soul_cache

            except Exception as e:

                if verbose:

                    print(f"     ⚠️ Error loading {soul_filename}: {e}")

        else:

            if verbose:

                print(f"     ⚠️ No soul file found: {soul_filename} (using default)")

        # Fallback to generated soul

        self._soul_cache = self._generated_soul()

        return self._soul_cache

    def _generated_soul(self) -> str:

        """Fallback generated soul if file doesn't exist"""

        return f"""# YOUR IDENTITY (NEVER BREAK CHARACTER)

NAME: {self.name.upper()}

ROLE: {self.role}

PERSONALITY: {self.personality}

SCIENTIFIC FOCUS: {self.focus}

# CRITICAL IDENTITY RULES

- You are ONLY {self.name}. Never speak as another team member.

- Never write dialogue for others (no "James would say..." or "Jasmine:")

- Never echo or repeat what colleagues just said - use your OWN words

- Bring YOUR unique perspective based on your role and focus

# CITATION RULES

1. The "RESEARCH DATABASE" below is your ONLY factual source

2. Use "exact quotation marks" when citing specific data

3. Cite sources: [from filename.md]

4. If info isn't in papers, say: "The papers don't cover this"

5. For inferences beyond text, prefix with [REDACTED]

# CONVERSATION STYLE

- Be concise: 50-80 words max

- Add NEW information each turn - don't rehash what was said

- Ask questions to drive discussion forward

"""

    @property

    def soul(self) -> str:

        """Return cached soul or generated fallback"""

        if self._soul_cache:

            return self._soul_cache

        return self._generated_soul()

class RainLabAgentFactory:

    """Factory for creating the Physics Research Team"""

    @staticmethod

    def create_team() -> List[Agent]:

        return [

            Agent(

                name="James",

                role="Lead Scientist / Technician",

                personality="Brilliant pattern-seeker with strong opinions. Will defend his geometric intuitions passionately but can be swayed by solid evidence. Sometimes dismissive of overly cautious approaches.",

                focus="Analyze the papers for 'Resonance', 'Geometric Structures', and 'Frequency' data. Connect disparate findings.",

                color="\033[92m",  # Green

                agreeableness=0.5,

                opinion_strength="strong"

            ),

            Agent(

                name="Jasmine",

                role="Hardware Architect",

                personality="Highly skeptical devil's advocate. Loves shooting down impractical ideas. Will argue that something can't be built unless proven otherwise. Finds theoretical discussions frustrating without concrete specs.",

                focus="Check the papers for 'Feasibility', 'Energy Requirements', and 'Material Constraints'. Ask: Can we actually build this?",

                color="\033[93m",  # Yellow

                agreeableness=0.2,

                opinion_strength="strong"

            ),

            Agent(

                name="Luca",

                role="Field Tomographer / Theorist",

                personality="Diplomatic peacemaker who tries to find common ground. Sees beauty in everyone's perspective. Rarely directly disagrees but will gently suggest alternatives. Sometimes too accommodating.",

                focus="Analyze the 'Topology', 'Fields', and 'Gradients' described in the papers. Describe the geometry of the theory.",

                color="\033[96m",  # Cyan

                agreeableness=0.9,

                opinion_strength="weak"

            ),

            Agent(

                name="Elena",

                role="Quantum Information Theorist",

                personality="Brutally honest math purist. Has zero patience for hand-waving or vague claims. Will interrupt to demand mathematical rigor. Often clashes with James's intuitive approach.",

                focus="Analyze 'Information Bounds', 'Computational Limits', and 'Entropy' in the research. Look for mathematical consistency.",

                color="\033[95m",  # Magenta

                agreeableness=0.6,

                opinion_strength="strong"

            ),

        ]

# --- CONTEXT MANAGEMENT ---
