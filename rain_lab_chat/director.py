"""Dynamic per-turn instruction generation for agents."""

import random
from typing import List

from rain_lab_chat.config import Config
from rain_lab_chat.agents import Agent

class RainLabDirector:

    """Directs agents with dynamic, citation-focused instructions"""

    

    def __init__(self, config: Config, paper_list: List[str]):

        self.config = config

        self.paper_list = paper_list

    

    def get_dynamic_instruction(self, agent: Agent, turn_count: int, topic: str) -> str:

        """Generate instructions that force citation"""

        

        # Opening move

        if turn_count == 0 and agent.name == "James":

            return f"Open the meeting. Survey the loaded research papers and identify which ones discuss '{topic}'. Quote key definitions or findings."

        # Mid-meeting paper focus

        if turn_count == 4 and self.paper_list:

            random_paper = random.choice(self.paper_list)

            if agent.name == "James":

                return f"Focus specifically on '{random_paper}'. What does it say about '{topic}'? Quote directly."

        

        # Research-Specific Instructions

        instructions = {

            "James": [

                f"Quote a specific finding or definition of '{topic}' from the papers. Which paper is it from?",

                f"Synthesize: How do different papers relate to '{topic}'? Reference specific papers.",

                f"What is the core innovation regarding '{topic}' according to the text? Quote it.",

                f"Find and compare TWO different mentions of '{topic}' from different papers.",

            ],

            "Jasmine": [

                f"Critique implementation: What do the papers say about building '{topic}'? Quote constraints.",

                f"Do the papers mention energy/hardware requirements for '{topic}'? Quote specifics.",

                f"Find experimental setups in the text related to '{topic}'. Quote parameters.",

                f"What materials or components are mentioned for '{topic}'? Quote from the papers.",

            ],

            "Luca": [

                f"Describe the theoretical geometry of '{topic}' using equations from the text. Quote them.",

                f"Visualize '{topic}' using descriptions from the papers. Quote the relevant passages.",

                f"What topology or structure defines '{topic}' in the text? Quote mathematical descriptions.",

                f"Find field equations related to '{topic}'. Quote and explain them.",

            ],

            "Elena": [

                f"Check mathematical consistency of '{topic}' in the papers. Quote specific equations.",

                f"Do papers define limits (bits, entropy, error) for '{topic}'? Quote numerical values.",

                f"Compare '{topic}' in the text to standard QM. Quote differences explicitly.",

                f"Find information-theoretic bounds on '{topic}'. Quote from papers.",

            ]

        }

        

        if agent.name in instructions:

            return random.choice(instructions[agent.name])

        

        return f"Analyze '{topic}' strictly from the research papers. Quote your sources."

# --- LOG MANAGER ---
