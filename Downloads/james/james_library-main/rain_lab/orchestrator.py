"""Main orchestrator — runs the research meeting loop."""

from __future__ import annotations

import glob
import os
import re
import select
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from graph_bridge import HypergraphManager
from hypothesis_tree import HypothesisTree, NodeStatus
from stagnation_monitor import StagnationMonitor

from .agents import Agent, RainLabAgentFactory
from .citations import CitationAnalyzer
from .config import (
    Config,
    PRIMARY_RESPONSE_SENTENCE_TARGET,
    PRIMARY_RESPONSE_WORD_TARGET,
    REPAIR_RESPONSE_SENTENCE_TARGET,
    meeting_response_length_guidance,
    no_self_name_intro_guidance,
    wrap_up_response_length_guidance,
)
from .context import ContextManager
from .diplomat import Diplomat
from .director import RainLabDirector
from .log_manager import LogManager
from .resonance import ResonanceDetector
from .rust_daemon import RustDaemonClient
from .sanitize import RE_CORRUPTION_CAPS, RE_CORRUPTION_PATTERNS, RE_WEB_SEARCH_COMMAND, sanitize_text
from .visual_events import VisualEventServer
from .voice import VoiceEngine
from .web_search import WebSearchManager, DDG_AVAILABLE

try:
    import msvcrt
except ImportError:
    msvcrt = None

# Lazy openai import — only needed when not using rust daemon
openai = None


def _ensure_openai():
    global openai
    if openai is None:
        import openai as _openai
        openai = _openai


# Optional eval metrics
try:
    from rain_metrics import MetricsTracker
except ImportError:
    MetricsTracker = None


class RainLabOrchestrator:
    """Main orchestrator with enhanced citation tracking and error handling."""

    def __init__(self, config: Config):
        self.config = config
        self.team = RainLabAgentFactory.create_team()
        self.context_manager = ContextManager(config)
        self.log_manager = LogManager(config)
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
        self.metrics_tracker = None

        if self.config.use_rust_daemon:
            try:
                self.rust_daemon_client = RustDaemonClient(
                    base_url=self.config.rust_daemon_api_url,
                    timeout_s=self.config.rust_daemon_timeout,
                )
                self.client = None
                print(f"\U0001f980 Rust daemon mode enabled: {self.config.rust_daemon_api_url}")
            except Exception as e:
                print(f"\u274c Failed to initialize Rust daemon client: {e}")
                sys.exit(1)
        else:
            _ensure_openai()
            try:
                import httpx

                connect_timeout = min(15.0, self.config.timeout)
                custom_timeout = httpx.Timeout(
                    connect_timeout,
                    read=self.config.timeout,
                    write=connect_timeout,
                    connect=connect_timeout,
                )
                self.client = openai.OpenAI(
                    base_url=config.base_url, api_key=config.api_key, timeout=custom_timeout
                )
            except Exception as e:
                print(f"\u274c Failed to initialize OpenAI client: {e}")
                sys.exit(1)

    # -- Visual event helpers --

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

    # -- Meeting archive --

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
            print(f"\u26a0\ufe0f  Failed to load meeting archive '{newest_file}': {e}")
            return ""

    # -- Connection test --

    def test_connection(self) -> bool:
        """Test LLM provider connection with retry."""
        print(f"\n\U0001f50c Testing connection to LLM provider at {self.config.base_url}...")
        for attempt in range(3):
            try:
                self.client.chat.completions.create(
                    model=self.config.model_name, messages=[{"role": "user", "content": "test"}], max_tokens=5
                )
                print("   \u2713 Connection successful!\n")
                return True
            except openai.APITimeoutError:
                print(f"   \u23f1\ufe0f  Timeout (attempt {attempt + 1}/3)")
                if attempt < 2:
                    time.sleep(2)
            except Exception as e:
                print(f"   \u2717 Connection failed: {e}")
                if attempt == 2:
                    print("\n\U0001f4a1 Troubleshooting:")
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
        frames = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"]
        end_time = time.time() + max(duration, 0.1)
        index = 0
        while time.time() < end_time:
            frame = frames[index % len(frames)]
            print(f"\r{color}{frame} {label}\033[0m", end="", flush=True)
            time.sleep(0.08)
            index += 1
        print(f"\r{color}\u2713 {label}\033[0m{' ' * 18}")

    # -- Main meeting loop --

    def run_meeting(self, topic: str):
        """Run the research meeting."""

        if sys.stdout.encoding != "utf-8":
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

        banner = r"""


\u2592\u2593\u2588  V E R S 3 D Y N A M I C S   R . A . I . N .   L A B  \u2588\u2593\u2592

\u2591\u2592\u2593\u2588\u2588\u2588    Recursive Architecture Intelligence Nexus    \u2588\u2588\u2588\u2593\u2592\u2591

"""

        print(f"\033[96m{banner}\033[0m")
        print(f"\U0001f4cb Topic: {topic}")

        if not self.test_connection():
            return

        verbose = self.config.verbose

        if verbose:
            print("\U0001f50d Scanning for Research Papers...")
        else:
            print("\U0001f50d Scanning research library...", end="", flush=True)

        context_block, paper_list = self.context_manager.get_library_context(verbose=verbose)

        if not verbose:
            if paper_list:
                print(f"\r\033[K\033[92m\u2713\033[0m Scanned {len(paper_list)} papers")
            else:
                print(f"\r\033[K\033[91m\u2717\033[0m No papers found.")

        if not paper_list:
            print("\n\u274c No papers found. Cannot proceed.")
            return

        self.director = RainLabDirector(self.config, paper_list)
        self.citation_analyzer = CitationAnalyzer(self.context_manager)

        self.metrics_tracker = None
        if MetricsTracker is not None:
            self.metrics_tracker = MetricsTracker(
                session_id=str(uuid.uuid4())[:8],
                topic=topic,
                model=self.config.model_name,
                recursive_depth=self.config.recursive_depth,
            )
            self.metrics_tracker.set_corpus(self.context_manager.loaded_papers)

        if verbose:
            print("\n\U0001f9e0 Loading Agent Souls...")
        else:
            print("\U0001f9e0 Loading agents...", end="", flush=True)

        for agent in self.team:
            agent.load_soul(self.config.library_path, verbose=verbose)

        if not verbose:
            print(f"\r\033[K\033[92m\u2713\033[0m Agents ready")

        web_context = ""
        if self.web_search_manager.enabled:
            if not verbose:
                print("\U0001f310 Searching web...", end="", flush=True)
            web_context, results = self.web_search_manager.search(topic, verbose=verbose)
            if not verbose:
                count = len(results) if results else 0
                print(f"\r\033[K\033[92m\u2713\033[0m Web search ({count} results)")
        elif self.config.enable_web_search and not DDG_AVAILABLE and verbose:
            print("\n\u26a0\ufe0f  Web search disabled: duckduckgo-search not installed")
            print("   Install with: pip install duckduckgo-search\n")

        full_context = context_block
        if web_context:
            full_context = context_block + "\n\n" + web_context
        self.full_context = full_context

        previous_meeting_summary = self.get_last_meeting_summary()
        if previous_meeting_summary:
            self.full_context += "\n### PREVIOUS MEETING CONTEXT\n" + previous_meeting_summary

        self.log_manager.initialize_log(topic, len(paper_list))
        self._start_visual_conversation(topic)

        history_log: List[str] = []
        turn_count = 0

        print(f"\n\U0001f680 TEAM MEETING")
        print(f"\U0001f4a1 Press Ctrl+C at any time to intervene as founder")
        print(f"\U0001f4a1 Welcome to the Vers3Dynamics Chatroom")
        print(f"\U0001f4a1 Meeting will wrap up after {self.config.max_turns - self.config.wrap_up_turns} discussion turns\n")
        print("=" * 70 + "\n")

        in_wrap_up = False
        wrap_up_complete = False
        root_id = self.hypothesis_tree.add_root(topic)
        self._current_hypothesis_id = self.hypothesis_tree.select()
        wrap_up_start_turn = self.config.max_turns - self.config.wrap_up_turns

        while turn_count < self.config.max_turns:
            external_message = self.diplomat.check_inbox()
            if external_message:
                print(f"\n\033[93m{external_message}\033[0m")
                history_log.append(external_message)

            if not in_wrap_up and turn_count >= wrap_up_start_turn:
                in_wrap_up = True
                print("\n" + "=" * 70)
                print("\U0001f4cb MEETING WRAP-UP PHASE")
                print("=" * 70 + "\n")

            current_agent = self.team[turn_count % len(self.team)]

            # User intervention window
            user_wants_to_speak = False
            print(f"\n{current_agent.color}\u25b6 {current_agent.name}'s turn ({current_agent.role})\033[0m")
            print("\033[90m   [Press ENTER to speak, or wait...]\033[0m", end="", flush=True)

            intervention_window = 1.5
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
                print(f"\n\033[97m\U0001f3a4 FOUNDER INTERVENTION (type 'done' to resume, 'quit' to end):\033[0m")
                while True:
                    try:
                        user_input = input("\U0001f3a4 FOUNDER: ").strip()
                        if user_input.lower() in ["done", "continue", "resume", ""]:
                            print("\n\033[90m\u25b6 Resuming automatic discussion...\033[0m\n")
                            break
                        elif user_input.lower() in ["quit", "exit", "stop"]:
                            print("\n\U0001f44b Meeting ended by FOUNDER.")
                            if self.metrics_tracker is not None:
                                self.metrics_tracker.finalize()
                            self.log_manager.finalize_log(self._generate_final_stats())
                            self._end_visual_conversation()
                            return
                        else:
                            print(f"\n\033[97m\U0001f4ac [FOUNDER]: {user_input}\033[0m\n")
                            self.log_manager.log_statement("FOUNDER", user_input)
                            history_log.append(f"FOUNDER: {user_input}")
                    except (EOFError, KeyboardInterrupt):
                        print("\n\033[90m\u25b6 Resuming automatic discussion...\033[0m\n")
                        break

            response, metadata = self._generate_agent_response(
                current_agent, self.full_context, history_log, turn_count, topic, is_wrap_up=in_wrap_up
            )

            if response is None:
                print("\u274c Failed to generate response after retries. Ending meeting.")
                break

            if self.config.enable_citation_tracking:
                citation_analysis = self.citation_analyzer.analyze_response(current_agent.name, response)
                metadata = citation_analysis
                current_agent.citations_made += len(citation_analysis["verified"])

            self._update_hypothesis_after_turn(response, metadata)

            clean_response = self._strip_agent_prefix(response, current_agent.name)

            print(f"\n{current_agent.color}{'-' * 70}")
            print(f"{current_agent.name}: {clean_response}")
            print(f"{'-' * 70}\033[0m")

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

            resonance = self.resonance_detector.analyze(clean_response)
            if resonance is not None:
                self._emit_visual_event(
                    {
                        "type": "resonance_state",
                        "conversation_id": self.visual_conversation_id or "",
                        **resonance,
                    }
                )

            self.voice_engine.speak(spoken_text, agent_name=current_agent.name)

            search_match = RE_WEB_SEARCH_COMMAND.search(clean_response)
            if search_match:
                query = search_match.group(1).strip()
                if query:
                    print(f"\033[94m\U0001f310 Active Web Search requested: {query}\033[0m")
                    web_note, web_results = self.web_search_manager.search(query, verbose=verbose)
                    if web_note:
                        print("\033[94m\U0001f4ce Web Search Result:\033[0m")
                        print(web_note)
                        history_log.append(f"SYSTEM: Web search for '{query}'\n{web_note}")
                    else:
                        no_result_note = f"No web results returned for query: {query}"
                        print(f"\033[94m\U0001f4ce Web Search Result: {no_result_note}\033[0m")
                        history_log.append(f"SYSTEM: {no_result_note}")
                    if web_results:
                        self.full_context += f"\n\n### LIVE WEB SEARCH\nQuery: {query}\n{web_note}"

            if metadata and metadata.get("verified"):
                print(f"\033[90m   \u2713 {len(metadata['verified'])} citation(s) verified\033[0m")
                for quote, source in metadata["verified"][:1]:
                    print(f'\033[90m      \u2022 "{quote[:60]}..." [from {source}]\033[0m')

            self.log_manager.log_statement(current_agent.name, response, metadata)
            history_log.append(f"{current_agent.name}: {response}")

            verdict = self.stagnation_monitor.check(response)
            if verdict.intervention_prompt:
                history_log.append(f"SYSTEM: {verdict.intervention_prompt}")
                self.log_manager.log_statement("SYSTEM", verdict.intervention_prompt)
                print(f"\n\033[91m{'=' * 70}")
                print(f"  {verdict.intervention_prompt}")
                print(f"{'=' * 70}\033[0m\n")

            if self.metrics_tracker is not None:
                self.metrics_tracker.record_turn(current_agent.name, response, metadata)

            turn_count += 1

        # Meeting closed
        print("\n" + "=" * 70)
        print("\U0001f44b MEETING ADJOURNED")
        print("=" * 70)
        print("\n\033[92mJames: Alright team, great discussion today! Let's reconvene soon.\033[0m")
        self.log_manager.log_statement("James", "Meeting adjourned. Great discussion everyone!")

        if self.metrics_tracker is not None:
            self.metrics_tracker.finalize()

        stats = self._generate_final_stats()
        self.log_manager.finalize_log(stats)
        self._end_visual_conversation()

        print("\n" + "=" * 70)
        print(stats)
        print("=" * 70)
        print(f"\n\u2705 Session saved to: {self.log_manager.log_path}\n")

    # -- Daemon event polling --

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

    # -- Response creation --

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

    # -- Hypothesis tree --

    def _get_hypothesis_context(self) -> str:
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
        if self._current_hypothesis_id is None:
            return
        try:
            node = self.hypothesis_tree.get(self._current_hypothesis_id)
        except KeyError:
            return
        if node.status != NodeStatus.ACTIVE:
            return

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
        try:
            self._current_hypothesis_id = self.hypothesis_tree.select()
            node = self.hypothesis_tree.get(self._current_hypothesis_id)
            print(f"\033[96m  [HYPOTHESIS SELECTED] #{node.node_id}: {node.hypothesis}\033[0m")
        except ValueError:
            self._current_hypothesis_id = None
            print("\033[93m  [HYPOTHESIS TREE EXHAUSTED] All branches explored.\033[0m")

    # -- Agent response generation --

    def _generate_agent_response(
        self,
        agent: Agent,
        context_block: str,
        history_log: List[str],
        turn_count: int,
        topic: str,
        is_wrap_up: bool = False,
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Generate agent response with robust error handling and retries."""

        recent_chat = "\n".join(history_log[-self.config.recent_history_window :]) if history_log else "[Meeting Start]"

        if is_wrap_up:
            mission = self._get_wrap_up_instruction(agent, topic)
        else:
            mission = self.director.get_dynamic_instruction(agent, turn_count, topic)

        prev_speaker = None
        if history_log:
            last_entry = history_log[-1]
            if ":" in last_entry:
                prev_speaker = last_entry.split(":")[0].strip()

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

        for attempt in range(self.config.max_retries):
            try:
                if prev_speaker and prev_speaker != agent.name and prev_speaker != "FOUNDER":
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
                content, finish_reason = self._create_response_content(
                    agent=agent,
                    topic=topic,
                    context_block=context_block,
                    recent_chat=recent_chat,
                    mission=mission,
                    user_msg=user_msg,
                )

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

                if self.config.recursive_intellect and self.config.recursive_depth > 0 and content:
                    for _ in range(self.config.recursive_depth):
                        pre_critique_text = content

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

                        if self.metrics_tracker is not None:
                            self.metrics_tracker.record_critique(pre_critique_text, content)

                if content.startswith(f"{agent.name}:"):
                    content = content.replace(f"{agent.name}:", "", 1).strip()

                other_agents = ["James", "Jasmine", "Luca", "Elena"]
                cleaned_lines = []
                for line in content.split("\n"):
                    is_other_agent_line = False
                    for other in other_agents:
                        if other != agent.name and line.strip().startswith(f"{other}:"):
                            is_other_agent_line = True
                            break
                    if not is_other_agent_line:
                        cleaned_lines.append(line)
                content = "\n".join(cleaned_lines).strip()

                is_truncated = self._looks_truncated_response(content, finish_reason)
                if is_truncated:
                    print("(completing...)", end=" ", flush=True)
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
                            max_tokens=60,
                        )
                        cont_text = continuation.choices[0].message.content.strip()
                        if cont_text and not cont_text.startswith(content[:20]):
                            if not cont_text[0].isupper():
                                content = content + " " + cont_text
                            else:
                                for end in [". ", "! ", "? "]:
                                    if end in content:
                                        last_end = content.rfind(end)
                                        if last_end > len(content) * 0.5:
                                            content = content[: last_end + 1]
                                            break
                                else:
                                    content = content.rstrip(",;:") + "..."
                    except Exception:
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
                    print(f"\n\u26a0\ufe0f  Corrupted response detected ({corruption_reason})")
                    if attempt < self.config.max_retries - 1:
                        print("   Regenerating...")
                        time.sleep(1)
                        continue
                    else:
                        print("   Falling back to placeholder response.")
                        content = f"[{agent.name} is processing... Let me gather my thoughts on this topic.]"

                print("\u2713")
                return content, {}

            except openai.APITimeoutError:
                print(f"\n\u23f1\ufe0f  Timeout (attempt {attempt + 1}/{self.config.max_retries})")
                if attempt < self.config.max_retries - 1:
                    print("   Retrying in 2 seconds...")
                    time.sleep(2)
                else:
                    print("\n\U0001f4a1 The model might be overloaded. Try:")
                    print("   1. Reducing max_tokens in Config")
                    print("   2. Checking LM Studio's server logs")
                    return None, None

            except openai.APIConnectionError:
                print(f"\n\u274c Connection Lost (attempt {attempt + 1}/{self.config.max_retries})")
                if attempt < self.config.max_retries - 1:
                    print("   Retrying in 3 seconds...")
                    time.sleep(3)
                else:
                    print("\n\U0001f4a1 Connection failed after retries. Check:")
                    print("   1. Is LM Studio still running?")
                    print("   2. Did the model unload? (Check LM Studio model tab)")
                    print("   3. Try reloading the model in LM Studio")
                    return None, None

            except openai.APIError as e:
                print(f"\n\u274c API Error: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(2)
                else:
                    return None, None

            except Exception as e:
                print(f"\n\u274c Unexpected Error: {e}")
                return None, None

        return None, None

    # -- Response repair --

    def _repair_too_short_response(
        self,
        *,
        agent: Agent,
        topic: str,
        context_block: str,
        short_content: str,
    ) -> str:
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
        if finish_reason == "length":
            return True

        normalized = (text or "").strip()
        if not normalized:
            return False

        if RE_WEB_SEARCH_COMMAND.search(normalized):
            return False

        if normalized.endswith((".", "!", "?", '"', "'", ")", "]")):
            return False

        if normalized.endswith((",", ";", ":")) and len(normalized) < 50:
            return True

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
        """Detect corrupted/garbled LLM outputs using multiple heuristics."""

        normalized = (text or "").strip()

        if not normalized:
            return True, "Response too short"

        if RE_CORRUPTION_CAPS.search(normalized):
            return True, "Excessive consecutive capitals detected"

        special_chars = sum(1 for c in normalized if c in ':;/\\|<>{}[]()@#$%^&*+=~`')
        if len(normalized) > 20 and special_chars / len(normalized) > 0.15:
            return True, "Too many special characters"

        for pattern in RE_CORRUPTION_PATTERNS:
            if pattern.search(normalized):
                return True, f"Corruption pattern detected: {pattern.pattern[:20]}"

        if len(normalized) < 20:
            sentence_candidate = normalized.rstrip("'\"'\u2019')]}")
            short_words = re.findall(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)?", normalized)
            if short_words and (sentence_candidate.endswith((".", "!", "?")) or len(short_words) >= 2):
                return False, ""
            if not short_words:
                return True, "Response too short"
            return False, ""

        if RainLabOrchestrator._looks_truncated_response(None, normalized, None):
            return True, "Incomplete sentence"

        lines = normalized.split("\n")
        empty_lines = sum(1 for line in lines if len(line.strip()) <= 2)
        if len(lines) > 5 and empty_lines / len(lines) > 0.5:
            return True, "Too many empty lines"

        words = normalized.split()
        if words:
            avg_word_len = sum(len(w) for w in words) / len(words)
            if avg_word_len > 15:
                return True, "Average word length too high (likely corrupted)"

        return False, ""

    # -- Wrap-up instructions --

    def _get_wrap_up_instruction(self, agent: Agent, topic: str) -> str:
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

    # -- Final stats --

    def _generate_final_stats(self) -> str:
        stats_lines = [
            "SESSION STATISTICS",
            "\u2500" * 70,
        ]

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

        if self.hypothesis_tree.size > 0:
            stats_lines.append("")
            stats_lines.append("HYPOTHESIS TREE:")
            proven = self.hypothesis_tree.proven_nodes()
            disproven = self.hypothesis_tree.disproven_nodes()
            active = self.hypothesis_tree.active_nodes()
            stats_lines.append(f"  \u2022 Proven: {len(proven)}  Active: {len(active)}  Disproven: {len(disproven)}")
            for node in proven:
                stats_lines.append(f"    [+] #{node.node_id}: {node.hypothesis}")
            for node in disproven[:5]:
                stats_lines.append(f"    [X] #{node.node_id}: {node.hypothesis}")

        return "\n".join(stats_lines)

    def _strip_agent_prefix(self, response: str, agent_name: str) -> str:
        cleaned = (response or "").strip()
        escaped_name = re.escape(agent_name)
        patterns = [
            rf"^{escaped_name}\s*(?:\([^)]*\))?\s*[:\-\u2013\u2014]\s*",
            rf"^{escaped_name}\s+here\s*[,:\-\u2013\u2014]\s*",
            rf"^(?:i am|i['\u2019]?m|im|this is)\s+{escaped_name}(?:\s*[,:\-\u2013\u2014]\s*|\s+and\s+)",
        ]

        while cleaned:
            updated = cleaned
            for pattern in patterns:
                updated = re.sub(pattern, "", updated, count=1, flags=re.IGNORECASE).strip()
            if updated == cleaned:
                break
            cleaned = updated

        return cleaned.strip()
