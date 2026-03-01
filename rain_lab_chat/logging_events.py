"""Meeting transcription, visual event logging, and external mailbox."""

import glob
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from rain_lab_chat._sanitize import sanitize_text
from rain_lab_chat.config import Config

class LogManager:

    """Handles meeting transcription with metadata and log rotation"""

    

    # Maximum log size before auto-rotation (150KB)

    MAX_LOG_SIZE_BYTES = 150_000

    

    def __init__(self, config: Config):

        self.config = config

        self.log_path = Path(config.library_path) / config.meeting_log

        self.archive_dir = Path(config.library_path) / "meeting_archives"

        

        # Check if rotation needed on startup

        self._check_and_rotate()

    

    def _check_and_rotate(self):

        """Archive log if it exceeds size limit"""

        if not self.log_path.exists():

            return

        

        try:

            file_size = self.log_path.stat().st_size

            if file_size > self.MAX_LOG_SIZE_BYTES:

                self._rotate_log()

        except Exception as e:

            print(f"⚠️  Log rotation check failed: {e}")

    

    def _rotate_log(self):

        """Move current log to archive with timestamp"""

        try:

            # Create archive directory if needed

            self.archive_dir.mkdir(exist_ok=True)

            

            # Generate archive filename with timestamp

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            archive_name = f"MEETING_LOG_{timestamp}.md"

            archive_path = self.archive_dir / archive_name

            

            # Move current log to archive

            import shutil

            shutil.move(str(self.log_path), str(archive_path))

            

            print(f"📁 Log rotated to: {archive_path.name}")

            print(f"   Old log archived ({archive_path.stat().st_size // 1024}KB)")

            

        except Exception as e:

            print(f"⚠️  Log rotation failed: {e}")

    

    def archive_now(self):

        """Force archive the current log (callable externally)"""

        if self.log_path.exists() and self.log_path.stat().st_size > 0:

            self._rotate_log()

            print("✅ Log archived successfully")

        else:

            print("ℹ️  No log to archive")

    

    def initialize_log(self, topic: str, paper_count: int):

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        header = f"""

{'='*70}

R.A.I.N. LAB RESEARCH MEETING

{'='*70}

TOPIC: {topic}

DATE: {timestamp}

PAPERS LOADED: {paper_count}

MODEL: CUSTOM

MODE: GENIUS

{'='*70}

"""

        self._append_to_log(header)

    

    def log_statement(self, agent_name: str, content: str, metadata: Optional[Dict] = None):

        """Log with optional citation metadata"""

        entry = f"**{agent_name}:** {content}\n"

        

        if metadata and metadata.get('verified'):

            citations = metadata['verified']

            entry += f"   └─ Citations: {len(citations)} verified\n"

            for quote, source in citations[:2]:  # Show first 2

                entry += f"      • \"{quote[:50]}...\" [from {source}]\n"

        

        entry += "\n"

        self._append_to_log(entry)

    

    def finalize_log(self, stats: str):

        footer = f"""

{'='*70}

SESSION ENDED

{stats}

{'='*70}

"""

        self._append_to_log(footer)

    

    def _append_to_log(self, text: str):

        try:

            with open(self.log_path, 'a', encoding='utf-8') as f:

                f.write(text)

        except Exception as e:

            print(f"⚠️  Logging error: {e}")

class VisualEventLogger:

    """Writes theme-agnostic conversation events for a Godot client bridge."""

    def __init__(self, config: Config):

        self.enabled = bool(config.emit_visual_events)
        self.path = self._resolve_path(config.library_path, config.visual_events_log)

        if self.enabled:

            try:

                self.path.parent.mkdir(parents=True, exist_ok=True)

            except Exception as e:

                print(f"âš ï¸  Visual event logger unavailable: {e}")

                self.enabled = False

    @staticmethod
    def _resolve_path(library_path: str, configured_path: str) -> Path:

        raw = Path(configured_path).expanduser()
        if raw.is_absolute():
            return raw
        return Path(library_path) / raw

    def emit(self, payload: Dict):

        if not self.enabled:
            return

        event = dict(payload)
        event.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")

        try:

            with open(self.path, "a", encoding="utf-8") as f:

                f.write(json.dumps(event, ensure_ascii=False) + "\n")

        except Exception as e:

            print(f"âš ï¸  Visual event write failed: {e}")

class Diplomat:

    """Simple file-based mailbox for external messages."""

    def __init__(self, base_path: str = ".", inbox: str = "inbox", outbox: str = "outbox", processed: str = "processed"):

        self.inbox = os.path.join(base_path, inbox)

        self.outbox = os.path.join(base_path, outbox)

        self.processed = os.path.join(base_path, processed)

        os.makedirs(self.inbox, exist_ok=True)

        os.makedirs(self.outbox, exist_ok=True)

        os.makedirs(self.processed, exist_ok=True)

    def check_inbox(self) -> Optional[str]:

        """Read first inbox message, archive it, and return formatted text."""

        message_files = sorted(glob.glob(os.path.join(self.inbox, "*.txt")), key=os.path.getmtime)

        if not message_files:

            return None

        message_file = message_files[0]

        try:

            with open(message_file, "r", encoding="utf-8") as f:

                content = f.read().strip()

            content = sanitize_text(content)

        except Exception as e:

            print(f"⚠️  Failed to read diplomat message '{message_file}': {e}")

            return None

        archived_path = os.path.join(self.processed, os.path.basename(message_file))

        try:

            shutil.move(message_file, archived_path)

        except Exception as e:

            print(f"⚠️  Failed to archive diplomat message '{message_file}': {e}")

            return None

        return f"📨 EXTERNAL MESSAGE: {content}"

# --- MAIN ORCHESTRATOR ---
