"""Meeting log manager with rotation and archival."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .config import Config


class LogManager:
    """Handles meeting transcription with metadata and log rotation."""

    MAX_LOG_SIZE_BYTES = 150_000

    def __init__(self, config: Config):
        self.config = config
        self.log_path = Path(config.library_path) / config.meeting_log
        self.archive_dir = Path(config.library_path) / "meeting_archives"
        self._check_and_rotate()

    def _check_and_rotate(self):
        """Archive log if it exceeds size limit."""
        if not self.log_path.exists():
            return
        try:
            file_size = self.log_path.stat().st_size
            if file_size > self.MAX_LOG_SIZE_BYTES:
                self._rotate_log()
        except Exception as e:
            print(f"\u26a0\ufe0f  Log rotation check failed: {e}")

    def _rotate_log(self):
        """Move current log to archive with timestamp."""
        try:
            self.archive_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"MEETING_LOG_{timestamp}.md"
            archive_path = self.archive_dir / archive_name

            shutil.move(str(self.log_path), str(archive_path))

            print(f"\U0001f4c1 Log rotated to: {archive_path.name}")
            print(f"   Old log archived ({archive_path.stat().st_size // 1024}KB)")
        except Exception as e:
            print(f"\u26a0\ufe0f  Log rotation failed: {e}")

    def archive_now(self):
        """Force archive the current log (callable externally)."""
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            self._rotate_log()
            print("\u2705 Log archived successfully")
        else:
            print("\u2139\ufe0f  No log to archive")

    def initialize_log(self, topic: str, paper_count: int):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        header = f"""

{"=" * 70}

R.A.I.N. LAB RESEARCH MEETING

{"=" * 70}

TOPIC: {topic}

DATE: {timestamp}

PAPERS LOADED: {paper_count}

MODEL: CUSTOM

MODE: GENIUS

{"=" * 70}



"""

        self._append_to_log(header)

    def log_statement(self, agent_name: str, content: str, metadata: Optional[Dict] = None):
        """Log with optional citation metadata."""
        entry = f"**{agent_name}:** {content}\n"

        if metadata and metadata.get("verified"):
            citations = metadata["verified"]
            entry += f"   \u2514\u2500 Citations: {len(citations)} verified\n"
            for quote, source in citations[:2]:
                entry += f'      \u2022 "{quote[:50]}..." [from {source}]\n'

        entry += "\n"
        self._append_to_log(entry)

    def finalize_log(self, stats: str):
        footer = f"""

{"=" * 70}

SESSION ENDED

{stats}

{"=" * 70}

"""

        self._append_to_log(footer)

    def _append_to_log(self, text: str):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            print(f"\u26a0\ufe0f  Logging error: {e}")
