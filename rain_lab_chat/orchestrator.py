"""Main meeting orchestrator with citation tracking and error handling."""

import os
import re
import sys
import time
import uuid
import glob
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

from rain_lab_chat._sanitize import (
    RE_CORRUPTION_CAPS, RE_CORRUPTION_PATTERNS, RE_WEB_SEARCH_COMMAND,
)
from rain_lab_chat.config import Config
from rain_lab_chat.agents import Agent, RainLabAgentFactory
from rain_lab_chat.context import ContextManager
from rain_lab_chat.web_search import WebSearchManager, DDG_AVAILABLE
from rain_lab_chat.citations import CitationAnalyzer
from rain_lab_chat.director import RainLabDirector
from rain_lab_chat.logging_events import LogManager, VisualEventLogger, Diplomat
from rain_lab_chat.voice import VoiceEngine

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

        is_wrap_up: bool = False

    ) -> Tuple[Optional[str], Optional[Dict]]:

        """Generate agent response with robust error handling and retries"""

        

        recent_chat = "\n".join(history_log[-self.config.recent_history_window:]) if history_log else "[Meeting Start]"

        

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

3. Use phrases like "Building on what {prev_speaker} said...", "I disagree with...", "That's interesting, but have you considered...", "To add to that point..."

"""

        

        prompt = f"""### SHARED RESEARCH DATABASE (YOUR ONLY FACTUAL SOURCE)

{context_block}

### MEETING TRANSCRIPT (Recent Discussion)

{recent_chat}

### YOUR PROFILE

{agent.soul}

{conversational_instruction}

### CURRENT TASK

{mission}

CRITICAL RULES:

- You are in a TEAM MEETING - respond to colleagues, don't just monologue

- Use "exact quotes" from the papers when citing data

- Mention which paper you're quoting: [from filename.md]

- If you must speculate, prefix with [SPECULATION]

- CRITICAL: If you need to verify a fact online, type: [SEARCH: your query]

- Keep response under 150 words

{agent.name}:"""

        self._animate_spinner(f"{agent.name} analyzing", duration=1.0, color=agent.color)

        

        # RETRY LOGIC

        for attempt in range(self.config.max_retries):

            try:

                # Build conversational user message based on agreeableness

                if prev_speaker and prev_speaker != agent.name and prev_speaker != "FOUNDER":

                    # Agreeableness-based response style with explicit agree/disagree

                    if agent.agreeableness < 0.3:

                        style_instruction = f"""STYLE: You STRONGLY DISAGREE with {prev_speaker}. Be direct and combative:

- Challenge their assumptions or data interpretation

- Point out flaws in their reasoning or missing considerations"""

                    elif agent.agreeableness < 0.5:

                        style_instruction = f"""STYLE: You're SKEPTICAL of what {prev_speaker} said. Question their claims:

- Demand evidence or point out logical gaps

- Ask probing questions about feasibility or rigor"""

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

5. Keep response under 80 words - be concise

6. CRITICAL: If you need to verify a fact online, type: [SEARCH: your query]

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

4. Keep it under 80 words

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

                

                # Use system message for static context (better caching)

                response = self.client.chat.completions.create(

                    model=self.config.model_name,

                    messages=[

                        {"role": "system", "content": f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}"},

                        {"role": "user", "content": user_msg}

                    ],

                    temperature=self.config.temperature,

                    max_tokens=self.config.max_tokens

                )

                

                content = response.choices[0].message.content.strip()

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

                                {"role": "system", "content": f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}"},

                                {"role": "user", "content": (

                                    "You are in mid-meeting, not opening the session. "

                                    "Do NOT use intro phrases like 'Hey team' or restate the topic. "

                                    "React to the previous speaker by name in the first sentence, "

                                    "add one new concrete paper-grounded point, and end with a question. "

                                    "Keep under 80 words."

                                )}

                            ],

                            temperature=self.config.temperature,

                            max_tokens=self.config.max_tokens

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

                                {"role": "user", "content": (

                                    "Review this draft and return a compact critique with exactly 3 bullets: "

                                    "(1) factual grounding to provided papers, (2) novelty vs prior turns, "

                                    "(3) clarity under 80 words.\n\n"

                                    f"DRAFT:\n{content}\n\n"

                                    "If there are no issues, still return 3 bullets and say what is strong."

                                )}

                            ],

                            temperature=0.2,

                            max_tokens=120

                        )

                        critique_text = critique.choices[0].message.content.strip()

                        refined = self.client.chat.completions.create(

                            model=self.config.model_name,

                            messages=[

                                {"role": "system", "content": f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}"},

                                {"role": "user", "content": (

                                    f"Revise this response as {agent.name} using critique below. "

                                    "Keep it under 80 words, add one concrete paper-grounded point, "

                                    "avoid repetition, and respond in first person only.\n\n"

                                    f"ORIGINAL:\n{content}\n\n"

                                    f"CRITIQUE:\n{critique_text}"

                                )}

                            ],

                            temperature=self.config.temperature,

                            max_tokens=self.config.max_tokens

                        )

                        content = refined.choices[0].message.content.strip() or content

                        # Record critique pair for eval metrics

                        if self.metrics_tracker is not None:

                            self.metrics_tracker.record_critique(

                                pre_critique_text, content

                            )

                

                # Clean up response - remove agent speaking as self

                if content.startswith(f"{agent.name}:"):

                    content = content.replace(f"{agent.name}:", "", 1).strip()

                

                # Remove lines where agent speaks as OTHER team members (identity confusion)

                other_agents = ["James", "Jasmine", "Luca", "Elena"]

                cleaned_lines = []

                for line in content.split('\n'):

                    # Check if line starts with another agent's name followed by colon

                    is_other_agent_line = False

                    for other in other_agents:

                        if other != agent.name and line.strip().startswith(f"{other}:"):

                            is_other_agent_line = True

                            break

                    if not is_other_agent_line:

                        cleaned_lines.append(line)

                content = '\n'.join(cleaned_lines).strip()

                

                # Check if response was truncated (doesn't end with sentence-ending punctuation)

                finish_reason = response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else None

                is_truncated = finish_reason == "length" or (

                    content and 

                    not content.endswith(('.', '!', '?', '"', "'", ')')) and

                    len(content) > 50  # Only check longer responses

                )

                

                if is_truncated:

                    print("(completing...)", end=' ', flush=True)

                    # Request continuation

                    try:

                        continuation = self.client.chat.completions.create(

                            model=self.config.model_name,

                            messages=[

                                {"role": "system", "content": f"{agent.soul}"},

                                {"role": "user", "content": f"Complete this thought in ONE sentence. Keep it brief:\n\n{content}"}

                            ],

                            temperature=self.config.temperature,

                            max_tokens=60  # Just enough to finish the thought

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

                                for end in ['. ', '! ', '? ']:

                                    if end in content:

                                        last_end = content.rfind(end)

                                        if last_end > len(content) * 0.5:  # Last sentence in second half

                                            content = content[:last_end + 1]

                                            break

                                else:

                                    # No good sentence end found, append ellipsis

                                    content = content.rstrip(',;:') + "..."

                    except Exception:

                        # Continuation failed - try to end gracefully

                        for end in ['. ', '! ', '? ']:

                            if end in content:

                                last_end = content.rfind(end)

                                if last_end > len(content) * 0.5:

                                    content = content[:last_end + 1]

                                    break

                        else:

                            content = content.rstrip(',;:') + "..."

                

                # CORRUPTION CHECK - validate response before accepting

                is_corrupted, corruption_reason = self._is_corrupted_response(content)

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

                print(f"\n⏱️  Timeout (attempt {attempt+1}/{self.config.max_retries})")

                if attempt < self.config.max_retries - 1:

                    print("   Retrying in 2 seconds...")

                    time.sleep(2)

                else:

                    print("\n💡 The model might be overloaded. Try:")

                    print("   1. Reducing max_tokens in Config")

                    print("   2. Checking LM Studio's server logs")

                    return None, None

                

            except openai.APIConnectionError as e:

                print(f"\n❌ Connection Lost (attempt {attempt+1}/{self.config.max_retries})")

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

    

    def _is_corrupted_response(self, text: str) -> Tuple[bool, str]:

        """

        Detect corrupted/garbled LLM outputs using multiple heuristics.

        Returns (is_corrupted, reason) tuple.

        """

        if not text or len(text.strip()) < 10:

            return True, "Response too short"

        

        # Heuristic 1: Too many consecutive uppercase letters (token corruption)

        # Pattern like "AIVERCREDREDRIECKERE" is a sign of corruption

        if RE_CORRUPTION_CAPS.search(text):

            return True, "Excessive consecutive capitals detected"

        

        # Heuristic 2: High ratio of special characters (gibberish)

        special_chars = sum(1 for c in text if c in ':;/\\|<>{}[]()@#$%^&*+=~`')

        if len(text) > 20 and special_chars / len(text) > 0.15:

            return True, "Too many special characters"

        

        # Heuristic 3: Common corruption patterns

        for pattern in RE_CORRUPTION_PATTERNS:

            if pattern.search(text):

                return True, f"Corruption pattern detected: {pattern.pattern[:20]}"

        

        # Heuristic 4: Too many empty lines or lines with just punctuation

        lines = text.split('\n')

        empty_lines = sum(1 for line in lines if len(line.strip()) <= 2)

        if len(lines) > 5 and empty_lines / len(lines) > 0.5:

            return True, "Too many empty lines"

        

        # Heuristic 5: Average word length too high (concatenated garbage)

        words = text.split()

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

Keep it under 80 words - this is a quick closing summary.""",

            

            "Jasmine": f"""WRAP-UP TIME: Give your closing thoughts on '{topic}':

- State your MAIN CONCERN or practical challenge going forward

- Acknowledge if any colleague made a good point about feasibility

- Mention what you'd need to see before moving forward

Keep it under 60 words - be direct and practical as always.""",

            

            "Luca": f"""WRAP-UP TIME: Give your closing synthesis on '{topic}':

- Find the COMMON GROUND between what everyone said

- Highlight how different perspectives complemented each other

- Express optimism about where the research is heading

Keep it under 60 words - stay diplomatic and unifying.""",

            

            "Elena": f"""WRAP-UP TIME: Give your final assessment of '{topic}':

- State the most important MATHEMATICAL or THEORETICAL point established

- Note any concerns about rigor that still need addressing

- Acknowledge good work from colleagues if warranted

Keep it under 60 words - maintain your standards but be collegial."""

        }

        

        return wrap_up_instructions.get(agent.name, f"Provide your closing thoughts on '{topic}' in under 60 words.")

    

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

        

        return "\n".join(stats_lines)

    

    def _strip_agent_prefix(self, response: str, agent_name: str) -> str:

        """Strip duplicate agent name prefixes from the response.

        

        Handles patterns like:

        - "James: ..."

        - "James (R.A.I.N. Lab Lead): ..."

        - "James (R.A.I.N. Lab): ..."

        """

        

        # Pattern: agent name followed by optional parenthetical text, then colon

        # Examples: "James:", "James (R.A.I.N. Lab Lead):", "James (anything):"

        pattern = rf'^{re.escape(agent_name)}\s*(?:\([^)]*\))?\s*:\s*'

        

        cleaned = re.sub(pattern, '', response, count=1)

        return cleaned.strip()

# --- CLI INTERFACE ---
