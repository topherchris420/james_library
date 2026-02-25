"""
R.A.I.N. Lab Log Manager Module

Handles session logging to file.
"""

from datetime import datetime
from pathlib import Path


class LogManager:
    def __init__(self, log_path: str):
        self.log_path = Path(log_path)

    def initialize(self, topic: str):
        header = f"""
{'='*70}
R.A.I.N. LAB RESEARCH
{'='*70}
TOPIC: {topic}
DATE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
MODE: Recursive Language Model - Code Execution Enabled
{'='*70}

"""
        self._write(header)

    def log(self, agent_name: str, content: str):
        self._write(f"**{agent_name}:** {content}\n\n")

    def finalize(self):
        self._write(f"\n{'='*70}\nSESSION ENDED\n{'='*70}\n")

    def _write(self, text: str):
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(text)
