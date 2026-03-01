"""Centralized configuration for R.A.I.N. Lab meetings."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


def _parse_env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Parse comma-separated env values while preserving a deterministic tuple."""
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    parsed = tuple(part.strip() for part in raw.split(",") if part.strip())
    return parsed or default

DEFAULT_LIBRARY_PATH = str(Path(__file__).resolve().parent.parent)

DEFAULT_MODEL_NAME = os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct")

DEFAULT_RECURSIVE_LIBRARY_SCAN = os.environ.get("RAIN_RECURSIVE_LIBRARY_SCAN", "0") == "1"

DEFAULT_LIBRARY_EXCLUDE_DIRS = _parse_env_csv(
    "RAIN_LIBRARY_EXCLUDE_DIRS",
    (
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        "meeting_archives",
        "openclaw-main",
        "vers3dynamics_lab",
        "rlm-main",
    ),
)

@dataclass
class Config:
    """Centralized configuration - Optimized for Rnj-1 8B"""

    # LLM Settings
    temperature: float = 0.7
    base_url: str = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    api_key: str = os.environ.get("LM_STUDIO_API_KEY", "lm-studio")
    model_name: str = DEFAULT_MODEL_NAME
    max_tokens: int = 200
    timeout: float = float(os.environ.get("RAIN_LM_TIMEOUT", "300"))
    max_retries: int = 2
    recursive_intellect: bool = os.environ.get("RAIN_RECURSIVE_INTELLECT", "1") != "0"
    recursive_depth: int = int(os.environ.get("RAIN_RECURSIVE_DEPTH", "1"))

    # File Settings
    library_path: str = DEFAULT_LIBRARY_PATH
    meeting_log: str = "RAIN_LAB_MEETING_LOG.md"

    # Conversation Settings
    max_turns: int = 25
    wrap_up_turns: int = 15
    recent_history_window: int = 2

    # Context Settings
    context_snippet_length: int = 3000
    total_context_length: int = 20000
    recursive_library_scan: bool = DEFAULT_RECURSIVE_LIBRARY_SCAN
    max_library_files: int = 400
    library_exclude_dirs: Tuple[str, ...] = DEFAULT_LIBRARY_EXCLUDE_DIRS

    # Citation Tracking
    enable_citation_tracking: bool = True
    require_quotes: bool = True

    # Web Search Settings
    enable_web_search: bool = True
    web_search_results: int = 3

    # Output Settings
    verbose: bool = False

    # Presentation/Event Layer Settings
    emit_visual_events: bool = os.environ.get("RAIN_VISUAL_EVENTS", "0") == "1"
    visual_events_log: str = os.environ.get("RAIN_VISUAL_EVENTS_LOG", "meeting_archives/godot_events.jsonl")
    export_tts_audio: bool = os.environ.get("RAIN_EXPORT_TTS_AUDIO", "1") != "0"
    tts_audio_dir: str = os.environ.get("RAIN_TTS_AUDIO_DIR", "meeting_archives/tts_audio")
