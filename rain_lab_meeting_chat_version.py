"""
R.A.I.N. LAB - RESEARCH
 


"""

import warnings
import logging
import os
import random
import sys
import time
from pathlib import Path

DEFAULT_LIBRARY_PATH = str(Path(__file__).resolve().parent)
DEFAULT_MODEL_NAME = os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct")
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import argparse
try:
    import msvcrt  # Windows keyboard input detection
except ImportError:
    msvcrt = None

# --- SILENCE WARNINGS ---
warnings.simplefilter("ignore")
os.environ['PYTHONWARNINGS'] = 'ignore'
logging.getLogger().setLevel(logging.WARNING)

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


# --- CONFIGURATION (RTX 4090 + RNJ-1 8B OPTIMIZED) ---
@dataclass
class Config:
    """Centralized configuration - Optimized for Rnj-1 8B"""
    # LLM Settings (Rnj-1 8B is ~50% faster than 12B models)
    temperature: float = 0.7  # Higher temp for more variety in responses
    base_url: str = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    api_key: str = os.environ.get("LM_STUDIO_API_KEY", "lm-studio")
    model_name: str = DEFAULT_MODEL_NAME
    max_tokens: int = 200  # Enough tokens for agents to complete their thoughts
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
    context_snippet_length: int = 3000    # ~750 tokens per paper - more in-depth content
    total_context_length: int = 20000     # ~5k tokens for papers - allows full digestion
    recursive_library_scan: bool = True      # Include nested folders (e.g., openclaw-main)
    max_library_files: int = 400             # Hard cap to prevent runaway scans
    
    # Citation Tracking
    enable_citation_tracking: bool = True
    require_quotes: bool = True
    
    # Web Search Settings
    enable_web_search: bool = True  # Enable DuckDuckGo search for online context
    web_search_results: int = 3     # Number of search results per query
    
    # Output Settings
    verbose: bool = False  # Set to True to show detailed loading output


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
                with open(soul_path, 'r', encoding='utf-8') as f:
                    external_soul = f.read()
                # Append critical meeting rules to external soul
                meeting_rules = f"""

# MEETING RULES (CRITICAL)
- You are ONLY {self.name}. Never speak as another team member.
- Never write dialogue for others (no "James:" or "Jasmine would say...")
- Never echo or repeat what colleagues just said - use your OWN words
- Be concise: 50-80 words max per response
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
- Bring YOUR unique perspective based on your role and focus

# CITATION RULES
1. The "RESEARCH DATABASE" below is your ONLY factual source
2. Use "exact quotation marks" when citing specific data
3. Cite sources: [from filename.md]
4. If info isn't in papers, say: "The papers don't cover this"
5. For inferences beyond text, prefix with [REDACTED]

# CONVERSATION STYLE
- Be concise: 50-80 words max
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
                personality="Brilliant pattern-seeker with strong opinions. Will defend his geometric intuitions passionately but can be swayed by solid evidence. Sometimes dismissive of overly cautious approaches.",
                focus="Analyze the papers for 'Resonance', 'Geometric Structures', and 'Frequency' data. Connect disparate findings.",
                color="\033[92m",  # Green
                agreeableness=0.5,
                opinion_strength="strong"
            ),
            
            Agent(
                name="Jasmine",
                role="Hardware Architect",
                personality="Highly skeptical devil's advocate. Loves shooting down impractical ideas. Will argue that something can't be built unless proven otherwise. Finds theoretical discussions frustrating without concrete specs.",
                focus="Check the papers for 'Feasibility', 'Energy Requirements', and 'Material Constraints'. Ask: Can we actually build this?",
                color="\033[93m",  # Yellow
                agreeableness=0.2,
                opinion_strength="strong"
            ),
            
            Agent(
                name="Luca",
                role="Field Tomographer / Theorist",
                personality="Diplomatic peacemaker who tries to find common ground. Sees beauty in everyone's perspective. Rarely directly disagrees but will gently suggest alternatives. Sometimes too accommodating.",
                focus="Analyze the 'Topology', 'Fields', and 'Gradients' described in the papers. Describe the geometry of the theory.",
                color="\033[96m",  # Cyan
                agreeableness=0.9,
                opinion_strength="weak"
            ),
            
            Agent(
                name="Elena",
                role="Quantum Information Theorist",
                personality="Brutally honest math purist. Has zero patience for hand-waving or vague claims. Will interrupt to demand mathematical rigor. Often clashes with James's intuitive approach.",
                focus="Analyze 'Information Bounds', 'Computational Limits', and 'Entropy' in the research. Look for mathematical consistency.",
                color="\033[95m",  # Magenta
                agreeableness=0.6,
                opinion_strength="strong"
            ),
        ]


# --- CONTEXT MANAGEMENT ---
class ContextManager:
    """Reads and manages research paper context - FULL PAPER MODE"""
    
    def __init__(self, config: Config):
        self.config = config
        self.lab_path = Path(config.library_path)
        self.loaded_papers: Dict[str, str] = {}
        self.loaded_papers_lower: Dict[str, str] = {}
        self.paper_list: List[str] = []
    
    def _discover_files(self) -> List[Path]:
        """Discover candidate research files, optionally including nested directories."""
        skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", "meeting_archives"}
        allowed_suffixes = {".md", ".txt", ".py"}

        if self.config.recursive_library_scan:
            candidates = [
                f for f in self.lab_path.rglob("*")
                if f.is_file() and f.suffix.lower() in allowed_suffixes
                and not any(part in skip_dirs for part in f.parts)
            ]
        else:
            candidates = [
                f for f in self.lab_path.iterdir()
                if f.is_file() and f.suffix.lower() in allowed_suffixes
            ]

        filtered = [
            f for f in candidates
            if f.name == "hello_os.py"
            or (f.parent.name == "hello_os" and f.suffix == ".py")
            or f.suffix.lower() in {".md", ".txt"}
        ]

        filtered = [
            f for f in filtered
            if "SOUL" not in f.name.upper()
            and "LOG" not in f.name.upper()
            and "MEETING" not in f.name.upper()
        ]
        return sorted(filtered)[: self.config.max_library_files]

    def get_library_context(self, verbose: bool = False) -> Tuple[str, List[str]]:
        """Read COMPLETE papers from local library"""
        # Ensure repeated calls don't keep stale/duplicated state.
        self.loaded_papers = {}
        self.loaded_papers_lower = {}
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
        
        for filepath in all_files:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Store FULL content for citation verification
                    paper_ref = str(filepath.relative_to(self.lab_path))
                    self.loaded_papers[paper_ref] = content
                    self.loaded_papers_lower[paper_ref] = content.lower()
                    self.paper_list.append(paper_ref)
                    
                    # Include full paper up to snippet length (25k = essentially full)
                    remaining_budget = self.config.total_context_length - total_chars
                    
                    if remaining_budget > 1000:
                        to_include = min(len(content), self.config.context_snippet_length, remaining_budget)
                        buffer.append(f"--- PAPER: {paper_ref} ---\n{content[:to_include]}\n")
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
        
        combined = "\n".join(buffer)
        
        if verbose:
            print(f"\n   📊 Total context loaded: {len(combined):,} characters")
            print(f"   📊 Papers with full coverage: {len([p for p in self.loaded_papers.keys()])}")
        
        return combined, self.paper_list
    
    def verify_citation(self, quote: str, fuzzy: bool = True) -> Optional[str]:
        """Verify if a quote exists in loaded papers"""
        quote_clean = quote.strip().lower()
        
        # Skip very short quotes
        if len(quote_clean.split()) < 3:
            return None
        
        for paper_name in self.loaded_papers:
            content_clean = self.loaded_papers_lower[paper_name]
            
            if fuzzy:
                # Allow minor variations (punctuation, whitespace)
                quote_words = quote_clean.split()
                if len(quote_words) > 3:
                    # Check multiple word windows for better matching
                    # Try first 5 words, then first 8, then middle section
                    windows_to_check = [
                        " ".join(quote_words[:5]),
                        " ".join(quote_words[:8]) if len(quote_words) >= 8 else None,
                        " ".join(quote_words[2:7]) if len(quote_words) >= 7 else None,
                    ]
                    for window in windows_to_check:
                        if window and window in content_clean:
                            return paper_name
            else:
                # Exact match required
                if quote_clean in content_clean:
                    return paper_name
        
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
                            results.append({
                                'title': r.get('title', ''),
                                'body': r.get('body', ''),
                                'href': r.get('href', '')
                            })
                
                self.search_cache[query] = results
                
                if results:
                    if verbose:
                        print(f"   ✓ Found {len(results)} web results")
                        for i, r in enumerate(results, 1):
                            title_preview = r['title'][:60] + '...' if len(r['title']) > 60 else r['title']
                            print(f"      {i}. {title_preview}")
                    return self._format_results(results), results
                else:
                    # No results but no error - may be rate limited or bad query
                    if attempt < self.max_retries - 1:
                        delay = self.retry_delay * (attempt + 1)
                        if verbose:
                            print(f"   ⚠ No results (attempt {attempt + 1}/{self.max_retries}), retrying in {delay:.1f}s...")
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
    
    def _format_results(self, results: List[Dict]) -> str:
        """Format results for agent context"""
        if not results:
            return ""
        
        formatted = ["\n### WEB SEARCH RESULTS (cite as [from web: title])"]
        for r in results:
            formatted.append(f"**{r['title']}**")
            formatted.append(f"{r['body']}")
            formatted.append(f"Source: {r['href']}\n")
        
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
        import re
        # Match text in "quotes" or 'quotes'
        quotes = re.findall(r'"([^"]+)"', text)
        quotes.extend(re.findall(r"'([^']+)'", text))
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
            'quotes_found': len(quotes),
            'verified': verified,
            'unverified': unverified,
            'has_speculation_tag': has_speculation,
            'citation_rate': len(verified) / len(quotes) if quotes else 0
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
            return f"Open the meeting. Survey the loaded research papers and identify which ones discuss '{topic}'. Quote key definitions or findings."

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
            ]
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
        context_block, paper_list = self.context_manager.get_library_context(verbose=verbose)
        
        if not paper_list:
            print("\n❌ No papers found. Cannot proceed.")
            return
        
        # Initialize components that need context
        self.director = RainLabDirector(self.config, paper_list)
        self.citation_analyzer = CitationAnalyzer(self.context_manager)
        
        # Load agent souls from external files
        if verbose:
            print("\n🧠 Loading Agent Souls...")
        for agent in self.team:
            agent.load_soul(self.config.library_path, verbose=verbose)
        
        # Perform web search for supplementary context
        web_context = ""
        if self.web_search_manager.enabled:
            web_context, _ = self.web_search_manager.search(topic, verbose=verbose)
        elif self.config.enable_web_search and not DDG_AVAILABLE and verbose:
            print("\n⚠️  Web search disabled: duckduckgo-search not installed")
            print("   Install with: pip install duckduckgo-search\n")
        
        # Combine contexts
        full_context = context_block
        if web_context:
            full_context = context_block + "\n\n" + web_context
        
        # Store for use in agent responses
        self.full_context = full_context
        
        # Initialize log
        self.log_manager.initialize_log(topic, len(paper_list))
        
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
            
            # Windows-compatible: check for keypress during brief window
            intervention_window = 1.5  # seconds to wait for user input
            start_time = time.time()
            while time.time() - start_time < intervention_window:
                if msvcrt and msvcrt.kbhit():  # Check if a key was pressed
                    key = msvcrt.getch()
                    user_wants_to_speak = True
                    break
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
                            self.log_manager.finalize_log(self._generate_final_stats())
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
            
            # Show citation feedback
            if metadata and metadata.get('verified'):
                print(f"\033[90m   ✓ {len(metadata['verified'])} citation(s) verified\033[0m")
                for quote, source in metadata['verified'][:1]:  # Show first citation
                    print(f"\033[90m      • \"{quote[:60]}...\" [from {source}]\033[0m")
            
            # 5. Log
            self.log_manager.log_statement(current_agent.name, response, metadata)
            history_log.append(f"{current_agent.name}: {response}")
            
            turn_count += 1
        
        # Meeting officially closed
        print("\n" + "="*70)
        print("👋 MEETING ADJOURNED")
        print("="*70)
        print("\n\033[92mJames: Alright team, great discussion today! Let's reconvene soon.\033[0m")
        self.log_manager.log_statement("James", "Meeting adjourned. Great discussion everyone!")
        
        # Finalize
        stats = self._generate_final_stats()
        self.log_manager.finalize_log(stats)
        
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

                # Optional recursive refinement: critique + revise in short internal loops
                if self.config.recursive_intellect and self.config.recursive_depth > 0 and content:
                    for _ in range(self.config.recursive_depth):
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
        import re
        if re.search(r'[A-Z]{8,}', text):
            return True, "Excessive consecutive capitals detected"
        
        # Heuristic 2: High ratio of special characters (gibberish)
        special_chars = sum(1 for c in text if c in ':;/\\|<>{}[]()@#$%^&*+=~`')
        if len(text) > 20 and special_chars / len(text) > 0.15:
            return True, "Too many special characters"
        
        # Heuristic 3: Common corruption patterns
        corruption_patterns = [
            r'\|eoc_fim\|',           # End of context markers
            r'ARILEX|AIVERI|RIECK',   # Common corruption sequences
            r'ingly:\w*scape',        # Gibberish compound words
            r':\s*\n\s*:\s*\n',       # Empty lines with colons
            r'##\d+\s*\(',            # Markdown header gibberish
            r'SING\w{10,}',           # Long corrupt strings starting with SING
            r'[A-Z]{4,}:[A-Z]{4,}',   # Multiple caps words with colons
        ]
        for pattern in corruption_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True, f"Corruption pattern detected: {pattern[:20]}"
        
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
        
        return "\n".join(stats_lines)
    
    def _strip_agent_prefix(self, response: str, agent_name: str) -> str:
        """Strip duplicate agent name prefixes from the response.
        
        Handles patterns like:
        - "James: ..."
        - "James (R.A.I.N. Lab Lead): ..."
        - "James (R.A.I.N. Lab): ..."
        """
        import re
        
        # Pattern: agent name followed by optional parenthetical text, then colon
        # Examples: "James:", "James (R.A.I.N. Lab Lead):", "James (anything):"
        pattern = rf'^{re.escape(agent_name)}\s*(?:\([^)]*\))?\s*:\s*'
        
        cleaned = re.sub(pattern, '', response, count=1)
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
        """
    )
    
    parser.add_argument(
        '--library',
        type=str,
        default=DEFAULT_LIBRARY_PATH,
        help='Path to research library folder'
    )
    
    parser.add_argument(
        '--topic',
        type=str,
        help='Research topic (if not provided, will prompt)'
    )

    parser.add_argument(
        '--model',
        type=str,
        default=DEFAULT_MODEL_NAME,
        help=f"LM Studio model name (default: {DEFAULT_MODEL_NAME})"
    )

    parser.add_argument(
        '--base-url',
        type=str,
        default=os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
        help='LM Studio OpenAI-compatible base URL'
    )
    
    parser.add_argument(
        '--temp',
        type=float,
        default=0.4,
        help='LLM temperature (0.0-1.0, default: 0.4)'
    )

    parser.add_argument(
        '--recursive-depth',
        type=int,
        default=int(os.environ.get("RAIN_RECURSIVE_DEPTH", "1")),
        help='Internal self-reflection passes per response (default: 1)'
    )

    parser.add_argument(
        '--no-recursive-intellect',
        action='store_true',
        help='Disable recursive self-reflection refinement'
    )
    
    parser.add_argument(
        '--max-turns',
        type=int,
        default=25,
        help='Maximum conversation turns (default: 25)'
    )
    
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=200,
        help='Max tokens per response (default: 200)'
    )

    parser.add_argument(
        '--timeout',
        type=float,
        default=float(os.environ.get("RAIN_LM_TIMEOUT", "300")),
        help='LLM read timeout in seconds (default: 300)'
    )
    
    parser.add_argument(
        '--no-web',
        action='store_true',
        help='Disable DuckDuckGo web search'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed loading output (papers, souls, web search)'
    )
    
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"⚠️ Ignoring unrecognized args: {' '.join(unknown)}")
    return args


# --- ENTRY POINT ---
def main():
    """Main entry point"""
    args = parse_args()
    
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
        recursive_intellect=not args.no_recursive_intellect
    )
    
    # Get topic
    if args.topic:
        topic = args.topic
    else:
        print("\n" + "="*70)
        print("R.A.I.N. LAB - RESEARCH FOCUS")
        print("="*70)
        topic = input("\n🔬 Research Topic: ").strip()
    
    if not topic:
        print("❌ No topic provided. Exiting.")
        sys.exit(1)
    
    # Run meeting
    orchestrator = RainLabOrchestrator(config)
    orchestrator.run_meeting(topic)


if __name__ == "__main__":
    main()
