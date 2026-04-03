"""

R.A.I.N. LAB - RESEARCH







"""

import warnings
import asyncio

import logging

import glob

import json

import os

import random

import shutil

import sys

import threading

import time


import tempfile

import uuid

from pathlib import Path

import re

import select

import bisect


# --- PRE-COMPILED REGEX PATTERNS ---

RE_QUOTE_DOUBLE = re.compile(r'"([^"]+)"')

RE_QUOTE_SINGLE = re.compile(r"'([^']+)'")

RE_CORRUPTION_CAPS = re.compile(r"[A-Z]{8,}")

RE_WEB_SEARCH_COMMAND = re.compile(r"\[SEARCH:\s*(.*?)\]", re.IGNORECASE)

RE_CORRUPTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\|eoc_fim\|",  # End of context markers
        r"ARILEX|AIVERI|RIECK",  # Common corruption sequences
        r"ingly:\w*scape",  # Gibberish compound words
        r":\s*\n\s*:\s*\n",  # Empty lines with colons
        r"##\d+\s*\(",  # Markdown header gibberish
        r"SING\w{10,}",  # Long corrupt strings starting with SING
        r"[A-Z]{4,}:[A-Z]{4,}",  # Multiple caps words with colons
    ]
]

# --- RESONANCE / FREQUENCY DETECTION ---

RE_FREQUENCY = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:hz|hertz)",
    re.IGNORECASE,
)

RE_RESONANCE_KEYWORDS = re.compile(
    r"\b(?:resonan(?:ce|t)|cymati(?:c|cs)|chladni|nodal|standing\s+wave|harmonic|"
    r"vibrat(?:e|ion|ional)|frequenc(?:y|ies)|acoustic|waveform|oscillat(?:e|ion)|"
    r"eigenfrequen(?:cy|cies)|anti[-\s]?node|amplitude)\b",
    re.IGNORECASE,
)


class ResonanceDetector:
    """Scan agent utterances for frequency/resonance discussion.

    Maintains a small rolling window of recently mentioned frequencies so
    that ``consensus_stability`` can rise when multiple agents converge on
    similar values and fall when discussion diverges.
    """

    _WINDOW_SIZE = 8

    def __init__(self) -> None:
        self._recent_frequencies: list[float] = []
        self._last_emitted_freq: float = 0.0
        self._last_stability: float = 0.0

    def analyze(self, text: str) -> "dict[str, float] | None":
        """Return a resonance_state payload dict, or *None* if nothing detected."""

        keyword_hits = len(RE_RESONANCE_KEYWORDS.findall(text))
        freq_matches = RE_FREQUENCY.findall(text)

        if keyword_hits == 0 and not freq_matches:
            return None

        # Extract the dominant mentioned frequency (last one wins).
        if freq_matches:
            target_freq = float(freq_matches[-1])
        elif self._recent_frequencies:
            target_freq = self._recent_frequencies[-1]
        else:
            target_freq = 432.0  # sensible acoustic default

        # Track recent frequencies for stability calculation.
        self._recent_frequencies.append(target_freq)
        if len(self._recent_frequencies) > self._WINDOW_SIZE:
            self._recent_frequencies = self._recent_frequencies[-self._WINDOW_SIZE :]

        # Amplitude: more keyword hits → stronger visual effect (capped at 1).
        amplitude = min(1.0, 0.25 + keyword_hits * 0.15)

        # Consensus stability: how tightly recent frequencies cluster.
        stability = self._compute_stability()

        self._last_emitted_freq = target_freq
        self._last_stability = stability

        return {
            "target_frequency": round(target_freq, 2),
            "amplitude": round(amplitude, 3),
            "consensus_stability": round(stability, 3),
        }

    def _compute_stability(self) -> float:
        n = len(self._recent_frequencies)
        if n < 2:
            return 0.5
        mean = sum(self._recent_frequencies) / n
        if mean == 0.0:
            return 1.0
        variance = sum((f - mean) ** 2 for f in self._recent_frequencies) / n
        cv = (variance**0.5) / mean  # coefficient of variation
        # Map CV → stability: cv=0 → 1.0, cv≥0.5 → 0.0
        return max(0.0, min(1.0, 1.0 - cv * 2.0))


def sanitize_text(text: str) -> str:
    """Sanitize external content to prevent prompt injection and control token attacks"""

    if not text:
        return ""

    # 1. Remove LLM control tokens and known corruption markers

    for token in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "|eoc_fim|"]:
        text = text.replace(token, "[TOKEN_REMOVED]")

    # 2. Neutralize '###' headers that could simulate system/user turns

    text = text.replace("###", ">>>")

    # 3. Prevent recursive search triggers

    text = text.replace("[SEARCH:", "[SEARCH;")

    return text.strip()


def _parse_env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Parse comma-separated env values while preserving a deterministic tuple."""

    raw = os.environ.get(name, "")

    if not raw.strip():
        return default

    parsed = tuple(part.strip() for part in raw.split(",") if part.strip())

    return parsed or default


DEFAULT_LIBRARY_PATH = str(Path(__file__).resolve().parent)

DEFAULT_MODEL_NAME = os.environ.get(
    "RAIN_LLM_MODEL",
    os.environ.get("LM_STUDIO_MODEL", "minimax-m2.7:cloud"),
)

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

from typing import List, Dict, Optional, Tuple, Any

from dataclasses import dataclass, field

from datetime import datetime

import argparse

from graph_bridge import HypergraphManager

from stagnation_monitor import StagnationMonitor

from hypothesis_tree import HypothesisTree, NodeStatus

try:
    import msvcrt  # Windows keyboard input detection

except ImportError:
    msvcrt = None


# --- SILENCE WARNINGS ---

warnings.simplefilter("ignore")

os.environ["PYTHONWARNINGS"] = "ignore"

logging.getLogger().setLevel(logging.WARNING)


# --- EVAL METRICS ---

try:
    from rain_metrics import MetricsTracker

except ImportError:
    MetricsTracker = None  # metrics collection is optional


# --- IMPORTS ---

openai = None

if "--help" not in sys.argv and "-h" not in sys.argv:
    try:
        import openai

    except ImportError:
        print("❌ Error: openai package not installed. Run: pip install openai")

        sys.exit(1)


# Optional: DuckDuckGo search support

DDG_AVAILABLE = False

DDG_PACKAGE = None

try:
    # Try the new package name first

    from ddgs import DDGS

    DDG_AVAILABLE = True

    DDG_PACKAGE = "ddgs"

except ImportError:
    try:
        # Fall back to deprecated package name (suppress rename warning)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*renamed.*")

            from duckduckgo_search import DDGS

        DDG_AVAILABLE = True

        DDG_PACKAGE = "duckduckgo_search"

    except ImportError:
        pass  # Web search will be disabled


# Optional: Text-to-speech support

try:
    import pyttsx3 as _pyttsx3

except Exception:
    _pyttsx3 = None


pyttsx3 = _pyttsx3

try:
    import edge_tts as _edge_tts

except Exception:
    _edge_tts = None


edge_tts = _edge_tts


def _safe_console_print(message: str) -> None:
    """Print a warning without crashing on non-UTF-8 Windows consoles."""

    try:
        print(message)
    except UnicodeEncodeError:
        fallback = message.encode("ascii", errors="ignore").decode("ascii").lstrip()
        print(fallback or "Console output contained unsupported characters.")


class VoiceEngine:
    """Voice wrapper with pyttsx3 first, edge-tts fallback, then silent mode."""

    EDGE_VOICE_BY_CHARACTER = {
        "James": "en-US-GuyNeural",
        "Luca": "en-US-GuyNeural",
        "Jasmine": "en-US-AriaNeural",
        "Elena": "en-US-AriaNeural",
    }

    def __init__(self):

        self.enabled = False

        self.export_enabled = False

        self.backend = "silent"

        self.engine = None

        self.voice_id_by_character: Dict[str, str] = {}

        self.default_voice_id: Optional[str] = None

        if pyttsx3 is not None:
            try:
                self.engine = pyttsx3.init()

                self._initialize_character_voices()

                self.enabled = True

                self.export_enabled = True

                self.backend = "pyttsx3"

                return

            except Exception as e:
                print = _safe_console_print
                print(f"⚠️  Voice engine unavailable: {e}")

                self.engine = None

                self.enabled = False

        if edge_tts is not None:
            self.enabled = True
            self.export_enabled = True
            self.backend = "edge-tts"

    def _initialize_character_voices(self):
        """Load Windows character voices and map them to known agents."""

        if not self.engine:
            return

        try:
            available_voices = self.engine.getProperty("voices") or []

        except Exception:
            available_voices = []

        male_voice_id = None

        female_voice_id = None

        for voice in available_voices:
            voice_name = (getattr(voice, "name", "") or "").lower()

            if "david" in voice_name and male_voice_id is None:
                male_voice_id = voice.id

            if "zira" in voice_name and female_voice_id is None:
                female_voice_id = voice.id

        current_voice_id = self.engine.getProperty("voice")

        self.default_voice_id = male_voice_id or female_voice_id or current_voice_id

        self.voice_id_by_character = {
            "James": male_voice_id or self.default_voice_id,
            "Luca": male_voice_id or self.default_voice_id,
            "Jasmine": female_voice_id or self.default_voice_id,
            "Elena": female_voice_id or self.default_voice_id,
        }

    def _voice_for_agent(self, agent_name: str) -> Optional[str]:
        """Return mapped voice id for known characters."""

        return self.voice_id_by_character.get(agent_name, self.default_voice_id)

    def _edge_voice_for_agent(self, agent_name: Optional[str]) -> str:
        return self.EDGE_VOICE_BY_CHARACTER.get(agent_name or "", "en-US-AriaNeural")

    async def _save_edge_tts_audio(self, text: str, agent_name: Optional[str], output_path: Path) -> Path:
        communicate = edge_tts.Communicate(text, self._edge_voice_for_agent(agent_name))
        await communicate.save(str(output_path))
        return output_path

    def _export_edge_tts_audio(self, text: str, agent_name: Optional[str], output_path: Path) -> Optional[Path]:
        if edge_tts is None:
            return None

        target_path = output_path.with_suffix(".mp3")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            return asyncio.run(self._save_edge_tts_audio(text, agent_name, target_path))
        except Exception as e:
            self.enabled = False
            self.export_enabled = False
            _safe_console_print(f"Voice export failed: {e}")
            return None

    def _play_audio_file(self, audio_path: Path) -> None:
        if os.name != "nt":
            return

        # Use os.startfile — the most reliable Windows-native way to play audio.
        # PowerShell/WMP approach breaks with Unicode paths and complex URIs.
        try:
            resolved = audio_path.resolve()
            os.startfile(str(resolved))
        except Exception as e:
            self.enabled = False
            _safe_console_print(f"Voice playback failed: {e}")

    def speak(self, text: str, agent_name: Optional[str] = None):
        """Speak text synchronously; no-op if voice is unavailable."""

        if not text:
            return

        if self.backend == "edge-tts":
            audio_path = self._export_edge_tts_audio(
                text,
                agent_name,
                Path(tempfile.gettempdir()) / f"rain_lab_tts_{uuid.uuid4().hex}.mp3",
            )
            if audio_path is not None:
                self._play_audio_file(audio_path)
            return

        if not self.enabled or not self.engine:
            return

        try:
            target_voice = self._voice_for_agent(agent_name or "")

            if target_voice:
                self.engine.setProperty("voice", target_voice)

            self.engine.say(text)

            # Blocks until the queue is empty so audio matches text output order

            self.engine.runAndWait()

        except Exception as e:
            print = _safe_console_print
            print(f"⚠️  Voice playback failed: {e}")

            self.enabled = False

    @staticmethod
    def estimate_duration_ms(text: str) -> int:
        """Estimate speech duration for subtitle timing when no media metadata exists."""

        words = max(1, len(text.split()))
        words_per_minute = 165
        duration_ms = int((words / words_per_minute) * 60_000)
        return max(900, duration_ms)

    def export_to_file(self, text: str, agent_name: Optional[str], output_path: Path) -> Optional[Path]:
        """Synthesize speech to a local audio file for external visual clients."""

        if not self.export_enabled:
            return None
        if not text:
            return None

        if self.backend == "edge-tts":
            return self._export_edge_tts_audio(text, agent_name, output_path)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            export_engine = pyttsx3.init()

            target_voice = self._voice_for_agent(agent_name or "")
            if target_voice:
                export_engine.setProperty("voice", target_voice)

            export_engine.save_to_file(text, str(output_path))
            export_engine.runAndWait()
            export_engine.stop()

            if output_path.exists() and output_path.stat().st_size > 0:
                return output_path
            return None

        except Exception as e:
            self.export_enabled = False
            print = _safe_console_print
            print(f"⚠️  Voice export failed: {e}")

            return None


# --- CONFIGURATION (RTX 4090 + RNJ-1 8B OPTIMIZED) ---


@dataclass
class Config:
    """Centralized configuration - Optimized for Rnj-1 8B"""

    # LLM Settings (Rnj-1 8B is ~50% faster than 12B models)

    temperature: float = 0.7  # Higher temp for more variety in responses

    base_url: str = os.environ.get(
        "RAIN_LLM_BASE_URL",
        os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:11434/v1"),
    )

    api_key: str = os.environ.get(
        "RAIN_LLM_API_KEY",
        os.environ.get("LM_STUDIO_API_KEY", "ollama"),
    )

    model_name: str = DEFAULT_MODEL_NAME

    max_tokens: int = field(
        default_factory=lambda: int(os.environ.get("RAIN_CHAT_MAX_TOKENS", "320"))
    )  # Keep Config aligned with the CLI/env default contract

    timeout: float = float(os.environ.get("RAIN_LM_TIMEOUT", "300"))

    max_retries: int = 2

    recursive_intellect: bool = os.environ.get("RAIN_RECURSIVE_INTELLECT", "1") != "0"

    recursive_depth: int = int(os.environ.get("RAIN_RECURSIVE_DEPTH", "1"))

    # File Settings

    library_path: str = DEFAULT_LIBRARY_PATH

    meeting_log: str = "RAIN_LAB_MEETING_LOG.md"

    # Conversation Settings

    max_turns: int = 25

    wrap_up_turns: int = 15  # Number of turns reserved for meeting wrap-up (starts after 10 discussion turns)

    recent_history_window: int = 2  # Reduced for speed - less context per call

    # Context Settings - EXPANDED FOR DEEPER PAPER ANALYSIS

    context_snippet_length: int = 3000  # ~750 tokens per paper - more in-depth content

    total_context_length: int = 20000  # ~5k tokens for papers - allows full digestion

    recursive_library_scan: bool = DEFAULT_RECURSIVE_LIBRARY_SCAN  # Default: top-level only

    max_library_files: int = 400  # Hard cap to prevent runaway scans

    library_exclude_dirs: Tuple[str, ...] = DEFAULT_LIBRARY_EXCLUDE_DIRS

    # Citation Tracking

    enable_citation_tracking: bool = True

    require_quotes: bool = True

    # Web Search Settings

    enable_web_search: bool = True  # Enable DuckDuckGo search for online context

    web_search_results: int = 3  # Number of search results per query

    # Output Settings

    verbose: bool = False  # Set to True to show detailed loading output

    # Presentation/Event Layer Settings

    emit_visual_events: bool = os.environ.get("RAIN_VISUAL_EVENTS", "0") == "1"

    visual_events_host: str = os.environ.get("RAIN_VISUAL_EVENTS_HOST", "127.0.0.1")

    visual_events_port: int = int(os.environ.get("RAIN_VISUAL_EVENTS_PORT", "8765"))

    log_visual_events: bool = os.environ.get("RAIN_LOG_VISUAL_EVENTS", "0") == "1"

    visual_events_log: str = os.environ.get("RAIN_VISUAL_EVENTS_LOG", "meeting_archives/godot_events.jsonl")

    export_tts_audio: bool = os.environ.get("RAIN_EXPORT_TTS_AUDIO", "1") != "0"

    tts_audio_dir: str = os.environ.get("RAIN_TTS_AUDIO_DIR", "meeting_archives/tts_audio")

    # Rust daemon bridge settings (PR B)
    use_rust_daemon: bool = os.environ.get("RAIN_USE_RUST_DAEMON", "0") == "1"
    rust_daemon_api_url: str = os.environ.get("RAIN_RUST_DAEMON_API_URL", "http://127.0.0.1:4200")
    rust_daemon_timeout: float = float(os.environ.get("RAIN_RUST_DAEMON_TIMEOUT", "120"))


PRIMARY_RESPONSE_WORD_TARGET = "90-140 words"
PRIMARY_RESPONSE_SENTENCE_TARGET = "3-5 complete sentences"
REPAIR_RESPONSE_SENTENCE_TARGET = "3 or 4 complete sentences"
WRAP_UP_RESPONSE_WORD_TARGET = "60-100 words"
WRAP_UP_RESPONSE_SENTENCE_TARGET = "2-3 complete sentences"
SELF_NAME_INTRO_GUIDANCE = (
    'Do not start with your own name, a speaker label, or a self-intro like "James:", "James here," or "I\'m James."'
)


def meeting_response_length_guidance() -> str:
    return (
        f"Aim for {PRIMARY_RESPONSE_WORD_TARGET} across {PRIMARY_RESPONSE_SENTENCE_TARGET} "
        "so each turn lands as a complete thought."
    )


def no_self_name_intro_guidance() -> str:
    return SELF_NAME_INTRO_GUIDANCE


def wrap_up_response_length_guidance() -> str:
    return (
        f"Aim for {WRAP_UP_RESPONSE_WORD_TARGET} across {WRAP_UP_RESPONSE_SENTENCE_TARGET} "
        "so the closing summary still sounds complete."
    )


# --- RESEARCH AGENT DEFINITIONS ---


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
                with open(soul_path, "r", encoding="utf-8") as f:
                    external_soul = f.read()

                # Append critical meeting rules to external soul

                meeting_rules = f"""



# MEETING RULES (CRITICAL)

- You are ONLY {self.name}. Never speak as another team member.

- Never write dialogue for others (no "James:" or "Jasmine would say...")

- Never echo or repeat what colleagues just said - use your OWN words

- {no_self_name_intro_guidance()}

- {meeting_response_length_guidance()}

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

- {no_self_name_intro_guidance()}

- Bring YOUR unique perspective based on your role and focus



# CITATION RULES

1. The "RESEARCH DATABASE" below is your ONLY factual source

2. Use "exact quotation marks" when citing specific data

3. Cite sources: [from filename.md]

4. If info isn't in papers, say: "The papers don't cover this"

5. For inferences beyond text, prefix with [REDACTED]



# CONVERSATION STYLE

- {meeting_response_length_guidance()}

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
                personality=(
                    "Brilliant pattern-seeker with strong opinions. Will defend his geometric"
                    " intuitions passionately but can be swayed by solid evidence."
                    " Sometimes dismissive of overly cautious approaches."
                ),
                focus=(
                    "Analyze the papers for 'Resonance', 'Geometric Structures',"
                    " and 'Frequency' data. Connect disparate findings."
                ),
                color="\033[92m",  # Green
                agreeableness=0.5,
                opinion_strength="strong",
            ),
            Agent(
                name="Jasmine",
                role="Hardware Architect",
                personality=(
                    "Highly skeptical devil's advocate. Loves shooting down impractical ideas."
                    " Will argue that something can't be built unless proven otherwise."
                    " Finds theoretical discussions frustrating without concrete specs."
                ),
                focus=(
                    "Check the papers for 'Feasibility', 'Energy Requirements',"
                    " and 'Material Constraints'. Ask: Can we actually build this?"
                ),
                color="\033[93m",  # Yellow
                agreeableness=0.2,
                opinion_strength="strong",
            ),
            Agent(
                name="Luca",
                role="Field Tomographer / Theorist",
                personality=(
                    "Diplomatic peacemaker who tries to find common ground."
                    " Sees beauty in everyone's perspective. Rarely directly disagrees"
                    " but will gently suggest alternatives. Sometimes too accommodating."
                ),
                focus=(
                    "Analyze the 'Topology', 'Fields', and 'Gradients' described"
                    " in the papers. Describe the geometry of the theory."
                ),
                color="\033[96m",  # Cyan
                agreeableness=0.9,
                opinion_strength="weak",
            ),
            Agent(
                name="Elena",
                role="Quantum Information Theorist",
                personality=(
                    "Brutally honest math purist. Has zero patience for hand-waving"
                    " or vague claims. Will interrupt to demand mathematical rigor."
                    " Often clashes with James's intuitive approach."
                ),
                focus=(
                    "Analyze 'Information Bounds', 'Computational Limits',"
                    " and 'Entropy' in the research. Look for mathematical consistency."
                ),
                color="\033[95m",  # Magenta
                agreeableness=0.6,
                opinion_strength="strong",
            ),
        ]


# --- CONTEXT MANAGEMENT ---


class ContextManager:
    """Reads and manages research paper context - FULL PAPER MODE"""

    def __init__(self, config: Config):

        self.config = config

        self.lab_path = Path(config.library_path)

        self.loaded_papers: Dict[str, str] = {}

        self.global_context_index: str = ""

        self.context_offsets: List[Tuple[int, str]] = []

        self.offset_keys: List[int] = []

        self.paper_list: List[str] = []

    def _discover_files(self) -> List[Path]:
        """Discover candidate research files, optionally including nested directories."""

        skip_dirs = set(self.config.library_exclude_dirs)

        allowed_suffixes = (".md", ".txt", ".py")

        exclude_patterns = ["SOUL", "LOG", "MEETING"]

        candidates = []

        if self.config.recursive_library_scan:
            for root, dirs, files in os.walk(self.lab_path):
                # Prune skip_dirs in-place to prevent traversing them

                dirs[:] = [d for d in dirs if d not in skip_dirs]

                # Pre-calculate parent dir check for .py files

                # If root ends with "hello_os", then files in it are inside hello_os package

                parent_name = os.path.basename(root)

                is_hello_os_dir = parent_name == "hello_os"

                for file in files:
                    # 1. Fast suffix check (string op, no object creation)

                    name_lower = file.lower()

                    if not name_lower.endswith(allowed_suffixes):
                        continue

                    # 2. Check exclusions

                    name_upper = file.upper()

                    if any(p in name_upper for p in exclude_patterns):
                        continue

                    if file in skip_dirs:
                        continue

                    # 3. Apply specific filtering rules

                    # Rule: .md/.txt are always allowed. .py only if hello_os.py or inside hello_os dir.

                    is_md_txt = name_lower.endswith((".md", ".txt"))

                    is_valid_py = False

                    if name_lower.endswith(".py"):
                        if file == "hello_os.py":
                            is_valid_py = True

                        elif is_hello_os_dir:
                            is_valid_py = True

                    if is_md_txt or is_valid_py:
                        candidates.append(Path(root) / file)

        else:
            # Non-recursive scan (top-level only)

            for f in self.lab_path.iterdir():
                if not f.is_file():
                    continue

                name = f.name

                name_lower = name.lower()

                if not name_lower.endswith(allowed_suffixes):
                    continue

                if name in skip_dirs:
                    continue

                name_upper = name.upper()

                if any(p in name_upper for p in exclude_patterns):
                    continue

                is_md_txt = name_lower.endswith((".md", ".txt"))

                is_valid_py = False

                if name_lower.endswith(".py"):
                    if name == "hello_os.py":
                        is_valid_py = True

                    # Check if the library itself is the hello_os package folder

                    elif self.lab_path.name == "hello_os":
                        is_valid_py = True

                if is_md_txt or is_valid_py:
                    candidates.append(f)

        return sorted(candidates)[: self.config.max_library_files]

    def get_library_context(self, verbose: bool = False) -> Tuple[str, List[str]]:
        """Read COMPLETE papers from local library"""

        # Ensure repeated calls don't keep stale/duplicated state.

        self.loaded_papers = {}

        self.global_context_index = ""

        self.context_offsets = []

        self.offset_keys = []

        self.paper_list = []

        if verbose:
            print(f"\n📂 Accessing Research Library at: {self.lab_path}")

        if not self.lab_path.exists():
            print(f"❌ Library path does not exist: {self.lab_path}")

            return "Library not accessible.", []

        buffer = []

        # Load all valid text files (recursive by default)

        all_files = self._discover_files()

        if verbose:
            scope = "recursive" if self.config.recursive_library_scan else "top-level"

            print(f"   • Scan mode: {scope}; files discovered: {len(all_files)}")

        if not all_files:
            print("⚠️  No research papers found in library.")

            return "No research papers found in library.", []

        if verbose:
            print(f"   ✓ Found {len(all_files)} papers.\n")

        total_chars = 0

        current_offset = 0

        index_parts = []

        for filepath in all_files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                    # Store FULL content for citation verification

                    paper_ref = str(filepath.relative_to(self.lab_path))

                    self.loaded_papers[paper_ref] = content

                    self.paper_list.append(paper_ref)

                    # Build Global Index for fast O(1) searches

                    content_lower = content.lower()

                    self.context_offsets.append((current_offset, paper_ref))

                    index_parts.append(content_lower)

                    current_offset += len(content_lower) + 1  # +1 for delimiter

                    # Include full paper up to snippet length (25k = essentially full)

                    remaining_budget = self.config.total_context_length - total_chars

                    if remaining_budget > 1000:
                        # SANITIZE CONTENT before adding to prompt

                        safe_content = sanitize_text(content)

                        to_include = min(len(safe_content), self.config.context_snippet_length, remaining_budget)

                        buffer.append(f"--- PAPER: {paper_ref} ---\n{safe_content[:to_include]}\n")

                        total_chars += to_include

                        # Show what percentage of paper was loaded

                        if verbose:
                            coverage = (to_include / len(content)) * 100 if len(content) > 0 else 100

                            print(f"     ✓ Loaded: {paper_ref} ({to_include:,} chars, {coverage:.0f}% coverage)")

                    else:
                        if verbose:
                            print(f"     ⚠ Skipped {paper_ref} (budget exhausted)")

            except Exception as e:
                if verbose:
                    print(f"     ✗ Error reading {filepath.name}: {e}")

                continue

        # Finalize global index

        self.global_context_index = "\0".join(index_parts)

        self.offset_keys = [o[0] for o in self.context_offsets]

        combined = "\n".join(buffer)

        if verbose:
            print(f"\n   📊 Total context loaded: {len(combined):,} characters")

            print(f"   📊 Papers with full coverage: {len([p for p in self.loaded_papers.keys()])}")

        return combined, self.paper_list

    def verify_citation(self, quote: str, fuzzy: bool = True) -> Optional[str]:
        """Verify if a quote exists in loaded papers using global index"""

        quote_clean = quote.strip().lower()

        # Skip very short quotes

        if len(quote_clean.split()) < 3:
            return None

        windows_to_check = []

        if fuzzy:
            quote_words = quote_clean.split()

            if len(quote_words) > 3:
                # Check multiple word windows for better matching

                # Try first 5 words, then first 8, then middle section

                raw_windows = [
                    " ".join(quote_words[:5]),
                    " ".join(quote_words[:8]) if len(quote_words) >= 8 else None,
                    " ".join(quote_words[2:7]) if len(quote_words) >= 7 else None,
                ]

                # Filter out None values once

                windows_to_check = [w for w in raw_windows if w]

        else:
            windows_to_check = [quote_clean]

        # Use global index search

        best_offset = -1

        for window in windows_to_check:
            # Find earliest occurrence in global index

            idx = self.global_context_index.find(window)

            if idx != -1:
                # If we found a match, check if it's earlier than previous matches

                if best_offset == -1 or idx < best_offset:
                    best_offset = idx

        if best_offset != -1:
            # Map offset to paper using binary search

            # bisect_right returns insertion point to maintain order

            paper_idx = bisect.bisect_right(self.offset_keys, best_offset) - 1

            if 0 <= paper_idx < len(self.context_offsets):
                return self.context_offsets[paper_idx][1]

        return None


# --- WEB SEARCH MANAGER ---


class WebSearchManager:
    """Handles DuckDuckGo web searches for supplementary research context"""

    def __init__(self, config: Config):

        self.config = config

        self.search_cache: Dict[str, List[Dict]] = {}

        self.enabled = config.enable_web_search and DDG_AVAILABLE

        self.max_retries = 3

        self.retry_delay = 2.0  # seconds between retries

    def search(self, query: str, verbose: bool = False) -> Tuple[str, List[Dict]]:
        """Search DuckDuckGo and return formatted results plus raw data"""

        if not self.enabled:
            if self.config.enable_web_search and verbose:
                print(f"\n⚠️  Web search disabled: No DDG package installed")

                print("   Install with: pip install ddgs")

            return "", []

        # Check cache

        if query in self.search_cache:
            if verbose:
                print(f"\n🔄 Using cached web results for: '{query}'")

            return self._format_results(self.search_cache[query]), self.search_cache[query]

        if verbose:
            print(f"\n🌐 Searching web for: '{query}'...")

        # Retry loop with exponential backoff

        for attempt in range(self.max_retries):
            try:
                results = []

                # Suppress any deprecation warnings during search

                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")

                    with DDGS() as ddgs:
                        for r in ddgs.text(query, max_results=self.config.web_search_results):
                            results.append(
                                {"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                            )

                self.search_cache[query] = results

                if results:
                    if verbose:
                        print(f"   ✓ Found {len(results)} web results")

                        for i, r in enumerate(results, 1):
                            title_preview = r["title"][:60] + "..." if len(r["title"]) > 60 else r["title"]

                            print(f"      {i}. {title_preview}")

                    return self._format_results(results), results

                else:
                    # No results but no error - may be rate limited or bad query

                    if attempt < self.max_retries - 1:
                        delay = self.retry_delay * (attempt + 1)

                        if verbose:
                            print(
                                f"   ⚠ No results (attempt {attempt + 1}/{self.max_retries}),"
                                f" retrying in {delay:.1f}s..."
                            )

                        time.sleep(delay)

                    else:
                        if verbose:
                            print(f"   ⚠ No web results found after {self.max_retries} attempts")

                            print("   💡 Possible causes: rate limiting, network issues, or overly specific query")

                        return "", []

            except Exception as e:
                error_msg = str(e).lower()

                # Identify specific error types for better messaging

                if "ratelimit" in error_msg or "429" in error_msg:
                    reason = "Rate limited by DuckDuckGo"

                elif "timeout" in error_msg:
                    reason = "Request timed out"

                elif "connection" in error_msg or "network" in error_msg:
                    reason = "Network connection error"

                else:
                    reason = str(e)

                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (attempt + 1)

                    if verbose:
                        print(f"   ⚠ {reason} (attempt {attempt + 1}/{self.max_retries}), retrying in {delay:.1f}s...")

                    time.sleep(delay)

                else:
                    if verbose:
                        print(f"   ⚠ Web search failed after {self.max_retries} attempts: {reason}")

                        print("   💡 Meeting will proceed with local papers only")

                    return "", []

        return "", []

    def _sanitize_text(self, text: str) -> str:
        """Sanitize web content to prevent prompt injection and control token attacks"""

        return sanitize_text(text)

    def _format_results(self, results: List[Dict]) -> str:
        """Format results for agent context"""

        if not results:
            return ""

        formatted = ["\n### WEB SEARCH RESULTS (cite as [from web: title])"]

        for r in results:
            safe_title = self._sanitize_text(r.get("title", ""))

            safe_body = self._sanitize_text(r.get("body", ""))

            formatted.append(f"**{safe_title}**")

            formatted.append(f"{safe_body}")

            formatted.append(f"Source: {r.get('href', '')}\n")

        return "\n".join(formatted)


# --- CITATION ANALYZER ---


class CitationAnalyzer:
    """Tracks and verifies citations in agent responses"""

    def __init__(self, context_manager: ContextManager):

        self.context_manager = context_manager

        self.total_quotes_found = 0

        self.verified_quotes = 0

    def extract_quotes(self, text: str) -> List[str]:
        """Extract quoted text from response"""

        # Match text in "quotes" or 'quotes' using pre-compiled patterns

        quotes = RE_QUOTE_DOUBLE.findall(text)

        quotes.extend(RE_QUOTE_SINGLE.findall(text))

        return [q for q in quotes if len(q.split()) > 3]  # Only meaningful quotes

    def analyze_response(self, agent_name: str, response: str) -> Dict[str, any]:
        """Analyze citation quality of response"""

        quotes = self.extract_quotes(response)

        self.total_quotes_found += len(quotes)

        verified = []

        unverified = []

        for quote in quotes:
            source = self.context_manager.verify_citation(quote)

            if source:
                verified.append((quote, source))

                self.verified_quotes += 1

            else:
                unverified.append(quote)

        has_speculation = "[SPECULATION]" in response.upper() or "[THEORY]" in response.upper()

        return {
            "quotes_found": len(quotes),
            "verified": verified,
            "unverified": unverified,
            "has_speculation_tag": has_speculation,
            "citation_rate": len(verified) / len(quotes) if quotes else 0,
        }

    def get_stats(self) -> str:
        """Get overall citation statistics"""

        if self.total_quotes_found == 0:
            return "No quotes analyzed yet."

        rate = (self.verified_quotes / self.total_quotes_found) * 100

        return f"Citation Rate: {self.verified_quotes}/{self.total_quotes_found} ({rate:.1f}% verified)"


# --- DIRECTOR ---


class RainLabDirector:
    """Directs agents with dynamic, citation-focused instructions"""

    def __init__(self, config: Config, paper_list: List[str]):

        self.config = config

        self.paper_list = paper_list

    def get_dynamic_instruction(self, agent: Agent, turn_count: int, topic: str) -> str:
        """Generate instructions that force citation"""

        # Opening move

        if turn_count == 0 and agent.name == "James":
            return (
                f"Open the meeting. Survey the loaded research papers and identify"
                f" which ones discuss '{topic}'. Quote key definitions or findings."
            )

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
            ],
        }

        if agent.name in instructions:
            return random.choice(instructions[agent.name])

        return f"Analyze '{topic}' strictly from the research papers. Quote your sources."


# --- LOG MANAGER ---


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

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

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
            print(f"⚠️  Logging error: {e}")


class VisualEventServer:
    """Streams theme-agnostic conversation events to Godot clients over WebSocket.

    Runs a websockets server in a background daemon thread.  The public
    ``emit()`` method is safe to call from any thread — it enqueues the
    event and the background loop broadcasts it to every connected client.

    Optionally logs events to a JSONL file when *log_path* is set (enabled
    via ``--log-visual-events``).
    """

    def __init__(self, config: Config):
        self.enabled = bool(config.emit_visual_events)
        self._host: str = str(getattr(config, "visual_events_host", "127.0.0.1"))
        self._port: int = int(getattr(config, "visual_events_port", 8765))

        # Optional JSONL debug log
        self._log_path: Optional[Path] = None
        if getattr(config, "log_visual_events", False):
            self._log_path = self._resolve_path(config.library_path, config.visual_events_log)
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"\u26a0\ufe0f  Visual event log unavailable: {e}")
                self._log_path = None

        self._loop = None
        self._queue = None
        self._thread: Optional[threading.Thread] = None
        self._clients: set = set()

        if self.enabled:
            self._start_server()

    # -- path helper (kept for log-file resolution) --

    @staticmethod
    def _resolve_path(library_path: str, configured_path: str) -> Path:
        raw = Path(configured_path).expanduser()
        if raw.is_absolute():
            return raw
        return Path(library_path) / raw

    # -- public API --

    def emit(self, payload: Dict):
        if not self.enabled:
            return

        event = dict(payload)
        event.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")

        # Write to debug log if enabled
        if self._log_path is not None:
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"\u26a0\ufe0f  Visual event log write failed: {e}")

        # Push to WebSocket broadcast queue (thread-safe)
        if self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def shutdown(self):
        """Stop the background server gracefully."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3)

    # -- internals --

    def _start_server(self):
        try:
            import asyncio as _asyncio
            import websockets as _ws
        except ImportError:
            print("\u26a0\ufe0f  websockets package not installed \u2014 visual event server disabled")
            self.enabled = False
            return

        ready = threading.Event()

        def _run():
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            self._loop = loop
            self._queue = _asyncio.Queue()

            async def _handler(websocket):
                self._clients.add(websocket)
                try:
                    async for raw in websocket:
                        if isinstance(raw, str):
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(msg, dict) and msg.get("type") == "ping":
                                await websocket.send(json.dumps({"type": "pong"}))
                except Exception:
                    pass
                finally:
                    self._clients.discard(websocket)

            async def _broadcaster():
                while True:
                    event = await self._queue.get()
                    if not self._clients:
                        continue
                    data = json.dumps(event, ensure_ascii=False)
                    stale = []
                    for client in list(self._clients):
                        try:
                            await client.send(data)
                        except Exception:
                            stale.append(client)
                    for client in stale:
                        self._clients.discard(client)

            async def _serve():
                async with _ws.serve(_handler, self._host, self._port):
                    print(f"[visual-events] ws://{self._host}:{self._port}")
                    ready.set()
                    await _broadcaster()

            loop.run_until_complete(_serve())

        self._thread = threading.Thread(target=_run, daemon=True, name="visual-event-server")
        self._thread.start()
        ready.wait(timeout=5)


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
            print(f"⚠️  Failed to read diplomat message '{message_file}': {e}")

            return None

        archived_path = os.path.join(self.processed, os.path.basename(message_file))

        try:
            shutil.move(message_file, archived_path)

        except Exception as e:
            print(f"⚠️  Failed to archive diplomat message '{message_file}': {e}")

            return None

        return f"📨 EXTERNAL MESSAGE: {content}"


class RustDaemonClient:
    """HTTP bridge client for local Rust daemon orchestration."""

    def __init__(self, base_url: str, timeout_s: float):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)))

    def request_agent_response(
        self,
        *,
        agent_name: str,
        topic: str,
        context_block: str,
        recent_chat: str,
        mission: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        payload = {
            "agent": agent_name,
            "topic": topic,
            "context": context_block,
            "recent_chat": recent_chat,
            "mission": mission,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        response = self.client.post(f"{self.base_url}/v1/agents/respond", json=payload)
        response.raise_for_status()
        data = response.json()
        content = (data.get("content") or "").strip()
        if not content:
            raise RuntimeError("Rust daemon returned empty content")
        return content

    def poll_events(self) -> List[Dict[str, Any]]:
        try:
            response = self.client.get(f"{self.base_url}/v1/events/poll")
            if response.status_code >= 400:
                return []
            data = response.json()
            events = data.get("events", [])
            if isinstance(events, list):
                return [event for event in events if isinstance(event, dict)]
            return []
        except Exception:
            return []


# --- MAIN ORCHESTRATOR ---


class RainLabOrchestrator:
    """Main orchestrator with enhanced citation tracking and error handling"""

    def __init__(self, config: Config):

        self.config = config

        self.team = RainLabAgentFactory.create_team()

        self.context_manager = ContextManager(config)

        self.log_manager = LogManager(config)

        # Will be initialized after context loading

        self.director = None

        self.citation_analyzer = None

        self.web_search_manager = WebSearchManager(config)

        self.voice_engine = VoiceEngine()

        self.visual_event_server = VisualEventServer(config)
        self.visual_conversation_id: Optional[str] = None
        self.visual_conversation_active = False
        self.resonance_detector = ResonanceDetector()
        self.stagnation_monitor = StagnationMonitor()
        self.hypothesis_tree = HypothesisTree()
        self._current_hypothesis_id: Optional[int] = None
        self.tts_audio_dir = Path(config.library_path) / config.tts_audio_dir
        if self.config.export_tts_audio:
            self.tts_audio_dir.mkdir(parents=True, exist_ok=True)

        self.diplomat = Diplomat(base_path=self.config.library_path)

        self.hypergraph_manager = HypergraphManager(library_path=self.config.library_path)

        self.hypergraph_manager.build()

        self.rust_daemon_client: Optional[RustDaemonClient] = None

        # LLM client with extended timeout for large context processing

        if self.config.use_rust_daemon:
            try:
                self.rust_daemon_client = RustDaemonClient(
                    base_url=self.config.rust_daemon_api_url,
                    timeout_s=self.config.rust_daemon_timeout,
                )
                self.client = None
                print(f"🦀 Rust daemon mode enabled: {self.config.rust_daemon_api_url}")
            except Exception as e:
                print(f"❌ Failed to initialize Rust daemon client: {e}")
                sys.exit(1)
        else:
            try:
                import httpx

                # Allow configurable read timeout for slower local models / larger contexts

                connect_timeout = min(15.0, self.config.timeout)

                custom_timeout = httpx.Timeout(
                    connect_timeout,
                    read=self.config.timeout,
                    write=connect_timeout,
                    connect=connect_timeout,
                )

                self.client = openai.OpenAI(base_url=config.base_url, api_key=config.api_key, timeout=custom_timeout)

            except Exception as e:
                print(f"❌ Failed to initialize OpenAI client: {e}")

                sys.exit(1)

    def _emit_visual_event(self, payload: Dict):

        self.visual_event_server.emit(payload)

    def _start_visual_conversation(self, topic: str):

        if not self.config.emit_visual_events:
            return

        self.visual_conversation_id = f"c_{uuid.uuid4().hex[:8]}"
        self.visual_conversation_active = True

        participants = [agent.name.lower() for agent in self.team]
        self._emit_visual_event(
            {
                "type": "conversation_started",
                "conversation_id": self.visual_conversation_id,
                "topic": topic,
                "participants": participants,
            }
        )

    def _end_visual_conversation(self):

        if not self.visual_conversation_active:
            return

        self._emit_visual_event(
            {
                "type": "conversation_ended",
                "conversation_id": self.visual_conversation_id or "",
            }
        )
        self.visual_conversation_active = False

    def _export_audio_payload(self, turn_id: str, spoken_text: str, agent_name: str) -> Dict:

        duration_ms = self.voice_engine.estimate_duration_ms(spoken_text)

        if not self.config.export_tts_audio:
            return {"mode": "synthetic", "duration_ms": duration_ms}

        filename = f"{turn_id}_{agent_name.lower()}.wav"
        output_path = self.tts_audio_dir / filename
        exported_path = self.voice_engine.export_to_file(spoken_text, agent_name, output_path)
        if exported_path:
            return {
                "mode": "file",
                "path": exported_path.resolve().as_posix(),
                "duration_ms": duration_ms,
            }

        return {"mode": "synthetic", "duration_ms": duration_ms}

    def get_last_meeting_summary(self) -> str:
        """Load the tail of the newest archived meeting summary."""

        archive_pattern = os.path.join("meeting_archives", "*.md")

        archive_files = glob.glob(archive_pattern)

        if not archive_files:
            return ""

        newest_file = max(archive_files, key=os.path.getmtime)

        try:
            with open(newest_file, "r", encoding="utf-8") as f:
                return f.read()[-2000:]

        except Exception as e:
            print(f"⚠️  Failed to load meeting archive '{newest_file}': {e}")

            return ""

    def test_connection(self) -> bool:
        """Test LLM provider connection with retry"""

        print(f"\n🔌 Testing connection to LLM provider at {self.config.base_url}...")

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model_name, messages=[{"role": "user", "content": "test"}], max_tokens=5
                )

                print("   ✓ Connection successful!\n")

                return True

            except openai.APITimeoutError:
                print(f"   ⏱️  Timeout (attempt {attempt + 1}/3)")

                if attempt < 2:
                    time.sleep(2)

            except Exception as e:
                print(f"   ✗ Connection failed: {e}")

                if attempt == 2:
                    print("\n💡 Troubleshooting:")

                    print("   1. Is your LLM provider running? (Ollama: 'ollama serve', LM Studio: start the server)")

                    model = self.config.model_name
                    print(f"   2. Is model '{model}' available? (Ollama: 'ollama pull {model}')")

                    print(f"   3. Is the provider listening on {self.config.base_url}?")

                    print("   4. Default ports: Ollama=11434, LM Studio=1234")

                    print("   5. Override with: RAIN_LLM_BASE_URL=http://host:port/v1\n")

                else:
                    time.sleep(2)

        return False

    def _animate_spinner(self, label: str, duration: float = 0.9, color: str = "\033[96m"):
        """Display a short ANSI spinner animation for terminal feedback."""

        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

        end_time = time.time() + max(duration, 0.1)

        index = 0

        while time.time() < end_time:
            frame = frames[index % len(frames)]

            print(f"\r{color}{frame} {label}\033[0m", end="", flush=True)

            time.sleep(0.08)

            index += 1

        print(f"\r{color}✓ {label}\033[0m{' ' * 18}")

    def run_meeting(self, topic: str):
        """Run the research meeting"""

        # UTF-8 setup

        if sys.stdout.encoding != "utf-8":
            try:
                sys.stdout.reconfigure(encoding="utf-8")

            except Exception:  # Some runtimes lack reconfigure()
                pass

        # Header - 3D block ASCII Banner

        banner = r"""



▒▓█  V E R S 3 D Y N A M I C S   R . A . I . N .   L A B  █▓▒

░▒▓███    Recursive Architecture Intelligence Nexus    ███▓▒░

"""

        print(f"\033[96m{banner}\033[0m")

        print(f"📋 Topic: {topic}")

        # Test connection

        if not self.test_connection():
            return

        # Load context

        verbose = self.config.verbose

        if verbose:
            print("🔍 Scanning for Research Papers...")

        else:
            print("🔍 Scanning research library...", end="", flush=True)

        context_block, paper_list = self.context_manager.get_library_context(verbose=verbose)

        if not verbose:
            if paper_list:
                print(f"\r\033[K\033[92m✓\033[0m Scanned {len(paper_list)} papers")

            else:
                print(f"\r\033[K\033[91m✗\033[0m No papers found.")

        if not paper_list:
            print("\n❌ No papers found. Cannot proceed.")

            return

        # Initialize components that need context

        self.director = RainLabDirector(self.config, paper_list)

        self.citation_analyzer = CitationAnalyzer(self.context_manager)

        # Initialize eval metrics tracker

        self.metrics_tracker = None

        if MetricsTracker is not None:
            self.metrics_tracker = MetricsTracker(
                session_id=str(uuid.uuid4())[:8],
                topic=topic,
                model=self.config.model_name,
                recursive_depth=self.config.recursive_depth,
            )

            self.metrics_tracker.set_corpus(self.context_manager.loaded_papers)

        # Load agent souls from external files

        if verbose:
            print("\n🧠 Loading Agent Souls...")

        else:
            print("🧠 Loading agents...", end="", flush=True)

        for agent in self.team:
            agent.load_soul(self.config.library_path, verbose=verbose)

        if not verbose:
            print(f"\r\033[K\033[92m✓\033[0m Agents ready")

        # Perform web search for supplementary context

        web_context = ""

        if self.web_search_manager.enabled:
            if not verbose:
                print("🌐 Searching web...", end="", flush=True)

            web_context, results = self.web_search_manager.search(topic, verbose=verbose)

            if not verbose:
                count = len(results) if results else 0

                print(f"\r\033[K\033[92m✓\033[0m Web search ({count} results)")

        elif self.config.enable_web_search and not DDG_AVAILABLE and verbose:
            print("\n⚠️  Web search disabled: duckduckgo-search not installed")

            print("   Install with: pip install duckduckgo-search\n")

        # Combine contexts

        full_context = context_block

        if web_context:
            full_context = context_block + "\n\n" + web_context

        # Store for use in agent responses

        self.full_context = full_context

        previous_meeting_summary = self.get_last_meeting_summary()

        if previous_meeting_summary:
            self.full_context += "\n### PREVIOUS MEETING CONTEXT\n" + previous_meeting_summary

        # Initialize log

        self.log_manager.initialize_log(topic, len(paper_list))
        self._start_visual_conversation(topic)

        # Meeting setup

        history_log = []

        turn_count = 0

        print(f"\n🚀 TEAM MEETING")

        print(f"💡 Press Ctrl+C at any time to intervene as founder")

        print(f"💡 Welcome to the Vers3Dynamics Chatroom")

        print(f"💡 Meeting will wrap up after {self.config.max_turns - self.config.wrap_up_turns} discussion turns\n")

        print("=" * 70 + "\n")

        # Track wrap-up phase

        in_wrap_up = False

        wrap_up_complete = False

        # --- HYPOTHESIS TREE INITIALIZATION ---

        root_id = self.hypothesis_tree.add_root(topic)
        self._current_hypothesis_id = self.hypothesis_tree.select()

        # --- AUTONOMOUS LOOP WITH MANUAL INTERVENTION ---

        # Calculate when wrap-up should start

        wrap_up_start_turn = self.config.max_turns - self.config.wrap_up_turns

        while turn_count < self.config.max_turns:
            external_message = self.diplomat.check_inbox()

            if external_message:
                print(f"\n\033[93m{external_message}\033[0m")

                history_log.append(external_message)

            # Check if we should enter wrap-up phase

            if not in_wrap_up and turn_count >= wrap_up_start_turn:
                in_wrap_up = True

                print("\n" + "=" * 70)

                print("📋 MEETING WRAP-UP PHASE")

                print("=" * 70 + "\n")

            current_agent = self.team[turn_count % len(self.team)]

            # Check for user intervention with Windows-compatible key detection

            user_wants_to_speak = False

            print(f"\n{current_agent.color}▶ {current_agent.name}'s turn ({current_agent.role})\033[0m")

            print("\033[90m   [Press ENTER to speak, or wait...]\033[0m", end="", flush=True)

            # Cross-platform: check for keypress during brief window

            intervention_window = 1.5  # seconds to wait for user input

            start_time = time.time()

            while time.time() - start_time < intervention_window:
                if msvcrt and msvcrt.kbhit():  # Windows
                    key = msvcrt.getch()

                    user_wants_to_speak = True

                    break

                elif sys.platform != "win32":  # Unix/Linux/Mac
                    try:
                        r, _, _ = select.select([sys.stdin], [], [], 0)

                        if r:
                            sys.stdin.readline()

                            user_wants_to_speak = True

                            break

                    except Exception:
                        pass

                time.sleep(0.05)  # Small sleep to prevent CPU spinning

            print("\r" + " " * 50 + "\r", end="")  # Clear the "Press ENTER" prompt

            # Handle user intervention

            if user_wants_to_speak:
                print(f"\n\033[97m🎤 FOUNDER INTERVENTION (type 'done' to resume, 'quit' to end):\033[0m")

                while True:
                    try:
                        user_input = input("🎤 FOUNDER: ").strip()

                        if user_input.lower() in ["done", "continue", "resume", ""]:
                            print("\n\033[90m▶ Resuming automatic discussion...\033[0m\n")

                            break

                        elif user_input.lower() in ["quit", "exit", "stop"]:
                            print("\n👋 Meeting ended by FOUNDER.")

                            if self.metrics_tracker is not None:
                                self.metrics_tracker.finalize()

                            self.log_manager.finalize_log(self._generate_final_stats())
                            self._end_visual_conversation()

                            return

                        else:
                            print(f"\n\033[97m💬 [FOUNDER]: {user_input}\033[0m\n")

                            self.log_manager.log_statement("FOUNDER", user_input)

                            history_log.append(f"FOUNDER: {user_input}")

                    except (EOFError, KeyboardInterrupt):
                        print("\n\033[90m▶ Resuming automatic discussion...\033[0m\n")

                        break

            # 2. Generate Response

            response, metadata = self._generate_agent_response(
                current_agent, self.full_context, history_log, turn_count, topic, is_wrap_up=in_wrap_up
            )

            if response is None:
                print("❌ Failed to generate response after retries. Ending meeting.")

                break

            # 3. Analyze Citations

            if self.config.enable_citation_tracking:
                citation_analysis = self.citation_analyzer.analyze_response(current_agent.name, response)

                metadata = citation_analysis

                current_agent.citations_made += len(citation_analysis["verified"])

            # 3b. Update hypothesis tree based on citation results

            self._update_hypothesis_after_turn(response, metadata)

            # 4. Output - Clean up any duplicate name prefixes from the response

            clean_response = self._strip_agent_prefix(response, current_agent.name)

            print(f"\n{current_agent.color}{'─' * 70}")

            print(f"{current_agent.name}: {clean_response}")

            print(f"{'─' * 70}\033[0m")

            spoken_text = f"{current_agent.name}: {clean_response}"
            turn_id = f"t_{turn_count + 1:04d}"
            audio_payload = self._export_audio_payload(turn_id, spoken_text, current_agent.name)

            self._emit_visual_event(
                {
                    "type": "agent_utterance",
                    "conversation_id": self.visual_conversation_id or "",
                    "turn_id": turn_id,
                    "agent_id": current_agent.name.lower(),
                    "agent_name": current_agent.name,
                    "text": clean_response,
                    "tone": "neutral",
                    "audio": audio_payload,
                }
            )

            # Emit resonance_state when agents discuss frequencies/acoustics
            resonance = self.resonance_detector.analyze(clean_response)
            if resonance is not None:
                self._emit_visual_event(
                    {
                        "type": "resonance_state",
                        "conversation_id": self.visual_conversation_id or "",
                        **resonance,
                    }
                )

            self.voice_engine.speak(
                spoken_text,
                agent_name=current_agent.name,
            )

            search_match = RE_WEB_SEARCH_COMMAND.search(clean_response)

            if search_match:
                query = search_match.group(1).strip()

                if query:
                    print(f"\033[94m🌐 Active Web Search requested: {query}\033[0m")

                    web_note, web_results = self.web_search_manager.search(query, verbose=verbose)

                    if web_note:
                        print("\033[94m📎 Web Search Result:\033[0m")

                        print(web_note)

                        history_log.append(f"SYSTEM: Web search for '{query}'\n{web_note}")

                    else:
                        no_result_note = f"No web results returned for query: {query}"

                        print(f"\033[94m📎 Web Search Result: {no_result_note}\033[0m")

                        history_log.append(f"SYSTEM: {no_result_note}")

                    if web_results:
                        self.full_context += f"\n\n### LIVE WEB SEARCH\nQuery: {query}\n{web_note}"

            # Show citation feedback

            if metadata and metadata.get("verified"):
                print(f"\033[90m   ✓ {len(metadata['verified'])} citation(s) verified\033[0m")

                for quote, source in metadata["verified"][:1]:  # Show first citation
                    print(f'\033[90m      • "{quote[:60]}..." [from {source}]\033[0m')

            # 5. Log

            self.log_manager.log_statement(current_agent.name, response, metadata)

            history_log.append(f"{current_agent.name}: {response}")

            # 6. Epistemic failsafe: check for stagnation / dead-end loops

            verdict = self.stagnation_monitor.check(response)
            if verdict.intervention_prompt:
                history_log.append(f"SYSTEM: {verdict.intervention_prompt}")
                self.log_manager.log_statement("SYSTEM", verdict.intervention_prompt)
                print(f"\n\033[91m{'=' * 70}")
                print(f"  {verdict.intervention_prompt}")
                print(f"{'=' * 70}\033[0m\n")

            # 7. Record eval metrics for this turn

            if self.metrics_tracker is not None:
                self.metrics_tracker.record_turn(current_agent.name, response, metadata)

            turn_count += 1

        # Meeting officially closed

        print("\n" + "=" * 70)

        print("👋 MEETING ADJOURNED")

        print("=" * 70)

        print("\n\033[92mJames: Alright team, great discussion today! Let's reconvene soon.\033[0m")

        self.log_manager.log_statement("James", "Meeting adjourned. Great discussion everyone!")

        # Finalize

        if self.metrics_tracker is not None:
            self.metrics_tracker.finalize()

        stats = self._generate_final_stats()

        self.log_manager.finalize_log(stats)
        self._end_visual_conversation()

        print("\n" + "=" * 70)

        print(stats)

        print("=" * 70)

        print(f"\n✅ Session saved to: {self.log_manager.log_path}\n")

    def _poll_daemon_events(self):
        if not self.rust_daemon_client:
            return

        for event in self.rust_daemon_client.poll_events():
            self._emit_visual_event(event)
            if str(event.get("type", "")) == "agent_utterance":
                text = sanitize_text(str(event.get("content", "")))
                agent_name = str(event.get("agent_name", "")) or None
                if text:
                    self.voice_engine.speak(text, agent_name=agent_name)

    def _create_response_content(
        self,
        *,
        agent: Agent,
        topic: str,
        context_block: str,
        recent_chat: str,
        mission: str,
        user_msg: str,
    ) -> Tuple[str, Optional[str]]:
        if self.rust_daemon_client is not None:
            self._poll_daemon_events()
            content = self.rust_daemon_client.request_agent_response(
                agent_name=agent.name,
                topic=topic,
                context_block=context_block,
                recent_chat=recent_chat,
                mission=mission,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
            return content, None

        response = self.client.chat.completions.create(
            model=self.config.model_name,
            messages=[
                {"role": "system", "content": f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}"},
                {"role": "user", "content": user_msg},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        content = response.choices[0].message.content.strip()
        finish_reason = response.choices[0].finish_reason if hasattr(response.choices[0], "finish_reason") else None
        return content, finish_reason

    def _get_hypothesis_context(self) -> str:
        """Build the hypothesis-tree prompt fragment for the current node."""
        if self._current_hypothesis_id is None:
            return ""
        try:
            node = self.hypothesis_tree.get(self._current_hypothesis_id)
            if node.status != NodeStatus.ACTIVE:
                return ""
            return self.hypothesis_tree.get_current_hypothesis_prompt(self._current_hypothesis_id)
        except KeyError:
            return ""

    def _update_hypothesis_after_turn(self, response: str, metadata: Optional[Dict]) -> None:
        """Update the hypothesis tree based on citation analysis results."""
        if self._current_hypothesis_id is None:
            return
        try:
            node = self.hypothesis_tree.get(self._current_hypothesis_id)
        except KeyError:
            return
        if node.status != NodeStatus.ACTIVE:
            return

        # Use citation analysis: if unverified claims dominate, mark disproven.
        if metadata and isinstance(metadata, dict):
            unverified = metadata.get("unverified", [])
            verified = metadata.get("verified", [])
            if unverified:
                self.hypothesis_tree.add_evidence(
                    self._current_hypothesis_id,
                    f"Unverified claims: {len(unverified)}",
                )
            if verified:
                for quote, source in verified[:2]:
                    self.hypothesis_tree.add_evidence(
                        self._current_hypothesis_id,
                        f'Verified: "{quote[:60]}" [from {source}]',
                    )
            # Disprove if zero verified citations but 3+ unverified in this turn.
            if len(unverified) >= 3 and len(verified) == 0:
                self.hypothesis_tree.disprove(
                    self._current_hypothesis_id,
                    "Failed citation verification: no claims supported by local corpus",
                )
                print(
                    f"\033[91m  [HYPOTHESIS PRUNED] #{self._current_hypothesis_id}: "
                    f"failed fact-check against corpus\033[0m"
                )
                self._advance_hypothesis_selection()

    def _advance_hypothesis_selection(self) -> None:
        """Select the next hypothesis node via UCB1, or log exhaustion."""
        try:
            self._current_hypothesis_id = self.hypothesis_tree.select()
            node = self.hypothesis_tree.get(self._current_hypothesis_id)
            print(f"\033[96m  [HYPOTHESIS SELECTED] #{node.node_id}: {node.hypothesis}\033[0m")
        except ValueError:
            self._current_hypothesis_id = None
            print("\033[93m  [HYPOTHESIS TREE EXHAUSTED] All branches explored.\033[0m")

    def _generate_agent_response(
        self,
        agent: Agent,
        context_block: str,
        history_log: List[str],
        turn_count: int,
        topic: str,
        is_wrap_up: bool = False,
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Generate agent response with robust error handling and retries"""

        recent_chat = "\n".join(history_log[-self.config.recent_history_window :]) if history_log else "[Meeting Start]"

        # Use wrap-up instructions or normal mission

        if is_wrap_up:
            mission = self._get_wrap_up_instruction(agent, topic)

        else:
            mission = self.director.get_dynamic_instruction(agent, turn_count, topic)

        # Get previous speaker for conversational context

        prev_speaker = None

        if history_log:
            last_entry = history_log[-1]

            if ":" in last_entry:
                prev_speaker = last_entry.split(":")[0].strip()

        # ENHANCED PROMPT - CONVERSATIONAL TEAM MEETING STYLE

        conversational_instruction = ""

        if prev_speaker and prev_speaker != agent.name:
            conversational_instruction = f"""

CONVERSATIONAL CONTEXT:

{prev_speaker} just spoke. You are in a LIVE TEAM MEETING. You must:

1. FIRST: Directly respond to what {prev_speaker} said (agree, disagree, add nuance, ask a follow-up question)

2. THEN: Add your own perspective related to the mission below

3. Use phrases like "Building on what {prev_speaker} said...",
"I disagree with...", "That's interesting, but have you considered...",
"To add to that point..."

"""

        prompt = f"""### SHARED RESEARCH DATABASE (YOUR ONLY FACTUAL SOURCE)

{context_block}



### MEETING TRANSCRIPT (Recent Discussion)

{recent_chat}



### YOUR PROFILE

{agent.soul}

{conversational_instruction}

{self._get_hypothesis_context()}

### CURRENT TASK

{mission}



CRITICAL RULES:

- You are in a TEAM MEETING - respond to colleagues, don't just monologue

- Use "exact quotes" from the papers when citing data

- Mention which paper you're quoting: [from filename.md]

- If you must speculate, prefix with [SPECULATION]

- CRITICAL: If you need to verify a fact online, type: [SEARCH: your query]

- {meeting_response_length_guidance()}



{agent.name}:"""

        self._animate_spinner(f"{agent.name} analyzing", duration=1.0, color=agent.color)

        # RETRY LOGIC

        for attempt in range(self.config.max_retries):
            try:
                # Build conversational user message based on agreeableness

                if prev_speaker and prev_speaker != agent.name and prev_speaker != "FOUNDER":
                    # Agreeableness-based response style with explicit agree/disagree

                    if agent.agreeableness < 0.3:
                        style_instruction = (
                            f"STYLE: You STRONGLY DISAGREE with {prev_speaker}."
                            " Be direct and combative:\n\n"
                            "- Challenge their assumptions or data interpretation\n\n"
                            "- Point out flaws in their reasoning or missing considerations"
                        )

                    elif agent.agreeableness < 0.5:
                        style_instruction = (
                            f"STYLE: You're SKEPTICAL of what {prev_speaker} said."
                            " Question their claims:\n\n"
                            "- Demand evidence or point out logical gaps\n\n"
                            "- Ask probing questions about feasibility or rigor"
                        )

                    elif agent.agreeableness < 0.7:
                        style_instruction = f"""STYLE: You PARTIALLY AGREE with {prev_speaker} but add nuance:

- Acknowledge one valid point then offer a different angle

- Redirect the discussion toward your specialty"""

                    else:
                        style_instruction = f"""STYLE: You AGREE with {prev_speaker} and BUILD on it:

- Add a NEW insight they didn't mention

- Extend their idea in a new direction"""

                    user_msg = f"""LIVE TEAM MEETING - Your turn to speak.



RECENT DISCUSSION:

{recent_chat}



{style_instruction}



=== CRITICAL RULES (MUST FOLLOW) ===

1. YOU ARE {agent.name.upper()} - Never speak as another person or quote what others "would say"

2. DO NOT REPEAT phrases others just said - use completely different wording

3. ADVANCE the discussion - raise a NEW point, question, or angle not yet discussed

4. Focus on YOUR specialty: {agent.focus}

5. {meeting_response_length_guidance()}

6. {no_self_name_intro_guidance()}

7. CRITICAL: If you need to verify a fact online, type: [SEARCH: your query]



Your task: {mission}



Respond as {agent.name} only:"""

                else:
                    # First speaker or after FOUNDER - open the discussion naturally

                    user_msg = f"""You are {agent.name}, STARTING a team meeting discussion.



Previous context: {recent_chat}



=== YOUR INSTRUCTIONS ===

1. Open casually and introduce the topic briefly

2. Share ONE specific observation from the papers

3. End with a question to spark discussion

4. {meeting_response_length_guidance()}

5. {no_self_name_intro_guidance()}


Your specialty: {agent.focus}

Your task: {mission}



Respond as {agent.name} only:"""

                if agent.name == "Luca":
                    graph_findings = self.hypergraph_manager.query(topic=topic)

                    user_msg += f"""



HIDDEN CONNECTIONS (KNOWLEDGE HYPERGRAPH):

{graph_findings}

Use these links to propose creative cross-paper insights if relevant.

"""
                # Use daemon bridge or direct provider call for primary generation
                content, finish_reason = self._create_response_content(
                    agent=agent,
                    topic=topic,
                    context_block=context_block,
                    recent_chat=recent_chat,
                    mission=mission,
                    user_msg=user_msg,
                )

                # Guardrail: some local models collapse back to James' opener template

                # on later turns, which appears in LM Studio logs as repeated intros.

                if turn_count >= 1 and agent.name == "James":
                    lowered = content.lower()

                    repeated_intro = (
                        lowered.startswith("hey team")
                        or "today we're looking into" in lowered
                        or "today we're talking about" in lowered
                    )

                    if repeated_intro:
                        correction = self.client.chat.completions.create(
                            model=self.config.model_name,
                            messages=[
                                {
                                    "role": "system",
                                    "content": f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}",
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        "You are in mid-meeting, not opening the session. "
                                        "Do NOT use intro phrases like 'Hey team' or restate the topic. "
                                        "React to the previous speaker by name in the first sentence, "
                                        "add one new concrete paper-grounded point, and end with a question. "
                                        f"{no_self_name_intro_guidance()} "
                                        f"{meeting_response_length_guidance()}"
                                    ),
                                },
                            ],
                            temperature=self.config.temperature,
                            max_tokens=self.config.max_tokens,
                        )

                        corrected = correction.choices[0].message.content.strip()

                        if corrected:
                            content = corrected

                # Optional recursive refinement: critique + revise in short internal loops

                if self.config.recursive_intellect and self.config.recursive_depth > 0 and content:
                    for _ in range(self.config.recursive_depth):
                        pre_critique_text = content  # snapshot for metrics

                        critique = self.client.chat.completions.create(
                            model=self.config.model_name,
                            messages=[
                                {"role": "system", "content": f"You are a strict research editor for {agent.name}."},
                                {
                                    "role": "user",
                                    "content": (
                                        "Review this draft and return a compact critique with exactly 3 bullets: "
                                        "(1) factual grounding to provided papers, (2) novelty vs prior turns, "
                                        f"(3) clarity and completeness within {PRIMARY_RESPONSE_WORD_TARGET}.\n\n"
                                        f"DRAFT:\n{content}\n\n"
                                        "If there are no issues, still return 3 bullets and say what is strong."
                                    ),
                                },
                            ],
                            temperature=0.2,
                            max_tokens=120,
                        )

                        critique_text = critique.choices[0].message.content.strip()

                        refined = self.client.chat.completions.create(
                            model=self.config.model_name,
                            messages=[
                                {
                                    "role": "system",
                                    "content": f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}",
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        f"Revise this response as {agent.name} using critique below. "
                                        f"Keep it within {PRIMARY_RESPONSE_WORD_TARGET} across "
                                        f"{PRIMARY_RESPONSE_SENTENCE_TARGET}, add one concrete paper-grounded point, "
                                        "avoid repetition, respond in first person only, "
                                        "and do not start with your own name.\n\n"
                                        f"ORIGINAL:\n{content}\n\n"
                                        f"CRITIQUE:\n{critique_text}"
                                    ),
                                },
                            ],
                            temperature=self.config.temperature,
                            max_tokens=self.config.max_tokens,
                        )

                        content = refined.choices[0].message.content.strip() or content

                        # Record critique pair for eval metrics

                        if self.metrics_tracker is not None:
                            self.metrics_tracker.record_critique(pre_critique_text, content)

                # Clean up response - remove agent speaking as self

                if content.startswith(f"{agent.name}:"):
                    content = content.replace(f"{agent.name}:", "", 1).strip()

                # Remove lines where agent speaks as OTHER team members (identity confusion)

                other_agents = ["James", "Jasmine", "Luca", "Elena"]

                cleaned_lines = []

                for line in content.split("\n"):
                    # Check if line starts with another agent's name followed by colon

                    is_other_agent_line = False

                    for other in other_agents:
                        if other != agent.name and line.strip().startswith(f"{other}:"):
                            is_other_agent_line = True

                            break

                    if not is_other_agent_line:
                        cleaned_lines.append(line)

                content = "\n".join(cleaned_lines).strip()

                # Check if response was truncated (doesn't end with sentence-ending punctuation)

                is_truncated = self._looks_truncated_response(content, finish_reason)

                if is_truncated:
                    print("(completing...)", end=" ", flush=True)

                    # Request continuation

                    try:
                        continuation = self.client.chat.completions.create(
                            model=self.config.model_name,
                            messages=[
                                {"role": "system", "content": f"{agent.soul}"},
                                {
                                    "role": "user",
                                    "content": (
                                        "Complete this thought in ONE complete sentence so the turn ends cleanly. "
                                        "Do not restart with your own name or a speaker label.\n\n"
                                        f"{content}"
                                    ),
                                },
                            ],
                            temperature=self.config.temperature,
                            max_tokens=60,  # Just enough to finish the thought
                        )

                        cont_text = continuation.choices[0].message.content.strip()

                        # Clean continuation - remove if it starts with the same text

                        if cont_text and not cont_text.startswith(content[:20]):
                            # Check if continuation is a complete sentence fragment

                            if not cont_text[0].isupper():
                                content = content + " " + cont_text

                            else:
                                # Model restarted - just ensure we end cleanly

                                # Find last complete sentence in original

                                for end in [". ", "! ", "? "]:
                                    if end in content:
                                        last_end = content.rfind(end)

                                        if last_end > len(content) * 0.5:  # Last sentence in second half
                                            content = content[: last_end + 1]

                                            break

                                else:
                                    # No good sentence end found, append ellipsis

                                    content = content.rstrip(",;:") + "..."

                    except Exception:
                        # Continuation failed - try to end gracefully

                        for end in [". ", "! ", "? "]:
                            if end in content:
                                last_end = content.rfind(end)

                                if last_end > len(content) * 0.5:
                                    content = content[: last_end + 1]

                                    break

                        else:
                            content = content.rstrip(",;:") + "..."

                content = self._repair_incomplete_response(
                    agent=agent,
                    topic=topic,
                    context_block=context_block,
                    content=content,
                    finish_reason=None,
                )

                # CORRUPTION CHECK - validate response before accepting

                is_corrupted, corruption_reason = self._is_corrupted_response(content)

                if is_corrupted and corruption_reason == "Incomplete sentence":
                    repaired = self._repair_too_short_response(
                        agent=agent,
                        topic=topic,
                        context_block=context_block,
                        short_content=content,
                    )
                    if repaired:
                        repaired_corrupted, repaired_reason = self._is_corrupted_response(repaired)
                        if not repaired_corrupted:
                            content = repaired
                            is_corrupted = False
                            corruption_reason = ""
                        else:
                            corruption_reason = repaired_reason

                if is_corrupted:
                    print(f"\n⚠️  Corrupted response detected ({corruption_reason})")

                    if attempt < self.config.max_retries - 1:
                        print("   Regenerating...")

                        time.sleep(1)

                        continue  # Retry

                    else:
                        print("   Falling back to placeholder response.")

                        content = f"[{agent.name} is processing... Let me gather my thoughts on this topic.]"

                print("✓")

                return content, {}

            except openai.APITimeoutError:
                print(f"\n⏱️  Timeout (attempt {attempt + 1}/{self.config.max_retries})")

                if attempt < self.config.max_retries - 1:
                    print("   Retrying in 2 seconds...")

                    time.sleep(2)

                else:
                    print("\n💡 The model might be overloaded. Try:")

                    print("   1. Reducing max_tokens in Config")

                    print("   2. Checking LM Studio's server logs")

                    return None, None

            except openai.APIConnectionError as e:
                print(f"\n❌ Connection Lost (attempt {attempt + 1}/{self.config.max_retries})")

                if attempt < self.config.max_retries - 1:
                    print("   Retrying in 3 seconds...")

                    time.sleep(3)

                else:
                    print("\n💡 Connection failed after retries. Check:")

                    print("   1. Is LM Studio still running?")

                    print("   2. Did the model unload? (Check LM Studio model tab)")

                    print("   3. Try reloading the model in LM Studio")

                    return None, None

            except openai.APIError as e:
                print(f"\n❌ API Error: {e}")

                if attempt < self.config.max_retries - 1:
                    time.sleep(2)

                else:
                    return None, None

            except Exception as e:
                print(f"\n❌ Unexpected Error: {e}")

                return None, None

        return None, None

    def _repair_too_short_response(
        self,
        *,
        agent: Agent,
        topic: str,
        context_block: str,
        short_content: str,
    ) -> str:
        """Ask the model to expand a fragment into a complete answer before falling back."""

        prompt_fragment = short_content.strip() or "[empty response]"

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {"role": "system", "content": f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}"},
                    {
                        "role": "user",
                        "content": (
                            f"Your last reply was too short or incomplete: {prompt_fragment}\n\n"
                            f"Rewrite it as {agent.name} answering this topic directly: {topic}\n"
                            f"- Use {REPAIR_RESPONSE_SENTENCE_TARGET}\n"
                            f"- Aim for {PRIMARY_RESPONSE_WORD_TARGET}\n"
                            f"- {no_self_name_intro_guidance()}\n"
                            "- No stage directions, role labels, placeholders, or code fences\n"
                            "- If the short draft had a useful idea, keep it and expand it"
                        ),
                    },
                ],
                temperature=self.config.temperature,
                max_tokens=min(self.config.max_tokens, 180),
            )
            repaired = response.choices[0].message.content.strip()
        except Exception:
            return ""

        repaired = self._strip_agent_prefix(repaired, agent.name).strip()
        other_agents = {"James", "Jasmine", "Luca", "Elena"} - {agent.name}
        cleaned_lines = [
            line
            for line in repaired.split("\n")
            if not any(line.strip().startswith(f"{other}:") for other in other_agents)
        ]
        return "\n".join(cleaned_lines).strip()

    def _repair_incomplete_response(
        self,
        *,
        agent: Agent,
        topic: str,
        context_block: str,
        content: str,
        finish_reason: Optional[str],
    ) -> str:
        """Repair dangling clauses that still look incomplete after continuation."""

        if not self._looks_truncated_response(content, finish_reason):
            return content

        repaired = self._repair_too_short_response(
            agent=agent,
            topic=topic,
            context_block=context_block,
            short_content=content,
        )
        if not repaired:
            return content

        repaired_corrupted, _ = self._is_corrupted_response(repaired)
        if repaired_corrupted or self._looks_truncated_response(repaired, None):
            return content

        return repaired

    def _looks_truncated_response(self, text: str, finish_reason: Optional[str]) -> bool:
        """Detect dangling clauses that should be completed before acceptance."""

        if finish_reason == "length":
            return True

        normalized = (text or "").strip()
        if not normalized:
            return False

        if RE_WEB_SEARCH_COMMAND.search(normalized):
            return False

        if normalized.endswith((".", "!", "?", '"', "'", ")", "]")):
            return False

        words = re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)?", normalized)
        # Only flag as truncated if ending with comma/colon AND the response is suspiciously
        # short (under 50 chars) — longer responses with these endings are often intentional.
        if normalized.endswith((",", ";", ":")) and len(normalized) < 50:
            return True

        # For longer responses, only flag if there are obvious incomplete clause patterns
        if normalized.endswith((",", ";")):
            incomplete_clause_patterns = (
                r"\b(which|because|although|however|therefore|while|when|if|that|where)\s*[,:;]?\s*$",
                r"\b(the|a|an)\s+$",
                r"\b(and|but|or)\s+$",
            )
            for pattern in incomplete_clause_patterns:
                if re.search(pattern, normalized, re.IGNORECASE):
                    return True

        return False

    def _is_corrupted_response(self, text: str) -> Tuple[bool, str]:
        """

        Detect corrupted/garbled LLM outputs using multiple heuristics.

        Returns (is_corrupted, reason) tuple.

        """

        normalized = (text or "").strip()

        if not normalized:
            return True, "Response too short"

        # Heuristic 1: Too many consecutive uppercase letters (token corruption)

        # Pattern like "AIVERCREDREDRIECKERE" is a sign of corruption

        if RE_CORRUPTION_CAPS.search(normalized):
            return True, "Excessive consecutive capitals detected"

        # Heuristic 2: High ratio of special characters (gibberish)

        special_chars = sum(1 for c in normalized if c in ":;/\\|<>{}[]()@#$%^&*+=~`")

        if len(normalized) > 20 and special_chars / len(normalized) > 0.15:
            return True, "Too many special characters"

        # Heuristic 3: Common corruption patterns

        for pattern in RE_CORRUPTION_PATTERNS:
            if pattern.search(normalized):
                return True, f"Corruption pattern detected: {pattern.pattern[:20]}"

        if len(normalized) < 20:
            # Compact answers like "I disagree." or "Why?" are valid in beginner/chat mode.
            # Only flag genuinely empty or truly broken responses.
            sentence_candidate = normalized.rstrip("'\"”’)]}")
            short_words = re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)?", normalized)
            if short_words and (sentence_candidate.endswith((".", "!", "?")) or len(short_words) >= 2):
                return False, ""
            if not short_words:
                return True, "Response too short"
            # Brevity is not corruption — the model chose to be concise.
            return False, ""

        if RainLabOrchestrator._looks_truncated_response(None, normalized, None):
            return True, "Incomplete sentence"

        # Heuristic 4: Too many empty lines or lines with just punctuation

        lines = normalized.split("\n")

        empty_lines = sum(1 for line in lines if len(line.strip()) <= 2)

        if len(lines) > 5 and empty_lines / len(lines) > 0.5:
            return True, "Too many empty lines"

        # Heuristic 5: Average word length too high (concatenated garbage)

        words = normalized.split()

        if words:
            avg_word_len = sum(len(w) for w in words) / len(words)

            if avg_word_len > 15:
                return True, "Average word length too high (likely corrupted)"

        return False, ""

    def _get_wrap_up_instruction(self, agent: Agent, topic: str) -> str:
        """Get wrap-up phase instructions for each agent to close the meeting naturally"""

        wrap_up_instructions = {
            "James": f"""WRAP-UP TIME: You are closing the meeting. As lead scientist:

- Summarize the KEY TAKEAWAY about '{topic}' from today's discussion

- Mention 1-2 specific insights from your colleagues that stood out

- Suggest ONE concrete next step or action item for the team

- End with something like 'Good discussion today' or 'Let's pick this up next time'

{wrap_up_response_length_guidance()}""",
            "Jasmine": f"""WRAP-UP TIME: Give your closing thoughts on '{topic}':

- State your MAIN CONCERN or practical challenge going forward

- Acknowledge if any colleague made a good point about feasibility

- Mention what you'd need to see before moving forward

{wrap_up_response_length_guidance()} Be direct and practical as always.""",
            "Luca": f"""WRAP-UP TIME: Give your closing synthesis on '{topic}':

- Find the COMMON GROUND between what everyone said

- Highlight how different perspectives complemented each other

- Express optimism about where the research is heading

{wrap_up_response_length_guidance()} Stay diplomatic and unifying.""",
            "Elena": f"""WRAP-UP TIME: Give your final assessment of '{topic}':

- State the most important MATHEMATICAL or THEORETICAL point established

- Note any concerns about rigor that still need addressing

- Acknowledge good work from colleagues if warranted

{wrap_up_response_length_guidance()} Maintain your standards but be collegial.""",
        }

        return wrap_up_instructions.get(
            agent.name,
            f"Provide your closing thoughts on '{topic}'. {wrap_up_response_length_guidance()}",
        )

    def _generate_final_stats(self) -> str:
        """Generate final statistics"""

        stats_lines = [
            "SESSION STATISTICS",
            "─" * 70,
        ]

        if self.citation_analyzer:
            stats_lines.append(self.citation_analyzer.get_stats())

            stats_lines.append("")

        stats_lines.append("AGENT PERFORMANCE:")

        for agent in self.team:
            stats_lines.append(f"  • {agent.name}: {agent.citations_made} verified citations")

        # Append eval-framework metrics when available

        if self.metrics_tracker is not None:
            m = self.metrics_tracker.summary()

            stats_lines.append("")

            stats_lines.append("EVAL METRICS:")

            stats_lines.append(f"  • Citation accuracy:    {m['citation_accuracy']:.2f}")

            stats_lines.append(f"  • Novel-claim density:  {m['novel_claim_density']:.2f}")

            stats_lines.append(f"  • Critique change rate: {m['critique_change_rate']:.2f}")

        # Hypothesis tree summary
        if self.hypothesis_tree.size > 0:
            stats_lines.append("")
            stats_lines.append("HYPOTHESIS TREE:")
            proven = self.hypothesis_tree.proven_nodes()
            disproven = self.hypothesis_tree.disproven_nodes()
            active = self.hypothesis_tree.active_nodes()
            stats_lines.append(f"  • Proven: {len(proven)}  Active: {len(active)}  Disproven: {len(disproven)}")
            for node in proven:
                stats_lines.append(f"    [+] #{node.node_id}: {node.hypothesis}")
            for node in disproven[:5]:
                stats_lines.append(f"    [X] #{node.node_id}: {node.hypothesis}")

        return "\n".join(stats_lines)

    def _strip_agent_prefix(self, response: str, agent_name: str) -> str:
        """Strip duplicate agent name prefixes from the response.



        Handles patterns like:

        - "James: ..."

        - "James (R.A.I.N. Lab Lead): ..."

        - "James (R.A.I.N. Lab): ..."

        """

        cleaned = (response or "").strip()
        escaped_name = re.escape(agent_name)
        patterns = [
            rf"^{escaped_name}\s*(?:\([^)]*\))?\s*[:\-–—]\s*",
            rf"^{escaped_name}\s+here\s*[,:\-–—]\s*",
            rf"^(?:i am|i['’]?m|im|this is)\s+{escaped_name}(?:\s*[,:\-–—]\s*|\s+and\s+)",
        ]

        while cleaned:
            updated = cleaned
            for pattern in patterns:
                updated = re.sub(pattern, "", updated, count=1, flags=re.IGNORECASE).strip()
            if updated == cleaned:
                break
            cleaned = updated

        return cleaned.strip()


# --- CLI INTERFACE ---


def parse_args():
    """Parse command line arguments"""

    parser = argparse.ArgumentParser(
        description="R.A.I.N. LAB - Research",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""

Examples:

  python rain_lab_v31_production.py --topic "quantum resonance"

  python rain_lab_v31_production.py --library ./my_papers --topic "field theory"

  python rain_lab_v31_production.py --temp 0.3 --topic "entanglement"
  python rain_lab_v31_production.py --temp 0.85 --max-tokens 320 --topic "entanglement"

        """,
    )

    parser.add_argument("--library", type=str, default=DEFAULT_LIBRARY_PATH, help="Path to research library folder")

    parser.add_argument("--topic", type=str, help="Research topic (if not provided, will prompt)")

    parser.add_argument(
        "--model", type=str, default=DEFAULT_MODEL_NAME, help=f"LLM model name (default: {DEFAULT_MODEL_NAME})"
    )

    parser.add_argument(
        "--base-url",
        type=str,
        default=os.environ.get(
            "RAIN_LLM_BASE_URL",
            os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:11434/v1"),
        ),
        help="OpenAI-compatible base URL (default: Ollama at http://127.0.0.1:11434/v1)",
    )

    parser.add_argument(
        "--temp",
        type=float,
        default=float(os.environ.get("RAIN_CHAT_TEMP", "0.7")),
        help="LLM temperature (0.0-1.0, default: 0.7; raise for more exploratory outputs)",
    )

    parser.add_argument(
        "--recursive-depth",
        type=int,
        default=int(os.environ.get("RAIN_RECURSIVE_DEPTH", "1")),
        help="Internal self-reflection passes per response (default: 1)",
    )

    parser.add_argument(
        "--no-recursive-intellect", action="store_true", help="Disable recursive self-reflection refinement"
    )

    parser.add_argument(
        "--recursive-library-scan", action="store_true", help="Recursively scan nested folders in the research library"
    )

    parser.add_argument(
        "--no-recursive-library-scan",
        action="store_true",
        help="Scan only top-level files in the research library (default)",
    )

    parser.add_argument("--max-turns", type=int, default=25, help="Maximum conversation turns (default: 25)")

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("RAIN_CHAT_MAX_TOKENS", "320")),
        help="Max tokens per response (default: 320)",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("RAIN_LM_TIMEOUT", "300")),
        help="LLM read timeout in seconds (default: 300)",
    )

    parser.add_argument("--no-web", action="store_true", help="Disable DuckDuckGo web search")

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed loading output (papers, souls, web search)"
    )

    parser.add_argument(
        "--emit-visual-events",
        action="store_true",
        help="Stream neutral conversation events to Godot clients via embedded WebSocket server",
    )

    parser.add_argument(
        "--no-emit-visual-events",
        action="store_true",
        help="Disable visual event streaming even if env enables it",
    )

    parser.add_argument(
        "--visual-events-host",
        type=str,
        default=os.environ.get("RAIN_VISUAL_EVENTS_HOST", "127.0.0.1"),
        help="WebSocket host for visual event server (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--visual-events-port",
        type=int,
        default=int(os.environ.get("RAIN_VISUAL_EVENTS_PORT", "8765")),
        help="WebSocket port for visual event server (default: 8765)",
    )

    parser.add_argument(
        "--log-visual-events",
        action="store_true",
        help="Also write visual events to a JSONL file for debugging",
    )

    parser.add_argument(
        "--visual-events-log",
        type=str,
        default=os.environ.get("RAIN_VISUAL_EVENTS_LOG", "meeting_archives/godot_events.jsonl"),
        help="Path (relative to --library or absolute) for JSONL debug log (requires --log-visual-events)",
    )

    parser.add_argument(
        "--tts-audio-dir",
        type=str,
        default=os.environ.get("RAIN_TTS_AUDIO_DIR", "meeting_archives/tts_audio"),
        help="Directory (relative to --library or absolute) for per-turn TTS audio files",
    )

    parser.add_argument(
        "--no-export-tts-audio",
        action="store_true",
        help="Disable per-turn TTS file export (keeps spoken audio behavior unchanged)",
    )

    args, unknown = parser.parse_known_args()

    if unknown:
        print(f"⚠️ Ignoring unrecognized args: {' '.join(unknown)}")

    return args


# --- ENTRY POINT ---


def main():
    """Main entry point"""

    args = parse_args()

    recursive_library_scan = DEFAULT_RECURSIVE_LIBRARY_SCAN

    if args.recursive_library_scan:
        recursive_library_scan = True

    if args.no_recursive_library_scan:
        recursive_library_scan = False

    emit_visual_events = os.environ.get("RAIN_VISUAL_EVENTS", "0") == "1"
    if args.emit_visual_events:
        emit_visual_events = True
    if args.no_emit_visual_events:
        emit_visual_events = False

    log_visual_events = os.environ.get("RAIN_LOG_VISUAL_EVENTS", "0") == "1"
    if getattr(args, "log_visual_events", False):
        log_visual_events = True

    export_tts_audio = os.environ.get("RAIN_EXPORT_TTS_AUDIO", "1") != "0"
    if args.no_export_tts_audio:
        export_tts_audio = False

    # Create config from args

    config = Config(
        library_path=args.library,
        temperature=args.temp,
        max_turns=args.max_turns,
        max_tokens=args.max_tokens,
        enable_web_search=not args.no_web,
        verbose=args.verbose,
        model_name=args.model,
        base_url=args.base_url,
        timeout=max(30.0, args.timeout),
        recursive_depth=max(1, args.recursive_depth),
        recursive_intellect=not args.no_recursive_intellect,
        recursive_library_scan=recursive_library_scan,
        emit_visual_events=emit_visual_events,
        visual_events_host=args.visual_events_host,
        visual_events_port=args.visual_events_port,
        log_visual_events=log_visual_events,
        visual_events_log=args.visual_events_log,
        export_tts_audio=export_tts_audio,
        tts_audio_dir=args.tts_audio_dir,
    )

    # Get topic

    if args.topic:
        topic = args.topic

    else:
        print("\n" + "=" * 70)

        print("R.A.I.N. LAB - RESEARCH FOCUS")

        print("=" * 70)

        topic = input("\n🔬 Research Topic: ").strip()

    if not topic:
        print("❌ No topic provided. Exiting.")

        sys.exit(1)

    # Run meeting

    orchestrator = RainLabOrchestrator(config)

    orchestrator.run_meeting(topic)


if __name__ == "__main__":
    main()
