"""Main meeting orchestrator with citation tracking and error handling."""

import glob
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import msvcrt
except ImportError:
    msvcrt = None
try:
    import select
except ImportError:
    select = None

import threading

import openai

try:
    from rain_metrics import MetricsTracker
except ImportError:
    MetricsTracker = None

try:
    from graph_bridge import HypergraphManager
except ImportError:

    class HypergraphManager:
        """No-op stub when graph_bridge is not installed."""

        def __init__(self, **_kw):
            pass

        def build(self):
            pass

        def query(self, **_kw):
            return None

from rain_lab_chat._logging import clear_terminal_overlay, set_terminal_overlay, terminal_output_lock
from rain_lab_chat._sanitize import RE_WEB_SEARCH_COMMAND
from rain_lab_chat.agents import Agent, RainLabAgentFactory
from rain_lab_chat.citations import CitationAnalyzer
from rain_lab_chat.config import Config
from rain_lab_chat.context import ContextManager
from rain_lab_chat.director import RainLabDirector
from rain_lab_chat.doctor import collect_lm_studio_diagnostics
from rain_lab_chat.guardrails import (
    is_corrupted_response,
    strip_agent_prefix,
)
from rain_lab_chat.logging_events import CheckpointManager, Diplomat, LogManager, SessionRunLedger, VisualEventLogger
from rain_lab_chat.response_gen import (
    build_user_message,
    call_llm_with_retry,
    fix_repeated_intro,
    get_wrap_up_instruction,
    handle_truncation,
    refine_response,
)
from rain_lab_chat.voice import VoiceEngine
from rain_lab_chat.web_search import DDG_AVAILABLE, WebSearchManager

try:
    from rich_ui import (
        AGENT_COLORS,
        agent_banner,
        color,
        meeting_header,
        print_panel,
        print_progress,
        status_indicator,
        supports_ansi,
    )
    _RICH_UI = True
    _ANSI_OK = supports_ansi()
except ImportError:
    _RICH_UI = False
    _ANSI_OK = True  # assume True when rich_ui is absent (legacy behavior)


def _a(code: str) -> str:
    """Return *code* only when ANSI is supported; empty string otherwise."""
    return code if _ANSI_OK else ""


# Map symbolic color names → ANSI codes (bright variants for readability)
_COLOR_MAP = {
    "green": "\033[92m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "red": "\033[91m",
    "blue": "\033[94m",
    "white": "\033[97m",
}


def _resolve_color(name: str) -> str:
    """Resolve a symbolic color name (or raw ANSI code) to a safe ANSI string."""
    if name.startswith("\033["):
        return _a(name)  # legacy raw code
    return _a(_COLOR_MAP.get(name, ""))


# Commonly used ANSI shortcuts (empty when unsupported)
_RST = _a("\033[0m")
_DIM = _a("\033[90m")
_RED = _a("\033[91m")
_GRN = _a("\033[92m")
_YLW = _a("\033[93m")
_BLU = _a("\033[94m")
_MAG = _a("\033[95m")
_CYN = _a("\033[96m")
_WHT = _a("\033[97m")
_CLR = _a("\033[K")


class RainLabOrchestrator:
    """Main orchestrator with enhanced citation tracking and error handling"""

    def __init__(self, config: Config):

        self.config = config

        self.team = RainLabAgentFactory.create_team()

        self.context_manager = ContextManager(config)

        self.log_manager = LogManager(config)
        self.checkpoint_manager = CheckpointManager(config)
        self.session_run_ledger = SessionRunLedger(config)

        # Will be initialized after context loading

        self.director = None

        self.citation_analyzer = None
        self.metrics_tracker = None
        self.session_run_id: Optional[str] = None
        self.session_started_at: Optional[str] = None
        self.session_resumed = False
        self.session_resume_source: Optional[str] = None
        self.last_connection_diagnostics: Optional[Dict] = None

        self.web_search_manager = WebSearchManager(config)

        self.voice_engine = VoiceEngine()

        self.visual_event_logger = VisualEventLogger(config)
        self.visual_conversation_id: Optional[str] = None
        self.visual_conversation_active = False
        self.tts_audio_dir = Path(config.library_path) / config.tts_audio_dir
        if self.config.emit_visual_events and self.config.export_tts_audio:
            self.tts_audio_dir.mkdir(parents=True, exist_ok=True)

        self.diplomat = Diplomat(base_path=self.config.library_path)

        self.hypergraph_manager = HypergraphManager(library_path=self.config.library_path)

        self.hypergraph_manager.build()

        # LLM client with extended timeout for large context processing

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

        self.visual_event_logger.emit(payload)

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
        exported = self.voice_engine.export_to_file(spoken_text, agent_name, output_path)
        if exported:
            return {
                "mode": "file",
                "path": output_path.resolve().as_posix(),
                "duration_ms": duration_ms,
            }

        return {"mode": "synthetic", "duration_ms": duration_ms}

    def _metrics_checkpoint_state(self) -> Optional[Dict]:

        if self.metrics_tracker is None:
            return None

        return {
            "session_id": self.metrics_tracker.session_id,
            "topic": self.metrics_tracker.topic,
            "model": self.metrics_tracker.model,
            "recursive_depth": self.metrics_tracker.recursive_depth,
            "turn_count": self.metrics_tracker._turn_count,
            "all_quotes": list(self.metrics_tracker._all_quotes),
            "all_claims": list(self.metrics_tracker._all_claims),
            "critique_pairs": [list(pair) for pair in self.metrics_tracker._critique_pairs],
        }

    def _restore_metrics_checkpoint_state(self, payload: Optional[Dict]):

        if self.metrics_tracker is None or not payload:
            return

        turn_count = payload.get("turn_count", self.metrics_tracker._turn_count)
        try:
            turn_count = int(turn_count)
        except (TypeError, ValueError):
            turn_count = self.metrics_tracker._turn_count

        self.metrics_tracker.session_id = str(payload.get("session_id", self.metrics_tracker.session_id))
        self.metrics_tracker.topic = str(payload.get("topic", self.metrics_tracker.topic))
        self.metrics_tracker.model = str(payload.get("model", self.metrics_tracker.model))

        recursive_depth = payload.get("recursive_depth", self.metrics_tracker.recursive_depth)
        try:
            self.metrics_tracker.recursive_depth = int(recursive_depth)
        except (TypeError, ValueError):
            pass

        self.metrics_tracker._turn_count = max(0, turn_count)
        self.metrics_tracker._all_quotes = [str(item) for item in payload.get("all_quotes", [])]
        self.metrics_tracker._all_claims = [str(item) for item in payload.get("all_claims", [])]

        critique_pairs = []
        for pair in payload.get("critique_pairs", []):
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                critique_pairs.append((str(pair[0]), str(pair[1])))
        self.metrics_tracker._critique_pairs = critique_pairs

    def _current_citation_counts(self) -> Dict:

        return {agent.name: agent.citations_made for agent in self.team}

    def _capture_doctor_snapshot(self, include_completion_probe: bool = False) -> Dict:

        timeout_s = min(max(2.0, self.config.timeout), 10.0)

        try:
            return collect_lm_studio_diagnostics(
                self.config.base_url,
                self.config.model_name,
                api_key=self.config.api_key,
                timeout_s=timeout_s,
                include_completion_probe=include_completion_probe,
            )

        except Exception as e:
            return {
                "ok": False,
                "base_url": self.config.base_url,
                "configured_model": self.config.model_name,
                "timeout_s": timeout_s,
                "endpoint": {},
                "probe": {},
                "actions": [f"Doctor snapshot failed: {e}"],
                "error": str(e),
            }

    def _append_session_run_record(
        self,
        topic: str,
        history_log: List[str],
        turn_count: int,
        paper_list: List[str],
        status: str,
        stage: str,
        doctor_snapshot: Optional[Dict] = None,
        error: Optional[str] = None,
    ):

        try:
            resolved_turn_count = int(turn_count)

        except (TypeError, ValueError):
            resolved_turn_count = len(history_log)

        payload = {
            "version": 1,
            "kind": "rain_lab_session_run",
            "run_id": self.session_run_id,
            "started_at": self.session_started_at,
            "status": status,
            "stage": stage,
            "topic": topic,
            "turn_count": max(0, resolved_turn_count),
            "history_count": len(history_log),
            "history_tail": list(history_log[-3:]),
            "paper_count": len(paper_list),
            "resumed": self.session_resumed,
            "resume_source": self.session_resume_source,
            "model_name": self.config.model_name,
            "base_url": self.config.base_url,
            "timeout": self.config.timeout,
            "checkpoint_path": self.checkpoint_manager.path.absolute().as_posix(),
            "meeting_log_path": self.log_manager.log_path.absolute().as_posix(),
            "session_runs_path": self.session_run_ledger.path.absolute().as_posix(),
            "citation_counts": self._current_citation_counts(),
            "visual_conversation_id": self.visual_conversation_id,
        }

        if doctor_snapshot is not None:
            payload["doctor_snapshot"] = doctor_snapshot

        if error:
            payload["error"] = error

        self.session_run_ledger.append(payload)

    def _save_session_checkpoint(
        self,
        topic: str,
        history_log: List[str],
        turn_count: int,
        paper_list: List[str],
        status: str,
        doctor_snapshot: Optional[Dict] = None,
        error: Optional[str] = None,
    ):

        loaded_papers = getattr(self.context_manager, "loaded_papers", {})

        payload = {
            "version": 1,
            "kind": "rain_lab_checkpoint",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": self.session_run_id,
            "started_at": self.session_started_at,
            "status": status,
            "topic": topic,
            "turn_count": max(0, int(turn_count)),
            "history": list(history_log),
            "paper_count": len(paper_list),
            "paper_list": list(paper_list),
            "loaded_papers": sorted(loaded_papers.keys()),
            "citation_counts": self._current_citation_counts(),
            "metrics_state": self._metrics_checkpoint_state(),
            "config": {
                "model_name": self.config.model_name,
                "base_url": self.config.base_url,
                "timeout": self.config.timeout,
                "max_turns": self.config.max_turns,
                "wrap_up_turns": self.config.wrap_up_turns,
                "recursive_depth": self.config.recursive_depth,
                "recursive_intellect": self.config.recursive_intellect,
                "enable_web_search": self.config.enable_web_search,
            },
            "visual_conversation_id": self.visual_conversation_id,
            "session_runs_path": self.session_run_ledger.path.absolute().as_posix(),
            "meeting_log_path": self.log_manager.log_path.absolute().as_posix(),
            "resume_source": self.session_resume_source,
        }

        if doctor_snapshot is not None:
            payload["doctor_snapshot"] = doctor_snapshot

        if error:
            payload["error"] = error

        self.checkpoint_manager.save(payload)

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
        """Test LM Studio connection with retry"""

        print(f"\n🔌 Testing LM Studio connection...")
        print(f"{_DIM}   Base URL: {self.config.base_url}{_RST}")
        print(f"{_DIM}   Model: {self.config.model_name}{_RST}")
        print(f"{_DIM}   Timeout: {self.config.timeout:.0f}s | Retries: 3{_RST}")

        self.last_connection_diagnostics = None

        last_error = ""
        saw_timeout = False

        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model_name, messages=[{"role": "user", "content": "test"}], max_tokens=5
                )

                print("   ✓ Connection successful!\n")
                self.last_connection_diagnostics = None

                return True

            except openai.APITimeoutError:
                saw_timeout = True
                print(f"   ⏱️  Timeout (attempt {attempt + 1}/3)")

                if attempt < 2:
                    time.sleep(2)

            except Exception as e:
                last_error = str(e)
                print(f"   ✗ Connection failed: {e}")

                if attempt < 2:
                    time.sleep(2)

        diagnostics = collect_lm_studio_diagnostics(
            self.config.base_url,
            self.config.model_name,
            api_key=self.config.api_key,
            timeout_s=min(max(2.0, self.config.timeout), 10.0),
            include_completion_probe=False,
        )
        self.last_connection_diagnostics = diagnostics
        endpoint = diagnostics["endpoint"]
        print("\n💡 Diagnostics:")
        if endpoint.get("latency_ms") is not None:
            print(f"   /v1/models latency: {endpoint['latency_ms']} ms")
        loaded_models = endpoint.get("loaded_models") or []
        if loaded_models:
            print(f"   Loaded models: {', '.join(loaded_models)}")
        else:
            print("   Loaded models: none detected")
        if endpoint.get("error"):
            print(f"   Endpoint status: {endpoint['error']}")
        if saw_timeout:
            print(f"   Completion probe timed out after 3 attempts at {self.config.timeout:.0f}s.")
        elif last_error:
            print(f"   Last completion error: {last_error}")
        actions = list(diagnostics.get("actions", []))
        if saw_timeout:
            actions.insert(0, f"Increase RAIN_LM_TIMEOUT above {self.config.timeout:.0f}s if the model is slow.")
        if actions:
            print("\n🔧 Recommended actions:")
            seen = set()
            for action in actions:
                if action not in seen:
                    seen.add(action)
                    print(f"   - {action}")
        print("")

        return False

    def _animate_spinner(self, label: str, duration: float = 0.9, color: str = ""):
        """Display short terminal feedback for an active step."""

        if not sys.stdout.isatty():
            print(f"{label}...", flush=True)
            return

        if not color:
            color = _CYN

        frames = ["|", "/", "-", "\\"]

        end_time = time.time() + max(duration, 0.1)

        index = 0

        while time.time() < end_time:
            frame = frames[index % len(frames)]

            print(f"\r{color}{frame} {label}{_RST}", end="", flush=True)

            time.sleep(0.08)

            index += 1

        print(f"\r{color}OK {label}{_RST}{' ' * 18}")

    class _LiveSpinner:
        """Context manager that shows an elapsed-time spinner in a background thread."""

        def __init__(self, label: str, color: str = ""):
            self._label = label
            self._color = color or _CYN
            self._stop = threading.Event()
            self._thread: threading.Thread | None = None
            self._last_frame = ""

        def __enter__(self):
            if not sys.stdout.isatty():
                print(f"{self._label}...", flush=True)
                return self
            set_terminal_overlay(self._clear_line, self._redraw_line)
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return self

        def __exit__(self, *_exc):
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=2)
            with terminal_output_lock():
                clear_terminal_overlay()
                self._clear_line()

        def _clear_line(self):
            print(f"\r{' ' * 60}\r", end="", flush=True)

        def _redraw_line(self):
            if self._last_frame:
                print(self._last_frame, end="", flush=True)

        def _run(self):
            frames = ["|", "/", "-", "\\"]
            start = time.time()
            idx = 0
            while not self._stop.is_set():
                elapsed = time.time() - start
                frame = frames[idx % len(frames)]
                with terminal_output_lock():
                    self._last_frame = f"\r{self._color}{frame} {self._label} ({elapsed:.0f}s){_RST}   "
                    print(self._last_frame, end="", flush=True)
                idx += 1
                self._stop.wait(0.15)

    def run_meeting(
        self,
        topic: str,
        prior_history: Optional[List[str]] = None,
        resume_state: Optional[Dict] = None,
    ):
        """Run the research meeting.  If *prior_history* is provided, the
        conversation resumes with those turns already in context."""

        if resume_state and not prior_history:
            restored_history = resume_state.get("history")
            if isinstance(restored_history, list):
                prior_history = [str(item) for item in restored_history if str(item).strip()]

        self.session_run_id = f"run_{uuid.uuid4().hex[:12]}"
        self.session_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.session_resumed = bool(resume_state)
        self.session_resume_source = None
        if isinstance(resume_state, dict):
            raw_resume_source = str(resume_state.get("source", "")).strip()
            if raw_resume_source:
                self.session_resume_source = raw_resume_source
        self.last_connection_diagnostics = None

        history_log = list(prior_history or [])
        paper_list: List[str] = []
        turn_count = 0
        log_initialized = False
        session_state = {"turn_count": turn_count}

        self._append_session_run_record(topic, history_log, turn_count, paper_list, "starting", "startup")

        if sys.stdout.encoding != "utf-8":
            try:
                sys.stdout.reconfigure(encoding="utf-8")

            except Exception:
                pass

        # Header

        if _RICH_UI:
            print(meeting_header(topic))
        else:
            banner = r"""

▒▓█  V E R S 3 D Y N A M I C S   R . A . I . N .   L A B  █▓▒

░▒▓███    Recursive Architecture Intelligence Nexus    ███▓▒░

"""
            print(f"{_CYN}{banner}{_RST}")
            print(f"📋 Topic: {topic}")

        # Test connection

        if not self.test_connection():
            doctor_snapshot = self.last_connection_diagnostics or self._capture_doctor_snapshot(
                include_completion_probe=False
            )
            error_text = (
                doctor_snapshot.get("endpoint", {}).get("error")
                or doctor_snapshot.get("error")
                or "LM Studio connection test failed."
            )
            self._save_session_checkpoint(
                topic,
                history_log,
                turn_count,
                paper_list,
                "connection_failed",
                doctor_snapshot=doctor_snapshot,
                error=error_text,
            )
            self._append_session_run_record(
                topic,
                history_log,
                turn_count,
                paper_list,
                "connection_failed",
                "startup",
                doctor_snapshot=doctor_snapshot,
                error=error_text,
            )
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
                indicator = status_indicator("ok") if _RICH_UI else f"{_GRN}✓{_RST}"
                print(f"\r{_CLR}{indicator} Scanned {len(paper_list)} papers")

            else:
                indicator = status_indicator("error") if _RICH_UI else f"{_RED}✗{_RST}"
                print(f"\r{_CLR}{indicator} No papers found.")

        if not paper_list:
            print("\n❌ No papers found. Cannot proceed.")
            error_text = "No papers found in research library."
            self._save_session_checkpoint(topic, history_log, turn_count, paper_list, "no_papers", error=error_text)
            self._append_session_run_record(
                topic,
                history_log,
                turn_count,
                paper_list,
                "no_papers",
                "startup",
                error=error_text,
            )
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

        if resume_state:
            citation_counts = resume_state.get("citation_counts")
            if isinstance(citation_counts, dict):
                for agent in self.team:
                    count = citation_counts.get(agent.name, 0)
                    try:
                        agent.citations_made = max(0, int(count))
                    except (TypeError, ValueError):
                        agent.citations_made = 0
            self._restore_metrics_checkpoint_state(resume_state.get("metrics_state"))

        # Load agent souls from external files

        if verbose:
            print("\n🧠 Loading Agent Souls...")

        else:
            print("🧠 Loading agents...", end="", flush=True)

        for agent in self.team:
            agent.load_soul(self.config.library_path, verbose=verbose)

        if not verbose:
            indicator = status_indicator("ok") if _RICH_UI else f"{_GRN}✓{_RST}"
            print(f"\r{_CLR}{indicator} Agents ready")

        # Perform web search / deep research for supplementary context

        web_context = ""

        if self.web_search_manager.enabled:
            if self.config.enable_deep_research:
                # Staged multi-angle deep research
                if not verbose:
                    print("🔬 Running deep research...", end="", flush=True)

                from rain_lab_chat.deep_research import DeepResearchEngine

                engine = DeepResearchEngine(self.web_search_manager, self.config)
                brief = engine.research(
                    topic, depth=self.config.deep_research_depth
                )
                web_context = brief.summary

                if not verbose:
                    indicator = status_indicator("ok") if _RICH_UI else f"{_GRN}✓{_RST}"
                    print(
                        f"\r{_CLR}{indicator} Deep research "
                        f"({brief.query_count} queries, "
                        f"{len(brief.evidence)} evidence items)"
                    )
            else:
                # Simple single-query web search (original behavior)
                if not verbose:
                    print("🌐 Searching web...", end="", flush=True)

                web_context, results = self.web_search_manager.search(
                    topic, verbose=verbose
                )

                if not verbose:
                    count = len(results) if results else 0
                    indicator = status_indicator("ok") if _RICH_UI else f"{_GRN}✓{_RST}"
                    print(f"\r{_CLR}{indicator} Web search ({count} results)")

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
        log_initialized = True
        self._start_visual_conversation(topic)

        # Meeting setup

        effective_max_turns = max(self.config.max_turns, len(self.team))
        if effective_max_turns != self.config.max_turns:
            print(
                f"{_DIM}   Note: raised max turns to {effective_max_turns} so every agent can speak at least once.{_RST}"
            )

        discussion_turns = max(0, effective_max_turns - self.config.wrap_up_turns)
        if _RICH_UI:
            meeting_info = (
                "Press Ctrl+C at any time to intervene as founder\n"
                "Welcome to the Vers3Dynamics Chatroom\n"
                f"Meeting will wrap up after {discussion_turns} discussion turns"
            )
            print_panel("TEAM MEETING", meeting_info)
        else:
            print(f"\n🚀 TEAM MEETING")
            print(f"💡 Press Ctrl+C at any time to intervene as founder")
            print(f"💡 Welcome to the Vers3Dynamics Chatroom")
            print(f"💡 Meeting will wrap up after {discussion_turns} discussion turns\n")
            print("=" * 70 + "\n")

        kickoff_agent = next((member for member in self.team if member.name == "James"), self.team[0])

        if prior_history:
            history_log = list(prior_history)
            resume_turn_count = len(prior_history)
            if resume_state:
                try:
                    resume_turn_count = int(resume_state.get("turn_count", resume_turn_count))
                except (TypeError, ValueError):
                    resume_turn_count = len(prior_history)
            turn_count = max(0, resume_turn_count)
            print(f"{_DIM}  Resumed with {len(prior_history)} prior turns in context.{_RST}\n")
        else:
            kickoff_greeting = f"Hey team, let's talk about {topic}."
            if _RICH_UI:
                print(agent_banner(kickoff_agent.name, kickoff_agent.role))
                print(f"  {kickoff_greeting}\n")
            else:
                print(f"\n{_resolve_color(kickoff_agent.color)}{'─' * 70}")
                print(f"{kickoff_agent.name}: {kickoff_greeting}")
                print(f"{'─' * 70}{_RST}")
            self.voice_engine.speak(kickoff_greeting, agent_name=kickoff_agent.name)
            history_log = [f"{kickoff_agent.name}: {kickoff_greeting}"]

        self._save_session_checkpoint(topic, history_log, turn_count, paper_list, "running")
        self._append_session_run_record(topic, history_log, turn_count, paper_list, "running", "meeting")

        # Track wrap-up phase

        in_wrap_up = False

        # --- AUTONOMOUS LOOP WITH MANUAL INTERVENTION ---

        # Calculate when wrap-up should start

        wrap_up_start_turn = max(0, effective_max_turns - self.config.wrap_up_turns)
        session_state["turn_count"] = turn_count

        try:
            stopped_early = self._run_meeting_loop(
                effective_max_turns,
                wrap_up_start_turn,
                history_log,
                topic,
                verbose,
                in_wrap_up,
                turn_count,
                paper_list,
                session_state,
            )
        except KeyboardInterrupt:
            turn_count = int(session_state.get("turn_count", turn_count))
            doctor_snapshot = self._capture_doctor_snapshot(include_completion_probe=False)
            error_text = "Meeting interrupted by user (Ctrl+C)."
            print(f"\r{' ' * 60}\r", end="", flush=True)
            print(f"\n{_RST}{_YLW}⚠ Meeting interrupted by Ctrl+C.{_RST}")
            print(f"{_DIM}  Saving session log...{_RST}")
            if log_initialized:
                self.log_manager.log_statement("SYSTEM", error_text)
            self._save_session_checkpoint(
                topic,
                history_log,
                turn_count,
                paper_list,
                "interrupted",
                doctor_snapshot=doctor_snapshot,
                error=error_text,
            )
            if self.metrics_tracker is not None:
                self.metrics_tracker.finalize()
            if log_initialized:
                self.log_manager.finalize_log(self._generate_final_stats())
            self._append_session_run_record(
                topic,
                history_log,
                turn_count,
                paper_list,
                "interrupted",
                "meeting",
                doctor_snapshot=doctor_snapshot,
                error=error_text,
            )
            self._end_visual_conversation()
            if log_initialized:
                print(f"  ✅ Session saved to: {self.log_manager.log_path}\n")
            else:
                print(f"  ✅ Session checkpoint saved to: {self.checkpoint_manager.path}\n")
            return
        except Exception as e:
            turn_count = int(session_state.get("turn_count", turn_count))
            doctor_snapshot = self._capture_doctor_snapshot(include_completion_probe=False)
            error_text = str(e)
            if log_initialized:
                self.log_manager.log_statement("SYSTEM", f"Meeting failed: {error_text}")
            self._save_session_checkpoint(
                topic,
                history_log,
                turn_count,
                paper_list,
                "failed",
                doctor_snapshot=doctor_snapshot,
                error=error_text,
            )
            if self.metrics_tracker is not None:
                self.metrics_tracker.finalize()
            if log_initialized:
                self.log_manager.finalize_log(self._generate_final_stats())
            self._append_session_run_record(
                topic,
                history_log,
                turn_count,
                paper_list,
                "failed",
                "meeting",
                doctor_snapshot=doctor_snapshot,
                error=error_text,
            )
            self._end_visual_conversation()
            raise

        turn_count = int(session_state.get("turn_count", turn_count))
        if stopped_early:
            self._save_session_checkpoint(topic, history_log, turn_count, paper_list, "stopped")
            if self.metrics_tracker is not None:
                self.metrics_tracker.finalize()
            self.log_manager.finalize_log(self._generate_final_stats())
            self._append_session_run_record(topic, history_log, turn_count, paper_list, "stopped", "meeting")
            self._end_visual_conversation()
            print(f"\n{_GRN}✅ Session saved to: {self.log_manager.log_path}{_RST}\n")
            return

        if _RICH_UI:
            print_panel("MEETING ADJOURNED", "Great discussion today! Let's reconvene soon.")
        else:
            print("\n" + "=" * 70)
            print("👋 MEETING ADJOURNED")
            print("=" * 70)
            print(f"\n{_GRN}James: Alright team, great discussion today! Let's reconvene soon.{_RST}")

        self.log_manager.log_statement("James", "Meeting adjourned. Great discussion everyone!")

        # Finalize

        if self.metrics_tracker is not None:
            self.metrics_tracker.finalize()

        stats = self._generate_final_stats()

        self.log_manager.finalize_log(stats)
        self._save_session_checkpoint(topic, history_log, turn_count, paper_list, "completed")
        self._append_session_run_record(topic, history_log, turn_count, paper_list, "completed", "shutdown")
        self._end_visual_conversation()

        if _RICH_UI:
            print_panel("SESSION STATISTICS", stats)
        else:
            print(f"\n{_CYN}{'=' * 70}{_RST}")
            print(f"{_CYN}{stats}{_RST}")
            print(f"{_CYN}{'=' * 70}{_RST}")

        print(f"\n{_GRN}✅ Session saved to: {self.log_manager.log_path}{_RST}\n")

    def _run_meeting_loop(
        self,
        effective_max_turns: int,
        wrap_up_start_turn: int,
        history_log: List[str],
        topic: str,
        verbose: bool,
        in_wrap_up: bool,
        turn_count: int,
        paper_list: List[str],
        session_state: Dict,
    ) -> bool:
        while turn_count < effective_max_turns:
            external_message = self.diplomat.check_inbox()

            if external_message:
                print(f"\n{_YLW}{external_message}{_RST}")

                history_log.append(external_message)
                self._save_session_checkpoint(topic, history_log, turn_count, paper_list, "running")

            if not in_wrap_up and turn_count >= wrap_up_start_turn:
                in_wrap_up = True

                print("\n" + "=" * 70)

                print("📋 MEETING WRAP-UP PHASE")

                print("=" * 70 + "\n")

            current_agent = self.team[turn_count % len(self.team)]

            user_wants_to_speak = False

            if _RICH_UI:
                print_progress(turn_count, effective_max_turns, prefix="Meeting")
                print(agent_banner(current_agent.name, current_agent.role))
            else:
                print(f"\n{_resolve_color(current_agent.color)}▶ {current_agent.name}'s turn ({current_agent.role}){_RST}")

            print(f"{_DIM}   [Press ENTER to speak, or wait...]{_RST}", end="", flush=True)

            intervention_window = 0.0 if turn_count == 0 else 2.5

            start_time = time.time()

            while time.time() - start_time < intervention_window:
                if msvcrt and msvcrt.kbhit():
                    key = msvcrt.getch()

                    user_wants_to_speak = True

                    break

                elif sys.platform != "win32":
                    try:
                        r, _, _ = select.select([sys.stdin], [], [], 0)

                        if r:
                            sys.stdin.readline()

                            user_wants_to_speak = True

                            break

                    except Exception:
                        pass

                time.sleep(0.05)

            print("\r" + " " * 50 + "\r", end="")

            if user_wants_to_speak:
                print(f"\n{_WHT}🎤 FOUNDER INTERVENTION (type 'done' to resume, 'quit' to end):{_RST}")

                while True:
                    try:
                        user_input = input("🎤 FOUNDER: ").strip()

                        if user_input.lower() in ["done", "continue", "resume", ""]:
                            print(f"\n{_DIM}▶ Resuming automatic discussion...{_RST}\n")

                            break

                        elif user_input.lower() in ["quit", "exit", "stop"]:
                            print("\n👋 Meeting ended by FOUNDER.")
                            session_state["turn_count"] = turn_count
                            return True

                        else:
                            print(f"\n{_WHT}💬 [FOUNDER]: {user_input}{_RST}\n")

                            self.log_manager.log_statement("FOUNDER", user_input)

                            history_log.append(f"FOUNDER: {user_input}")
                            self._save_session_checkpoint(topic, history_log, turn_count, paper_list, "running")

                    except (EOFError, KeyboardInterrupt):
                        print(f"\n{_DIM}▶ Resuming automatic discussion...{_RST}\n")

                        break

            response, metadata = self._generate_agent_response(
                current_agent, self.full_context, history_log, turn_count, topic, is_wrap_up=in_wrap_up
            )

            if response is None:
                print("Model timeout detected; using an agent-specific fallback so discussion can continue.")
                response = self._timeout_fallback_response(
                    current_agent,
                    topic,
                    history_log,
                    turn_count,
                )
                metadata = {"timeout_fallback": True}

            if self.config.enable_citation_tracking:
                citation_analysis = self.citation_analyzer.analyze_response(current_agent.name, response)

                metadata = citation_analysis

                current_agent.citations_made += len(citation_analysis["verified"])

            clean_response = self._strip_agent_prefix(response, current_agent.name)

            if _RICH_UI:
                agent_color_name = AGENT_COLORS.get(current_agent.name, "white")
                print(f"\n  {color(current_agent.name + ':', agent_color_name)} {clean_response}\n")
            else:
                print(f"\n{_resolve_color(current_agent.color)}{'─' * 70}")
                print(f"{current_agent.name}: {clean_response}")
                print(f"{'─' * 70}{_RST}")

            spoken_text = clean_response
            if self.config.emit_visual_events:
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

            self.voice_engine.speak(
                spoken_text,
                agent_name=current_agent.name,
            )

            search_match = RE_WEB_SEARCH_COMMAND.search(clean_response)

            if search_match:
                query = search_match.group(1).strip()

                if query:
                    print(f"{_BLU}🌐 Active Web Search requested: {query}{_RST}")

                    web_note, web_results = self.web_search_manager.search(query, verbose=verbose)

                    if web_note:
                        print(f"{_BLU}📎 Web Search Result:{_RST}")

                        print(web_note)

                        history_log.append(f"SYSTEM: Web search for '{query}'\n{web_note}")

                    else:
                        no_result_note = f"No web results returned for query: {query}"

                        print(f"{_BLU}📎 Web Search Result: {no_result_note}{_RST}")

                        history_log.append(f"SYSTEM: {no_result_note}")

                    if web_results:
                        self.full_context += f"\n\n### LIVE WEB SEARCH\nQuery: {query}\n{web_note}"

            if metadata and metadata.get("verified"):
                if _RICH_UI:
                    print(f"  {status_indicator('ok')} {len(metadata['verified'])} citation(s) verified")
                else:
                    print(f"{_DIM}   ✓ {len(metadata['verified'])} citation(s) verified{_RST}")

                for quote, source in metadata["verified"][:1]:
                    print(f'{_DIM}      • "{quote[:60]}..." [from {source}]{_RST}')

            self.log_manager.log_statement(current_agent.name, response, metadata)

            history_log.append(f"{current_agent.name}: {response}")

            if self.metrics_tracker is not None:
                self.metrics_tracker.record_turn(current_agent.name, response, metadata)

            turn_count += 1
            session_state["turn_count"] = turn_count
            self._save_session_checkpoint(topic, history_log, turn_count, paper_list, "running")

        session_state["turn_count"] = turn_count
        return False

    def _generate_agent_response(
        self,
        agent: Agent,
        context_block: str,
        history_log: List[str],
        turn_count: int,
        topic: str,
        is_wrap_up: bool = False,
    ) -> Tuple[Optional[str], Optional[Dict]]:
        recent_chat = "\n".join(history_log[-self.config.recent_history_window :]) if history_log else "[Meeting Start]"

        if is_wrap_up:
            mission = get_wrap_up_instruction(agent, topic)
        else:
            mission = self.director.get_dynamic_instruction(agent, turn_count, topic)

        prev_speaker = None
        if history_log:
            last_entry = history_log[-1]
            if ":" in last_entry:
                prev_speaker = last_entry.split(":")[0].strip()

        graph_findings = None
        if agent.name == "Luca":
            graph_findings = self.hypergraph_manager.query(topic=topic)

        user_msg = build_user_message(agent, recent_chat, mission, prev_speaker, graph_findings)
        system_msg = f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}"

        for attempt in range(self.config.max_retries):
            with self._LiveSpinner(f"{agent.name} is thinking", color=_resolve_color(agent.color)):
                content, finish_reason = call_llm_with_retry(
                    self.client,
                    self.config,
                    system_msg,
                    user_msg,
                    max_retries=1,
                    log_failures=False,
                )
            if content is None:
                if attempt < self.config.max_retries - 1:
                    if _RICH_UI:
                        print(f"  {status_indicator('warning')} {agent.name} timed out — retrying...")
                    else:
                        print(f"{_YLW}⚠ {agent.name} timed out — retrying...{_RST}")
                    continue
                return None, None

            if turn_count >= 1 and agent.name == "James":
                content = fix_repeated_intro(
                    self.client,
                    self.config,
                    agent,
                    content,
                    context_block,
                )

            content = refine_response(
                self.client,
                self.config,
                agent,
                content,
                context_block,
                metrics_tracker=self.metrics_tracker,
            )

            from rain_lab_chat.guardrails import clean_identity

            content = clean_identity(content, agent.name)

            content = handle_truncation(
                self.client,
                self.config,
                agent,
                content,
                finish_reason,
            )

            corrupted, reason = is_corrupted_response(content)
            if corrupted:
                print(f"\n⚠️  Corrupted response detected ({reason})")
                if attempt < self.config.max_retries - 1:
                    print("   Regenerating...")
                    import time as _t

                    _t.sleep(1)
                    continue
                else:
                    print("   Falling back to placeholder response.")
                    content = f"[{agent.name} is processing... Let me gather my thoughts on this topic.]"

            print("✓")
            return content, {}

        return None, None

    def _timeout_fallback_response(
        self,
        agent: Agent,
        topic: str,
        history_log: List[str],
        turn_count: int,
    ) -> str:
        """Generate distinct team-style fallback text when the model times out."""
        previous_speaker = None
        if history_log:
            last_entry = history_log[-1]
            if ":" in last_entry:
                previous_speaker = last_entry.split(":", 1)[0].strip()

        handoff = ""
        if previous_speaker and previous_speaker not in {agent.name, "FOUNDER", "SYSTEM"}:
            handoff = f"{previous_speaker}, building on your point: "

        by_agent = {
            "James": (
                "from the papers, time is framed as dynamic location rather than a fixed line. "
                "Let's compare one claim from 'Temporal Re-Localization via Scalar Resonance' "
                "with one from 'Location is a Dynamic Variable', then isolate the first falsifiable test."
            ),
            "Jasmine": (
                "before expanding theory, I need feasibility bounds: energy budget, materials, and "
                "instrument tolerances. If those are missing from the papers, we should label this "
                "pre-prototype and define a minimal bench test first."
            ),
            "Luca": (
                "I read this as a field-geometry question: if time is re-localization, we need a stable "
                "topology for transitions. Let's map resonance nodes and gradients, then choose the geometry "
                "that keeps coherence intact."
            ),
            "Elena": (
                f"I want hard bounds around '{topic}': entropy cost, computational complexity, and stability limits. "
                "If the papers cannot quantify those, we should separate what is formally supported from what is speculative."
            ),
        }
        default_text = f"for '{topic}', let's extract one concrete, testable claim from each relevant paper before we add new assumptions."
        body = by_agent.get(agent.name, default_text)
        return f"{handoff}{body}"

    def _generate_final_stats(self) -> str:
        """Generate final statistics."""
        stats_lines = ["SESSION STATISTICS", "\u2500" * 70]

        if self.citation_analyzer:
            stats_lines.append(self.citation_analyzer.get_stats())
            stats_lines.append("")

        stats_lines.append("AGENT PERFORMANCE:")
        for agent in self.team:
            stats_lines.append(f"  \u2022 {agent.name}: {agent.citations_made} verified citations")

        if self.metrics_tracker is not None:
            m = self.metrics_tracker.summary()
            stats_lines.append("")
            stats_lines.append("EVAL METRICS:")
            stats_lines.append(f"  \u2022 Citation accuracy:    {m['citation_accuracy']:.2f}")
            stats_lines.append(f"  \u2022 Novel-claim density:  {m['novel_claim_density']:.2f}")
            stats_lines.append(f"  \u2022 Critique change rate: {m['critique_change_rate']:.2f}")

        return "\n".join(stats_lines)

    def _strip_agent_prefix(self, response: str, agent_name: str) -> str:
        """Delegate to guardrails.strip_agent_prefix."""
        return strip_agent_prefix(response, agent_name)


# --- CLI INTERFACE ---
