"""Main meeting orchestrator with citation tracking and error handling."""

import glob
import os
import sys
import time
import uuid
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

import openai

try:
    from rain_metrics import MetricsTracker
except ImportError:
    MetricsTracker = None

from graph_bridge import HypergraphManager
from rain_lab_chat._sanitize import RE_WEB_SEARCH_COMMAND
from rain_lab_chat.agents import Agent, RainLabAgentFactory
from rain_lab_chat.citations import CitationAnalyzer
from rain_lab_chat.config import Config
from rain_lab_chat.context import ContextManager
from rain_lab_chat.director import RainLabDirector
from rain_lab_chat.guardrails import (
    is_corrupted_response,
    strip_agent_prefix,
)
from rain_lab_chat.logging_events import Diplomat, LogManager, VisualEventLogger
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

        self.visual_event_logger = VisualEventLogger(config)
        self.visual_conversation_id: Optional[str] = None
        self.visual_conversation_active = False
        self.tts_audio_dir = Path(config.library_path) / config.tts_audio_dir
        if self.config.export_tts_audio:
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

            self.client = openai.OpenAI(

                base_url=config.base_url, 

                api_key=config.api_key,

                timeout=custom_timeout

            )

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

        print(f"\n🔌 Testing connection to blacksite at {self.config.base_url}...")

        for attempt in range(3):

            try:

                response = self.client.chat.completions.create(

                    model=self.config.model_name,

                    messages=[{"role": "user", "content": "test"}],

                    max_tokens=5

                )

                print("   ✓ Connection successful!\n")

                return True

            except openai.APITimeoutError:

                print(f"   ⏱️  Timeout (attempt {attempt+1}/3)")

                if attempt < 2:

                    time.sleep(2)

            except Exception as e:

                print(f"   ✗ Connection failed: {e}")

                if attempt == 2:

                    print("\n💡 Troubleshooting:")

                    print("   1. Is LM Studio running?")

                    print("   2. Is the server started? (green 'Server Running' button)")

                    print(f"   3. Is model '{self.config.model_name}' loaded?")

                    print(f"   4. Is it listening on {self.config.base_url}?")

                    print("   5. Try clicking 'Reload Model' in LM Studio\n")

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

        if sys.stdout.encoding != 'utf-8':

            try:

                sys.stdout.reconfigure(encoding='utf-8')

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

        print("="*70 + "\n")

        # Track wrap-up phase

        in_wrap_up = False

        wrap_up_complete = False

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

                print("\n" + "="*70)

                print("📋 MEETING WRAP-UP PHASE")

                print("="*70 + "\n")

            current_agent = self.team[turn_count % len(self.team)]

            # Check for user intervention with Windows-compatible key detection

            user_wants_to_speak = False

            print(f"\n{current_agent.color}▶ {current_agent.name}'s turn ({current_agent.role})\033[0m")

            print("\033[90m   [Press ENTER to speak, or wait...]\033[0m", end='', flush=True)

            # Cross-platform: check for keypress during brief window

            intervention_window = 1.5  # seconds to wait for user input

            start_time = time.time()

            while time.time() - start_time < intervention_window:

                if msvcrt and msvcrt.kbhit():  # Windows

                    key = msvcrt.getch()

                    user_wants_to_speak = True

                    break

                elif sys.platform != 'win32':  # Unix/Linux/Mac

                    try:

                        r, _, _ = select.select([sys.stdin], [], [], 0)

                        if r:

                            sys.stdin.readline()

                            user_wants_to_speak = True

                            break

                    except Exception:

                        pass

                time.sleep(0.05)  # Small sleep to prevent CPU spinning

            print("\r" + " " * 50 + "\r", end='')  # Clear the "Press ENTER" prompt

            # Handle user intervention

            if user_wants_to_speak:

                print(f"\n\033[97m🎤 FOUNDER INTERVENTION (type 'done' to resume, 'quit' to end):\033[0m")

                while True:

                    try:

                        user_input = input("🎤 FOUNDER: ").strip()

                        if user_input.lower() in ['done', 'continue', 'resume', '']:

                            print("\n\033[90m▶ Resuming automatic discussion...\033[0m\n")

                            break

                        elif user_input.lower() in ['quit', 'exit', 'stop']:

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

                current_agent, 

                self.full_context, 

                history_log, 

                turn_count, 

                topic,

                is_wrap_up=in_wrap_up

            )

            if response is None:

                print("❌ Failed to generate response after retries. Ending meeting.")

                break

            # 3. Analyze Citations

            if self.config.enable_citation_tracking:

                citation_analysis = self.citation_analyzer.analyze_response(

                    current_agent.name, 

                    response

                )

                metadata = citation_analysis

                current_agent.citations_made += len(citation_analysis['verified'])

            # 4. Output - Clean up any duplicate name prefixes from the response

            clean_response = self._strip_agent_prefix(response, current_agent.name)

            print(f"\n{current_agent.color}{'─'*70}")

            print(f"{current_agent.name}: {clean_response}")

            print(f"{'─'*70}\033[0m")

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

            if metadata and metadata.get('verified'):

                print(f"\033[90m   ✓ {len(metadata['verified'])} citation(s) verified\033[0m")

                for quote, source in metadata['verified'][:1]:  # Show first citation

                    print(f"\033[90m      • \"{quote[:60]}...\" [from {source}]\033[0m")

            # 5. Log

            self.log_manager.log_statement(current_agent.name, response, metadata)

            history_log.append(f"{current_agent.name}: {response}")

            # 6. Record eval metrics for this turn

            if self.metrics_tracker is not None:

                self.metrics_tracker.record_turn(

                    current_agent.name, response, metadata

                )

            turn_count += 1

        # Meeting officially closed

        print("\n" + "="*70)

        print("👋 MEETING ADJOURNED")

        print("="*70)

        print("\n\033[92mJames: Alright team, great discussion today! Let's reconvene soon.\033[0m")

        self.log_manager.log_statement("James", "Meeting adjourned. Great discussion everyone!")

        # Finalize

        if self.metrics_tracker is not None:

            self.metrics_tracker.finalize()

        stats = self._generate_final_stats()

        self.log_manager.finalize_log(stats)
        self._end_visual_conversation()

        print("\n" + "="*70)

        print(stats)

        print("="*70)

        print(f"\n✅ Session saved to: {self.log_manager.log_path}\n")

    def _generate_agent_response(
        self,
        agent: Agent,
        context_block: str,
        history_log: List[str],
        turn_count: int,
        topic: str,
        is_wrap_up: bool = False,
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Generate agent response: build prompt, call LLM, refine, validate."""
        recent_chat = "\n".join(history_log[-self.config.recent_history_window:]) if history_log else "[Meeting Start]"

        # Choose mission
        if is_wrap_up:
            mission = get_wrap_up_instruction(agent, topic)
        else:
            mission = self.director.get_dynamic_instruction(agent, turn_count, topic)

        # Determine previous speaker
        prev_speaker = None
        if history_log:
            last_entry = history_log[-1]
            if ":" in last_entry:
                prev_speaker = last_entry.split(":")[0].strip()

        # Build messages
        graph_findings = None
        if agent.name == "Luca":
            graph_findings = self.hypergraph_manager.query(topic=topic)

        user_msg = build_user_message(agent, recent_chat, mission, prev_speaker, graph_findings)
        system_msg = f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}"

        self._animate_spinner(f"{agent.name} analyzing", duration=1.0, color=agent.color)

        # Call LLM with retry
        for attempt in range(self.config.max_retries):
            content, finish_reason = call_llm_with_retry(
                self.client, self.config, system_msg, user_msg, max_retries=1,
            )
            if content is None:
                if attempt < self.config.max_retries - 1:
                    continue
                return None, None

            # Guardrail: fix repeated intro on later James turns
            if turn_count >= 1 and agent.name == "James":
                content = fix_repeated_intro(
                    self.client, self.config, agent, content, context_block,
                )

            # Recursive self-reflection
            content = refine_response(
                self.client, self.config, agent, content, context_block,
                metrics_tracker=self.metrics_tracker,
            )

            # Identity cleanup
            from rain_lab_chat.guardrails import clean_identity
            content = clean_identity(content, agent.name)

            # Handle truncation
            content = handle_truncation(
                self.client, self.config, agent, content, finish_reason,
            )

            # Corruption check
            corrupted, reason = is_corrupted_response(content)
            if corrupted:
                print(f"\n\u26a0\ufe0f  Corrupted response detected ({reason})")
                if attempt < self.config.max_retries - 1:
                    print("   Regenerating...")
                    import time as _t
                    _t.sleep(1)
                    continue
                else:
                    print("   Falling back to placeholder response.")
                    content = f"[{agent.name} is processing... Let me gather my thoughts on this topic.]"

            print("\u2713")
            return content, {}

        return None, None

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
# --- CLI INTERFACE ---
