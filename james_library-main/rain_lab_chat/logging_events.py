"""Meeting transcription, visual event logging, and external mailbox."""

import glob
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from rain_lab_chat._logging import get_logger
from rain_lab_chat._sanitize import sanitize_text
from rain_lab_chat.config import Config

log = get_logger(__name__)


def _resolve_configured_path(library_path: str, configured_path: str) -> Path:
    raw = Path(configured_path).expanduser()
    if raw.is_absolute():
        return raw
    return Path(library_path) / raw


class LogManager:
    """Handles meeting transcription with metadata and log rotation"""

    # Maximum log size before auto-rotation (150KB)

    MAX_LOG_SIZE_BYTES = 150_000

    def __init__(self, config: Config):

        self.config = config

        self.log_path = _resolve_configured_path(config.library_path, config.meeting_log)

        self.archive_dir = _resolve_configured_path(config.library_path, "meeting_archives")

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
            log.warning("Log rotation check failed: %s", e)

    def _rotate_log(self):
        """Move current log to archive with timestamp"""

        try:
            # Create archive directory if needed

            self.archive_dir.mkdir(exist_ok=True)

            # Generate archive filename with timestamp

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            archive_name = f"MEETING_LOG_{timestamp}.md"

            archive_path = self.archive_dir / archive_name

            # Move current log to archive

            shutil.move(str(self.log_path), str(archive_path))

            log.info("Log rotated to: %s (%dKB)", archive_path.name, archive_path.stat().st_size // 1024)

        except Exception as e:
            log.warning("Log rotation failed: %s", e)

    def archive_now(self):
        """Force archive the current log (callable externally)"""

        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            self._rotate_log()

            log.info("Log archived successfully")

        else:
            log.info("No log to archive")

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
        """Log with optional citation metadata"""

        entry = f"**{agent_name}:** {content}\n"

        if metadata and metadata.get("verified"):
            citations = metadata["verified"]

            entry += f"   └─ Citations: {len(citations)} verified\n"

            for quote, source in citations[:2]:  # Show first 2
                entry += f'      • "{quote[:50]}..." [from {source}]\n'

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
            log.warning("Logging error: %s", e)


class CheckpointManager:
    def __init__(self, config: Config):

        self.config = config

        self.path = _resolve_configured_path(config.library_path, config.checkpoint_path)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)

        except Exception as e:
            log.warning("Checkpoint directory unavailable: %s", e)

    def save(self, payload: Dict):

        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")

        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            tmp_path.replace(self.path)

        except Exception as e:
            log.warning("Checkpoint write failed: %s", e)


class SessionRunLedger:
    def __init__(self, config: Config):

        self.config = config

        self.path = _resolve_configured_path(config.library_path, config.session_runs_path)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)

        except Exception as e:
            log.warning("Session run ledger directory unavailable: %s", e)

    def append(self, payload: Dict):

        record = dict(payload)
        record.setdefault("recorded_at", datetime.utcnow().isoformat() + "Z")

        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        except Exception as e:
            log.warning("Session run ledger write failed: %s", e)


def _parse_checkpoint_for_resume(path: Path) -> dict:

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))

    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    history = payload.get("history")
    if not isinstance(history, list):
        return {}

    topic = str(payload.get("topic", "")).strip()
    normalized_history = [str(item).strip() for item in history if str(item).strip()]
    turn_count = payload.get("turn_count", len(normalized_history))

    try:
        turn_count = int(turn_count)

    except (TypeError, ValueError):
        turn_count = len(normalized_history)

    citation_counts = payload.get("citation_counts")
    if not isinstance(citation_counts, dict):
        citation_counts = {}

    metrics_state = payload.get("metrics_state")
    if not isinstance(metrics_state, dict):
        metrics_state = None

    if not topic:
        return {}

    return {
        "topic": topic,
        "history": normalized_history,
        "turn_count": max(0, turn_count),
        "citation_counts": citation_counts,
        "metrics_state": metrics_state,
        "status": str(payload.get("status", "running")),
        "source": "checkpoint",
    }


def parse_log_for_resume(log_path: str) -> dict:
    """Parse an existing meeting log to extract topic and conversation history.

    Returns a dict with keys 'topic', 'history' (list of "Speaker: text" strings),
    and 'turn_count' (int).  Returns empty dict on failure.
    """
    import re

    path = Path(log_path)
    if not path.exists():
        return {}

    checkpoint_data = _parse_checkpoint_for_resume(path)
    if checkpoint_data:
        return checkpoint_data

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    # Extract topic
    topic_match = re.search(r"TOPIC:\s*(.+)", text)
    topic = topic_match.group(1).strip() if topic_match else ""

    # Extract statements:  **AgentName:** content
    history: list[str] = []
    for m in re.finditer(r"\*\*(\w+):\*\*\s*(.+?)(?=\n\n|\n\*\*|\n={5,}|\Z)", text, re.DOTALL):
        speaker = m.group(1).strip()
        content = m.group(2).strip()
        # Skip system / session-end markers
        if speaker.upper() in ("SESSION", "SYSTEM"):
            continue
        history.append(f"{speaker}: {content}")

    return {
        "topic": topic,
        "history": history,
        "turn_count": len(history),
        "citation_counts": {},
        "metrics_state": None,
        "status": "parsed_log",
        "source": "log",
    }


class VisualEventLogger:
    """Writes theme-agnostic conversation events for a Godot client bridge."""

    def __init__(self, config: Config):

        self.enabled = bool(config.emit_visual_events)
        self.path = _resolve_configured_path(config.library_path, config.visual_events_log)

        if self.enabled:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)

            except Exception as e:
                log.warning("Visual event logger unavailable: %s", e)

                self.enabled = False

    def emit(self, payload: Dict):

        if not self.enabled:
            return

        event = dict(payload)
        event.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")

        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

        except Exception as e:
            log.warning("Visual event write failed: %s", e)


class Diplomat:
    """Simple file-based mailbox for external messages."""

    def __init__(
        self, base_path: str = ".", inbox: str = "inbox", outbox: str = "outbox", processed: str = "processed"
    ):

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
            log.warning("Failed to read diplomat message '%s': %s", message_file, e)

            return None

        archived_path = os.path.join(self.processed, os.path.basename(message_file))

        try:
            shutil.move(message_file, archived_path)

        except Exception as e:
            log.warning("Failed to archive diplomat message '%s': %s", message_file, e)

            return None

        return f"📨 EXTERNAL MESSAGE: {content}"


# --- MAIN ORCHESTRATOR ---
