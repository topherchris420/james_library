"""
R.A.I.N. Lab — Recursive Architecture Intelligence Nexus

Modular Python package for the research meeting orchestration layer.
"""

from .agents import Agent, RainLabAgentFactory
from .citations import CitationAnalyzer
from .cli import main, parse_args
from .config import (
    Config,
    DEFAULT_LIBRARY_EXCLUDE_DIRS,
    DEFAULT_LIBRARY_PATH,
    DEFAULT_MODEL_NAME,
    DEFAULT_RECURSIVE_LIBRARY_SCAN,
    PRIMARY_RESPONSE_SENTENCE_TARGET,
    PRIMARY_RESPONSE_WORD_TARGET,
    REPAIR_RESPONSE_SENTENCE_TARGET,
    SELF_NAME_INTRO_GUIDANCE,
    WRAP_UP_RESPONSE_SENTENCE_TARGET,
    WRAP_UP_RESPONSE_WORD_TARGET,
    meeting_response_length_guidance,
    no_self_name_intro_guidance,
    wrap_up_response_length_guidance,
)
from .context import ContextManager
from .diplomat import Diplomat
from .director import RainLabDirector
from .log_manager import LogManager
from .orchestrator import RainLabOrchestrator
from .resonance import ResonanceDetector
from .rust_daemon import RustDaemonClient
from .sanitize import (
    RE_CORRUPTION_CAPS,
    RE_CORRUPTION_PATTERNS,
    RE_FREQUENCY,
    RE_QUOTE_DOUBLE,
    RE_QUOTE_SINGLE,
    RE_RESONANCE_KEYWORDS,
    RE_WEB_SEARCH_COMMAND,
    sanitize_text,
)
from .visual_events import VisualEventServer
from .voice import VoiceEngine, edge_tts, pyttsx3
from .web_search import DDG_AVAILABLE, DDG_PACKAGE, WebSearchManager

__all__ = [
    # Config
    "Config",
    "DEFAULT_LIBRARY_PATH",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_RECURSIVE_LIBRARY_SCAN",
    "DEFAULT_LIBRARY_EXCLUDE_DIRS",
    "PRIMARY_RESPONSE_WORD_TARGET",
    "PRIMARY_RESPONSE_SENTENCE_TARGET",
    "REPAIR_RESPONSE_SENTENCE_TARGET",
    "WRAP_UP_RESPONSE_WORD_TARGET",
    "WRAP_UP_RESPONSE_SENTENCE_TARGET",
    "SELF_NAME_INTRO_GUIDANCE",
    "meeting_response_length_guidance",
    "no_self_name_intro_guidance",
    "wrap_up_response_length_guidance",
    # Agents
    "Agent",
    "RainLabAgentFactory",
    # Managers
    "ContextManager",
    "CitationAnalyzer",
    "WebSearchManager",
    "LogManager",
    "RainLabDirector",
    "Diplomat",
    "RustDaemonClient",
    "VisualEventServer",
    "VoiceEngine",
    "ResonanceDetector",
    # Orchestrator
    "RainLabOrchestrator",
    # CLI
    "main",
    "parse_args",
    # Sanitization
    "sanitize_text",
    "RE_QUOTE_DOUBLE",
    "RE_QUOTE_SINGLE",
    "RE_CORRUPTION_CAPS",
    "RE_WEB_SEARCH_COMMAND",
    "RE_CORRUPTION_PATTERNS",
    "RE_FREQUENCY",
    "RE_RESONANCE_KEYWORDS",
    # DDG
    "DDG_AVAILABLE",
    "DDG_PACKAGE",
    # TTS backends (exposed for test patching)
    "pyttsx3",
    "edge_tts",
]
