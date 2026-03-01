"""
R.A.I.N. LAB 

"""

import sys
import os
import glob
import io
import time
import uuid
import concurrent.futures
from pathlib import Path
from typing import List
from dataclasses import dataclass, field
from datetime import datetime

# --- EVAL METRICS ---
try:
    from rain_metrics import MetricsTracker
except ImportError:
    MetricsTracker = None  # metrics collection is optional

# --- FORCE UTF-8 GLOBALLY (must be before other imports) ---
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        # Some environments don't expose reconfigure(); keep running.
        pass
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

# POINT TO THE USER'S LIBRARY LOCATION
TARGET_PATH = os.environ.get("JAMES_LIBRARY_PATH")
if not TARGET_PATH or not os.path.exists(TARGET_PATH):
    # Fallback to the current working directory when launched from the repo folder.
    TARGET_PATH = os.getcwd()

# Ensure consistent environment for subprocesses/REPL
os.environ["JAMES_LIBRARY_PATH"] = TARGET_PATH

# Add path so we can import 'rlm'
sys.path.append(TARGET_PATH)
sys.path.append(os.path.join(TARGET_PATH, "rlm-main"))  # Just in case it's nested
sys.path.append(os.path.join(TARGET_PATH, "rlm-main", "rlm-main"))  # Double nested

try:
    import sys as _sys_mod
    for _m in list(_sys_mod.modules):
        if _m == 'rlm' or _m.startswith('rlm.'):
            _sys_mod.modules.pop(_m, None)
except Exception:  # noqa: E722 — best-effort cache clear; safe to ignore
    pass

RLM = None
if "--help" not in sys.argv and "-h" not in sys.argv:
    try:
        from rlm import RLM
        import rlm as _rlm_mod
        print(f"Using RLM from: {_rlm_mod.__file__}")
    except ImportError as e:
        missing_dep = getattr(e, "name", None)
        print(f"❌ CRITICAL ERROR: Could not import 'rlm' from {TARGET_PATH}")
        print("Checked sys.path entries:")
        print(f"  - {TARGET_PATH}")
        print(f"  - {os.path.join(TARGET_PATH, 'rlm-main')}")
        print(f"  - {os.path.join(TARGET_PATH, 'rlm-main', 'rlm-main')}")
        if missing_dep:
            print(f"Missing Python dependency: {missing_dep}")
            print("Install it in this same Python env and re-run.")
        else:
            print(f"ImportError details: {e}")
        sys.exit(1)


def _host_has_web_search() -> bool:
    try:
        try:
            from ddgs import DDGS  # noqa: F401
        except ImportError:
            from duckduckgo_search import DDGS  # noqa: F401
        return True
    except ImportError:
        return False

# --- FORCE UTF-8 ---
for _name in ("stdout", "stderr"):
    _obj = getattr(sys, _name, None)
    _buffer = getattr(_obj, "buffer", None)
    if _buffer is not None:
        setattr(sys, _name, io.TextIOWrapper(_buffer, encoding='utf-8'))


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


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


try:
    from tools import get_setup_code as _get_setup_code
except Exception:  # noqa: E722
    _get_setup_code = None


# =============================================================================
# THE SETUP CODE: INJECTED INTO RLM REPL
# This code runs INSIDE the agent's brain before it starts.
# =============================================================================
_DEFAULT_SETUP_CODE = '''
import os
import glob
import re

# PATH TO USER LIBRARY (Use forward slashes to avoid escape issues)
LIBRARY_PATH = os.environ.get("JAMES_LIBRARY_PATH", os.getcwd())

# GLOBAL TOPIC VARIABLE (Injected by the agent's first turn or host env)
TOPIC = os.environ.get("RLM_TOPIC", "RESEARCH_TOPIC")

# --- LAZY IMPORT HELPERS & GLOBALS ---
embedder = None
collection = None
_web_search_ready = False
_rag_failed = False
_paper_cache = {}
_library_files_cache = None  # Cache for glob results
HELLO_OS_PATH = os.path.join(LIBRARY_PATH, "hello_os.py")
HELLO_OS_PKG = os.path.join(LIBRARY_PATH, "hello_os")


def sanitize_text(text):
    if not text: return ""
    text = text.replace("<|endoftext|>", "[TOKEN_REMOVED]")
    text = text.replace("<|im_start|>", "[TOKEN_REMOVED]")
    text = text.replace("<|im_end|>", "[TOKEN_REMOVED]")
    text = text.replace("|eoc_fim|", "[TOKEN_REMOVED]")
    text = text.replace("###", ">>>")
    text = text.replace("[SEARCH:", "[SEARCH;")
    return text.strip()


def _get_library_files():
    """Return cached list of library files to avoid repeated globs."""
    global _library_files_cache
    if _library_files_cache is None:
        _library_files_cache = glob.glob(os.path.join(LIBRARY_PATH, "*.md")) + glob.glob(os.path.join(LIBRARY_PATH, "*.txt"))
    return _library_files_cache


def _require_web_search():
    """Fail fast if DuckDuckGo client isn't available."""
    global _web_search_ready
    if _web_search_ready:
        return True
    try:
        try:
            from ddgs import DDGS  # noqa: F401
        except ImportError:
            from duckduckgo_search import DDGS  # noqa: F401
        _web_search_ready = True
        return True
    except ImportError as e:
        _web_search_ready = False
        print(
            "[ERROR] DuckDuckGo search client not installed. "
            "Install one of: 'ddgs' or 'duckduckgo_search'."
        )
        return False


def _init_rag():
    """Initialize RAG system if dependencies exist."""
    global embedder, collection, _rag_failed
    if _rag_failed:
        return False
    if embedder is not None: return True # Already initialized
    
    try:
        # --- ROBUST WINDOWS FIX FOR [WinError 1114] ---
        # 1. Force KMP override to avoid OpenMP conflicts
        os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
        
        # 2. Locate and add paths
        import sys
        import site
        import ctypes
        
        paths_to_add = []
        
        # Find Conda Library/bin (System DLLs: msvcp140, etc)
        conda_base = os.path.dirname(sys.executable)
        conda_lib = os.path.join(conda_base, "Library", "bin")
        if not os.path.exists(conda_lib):
            conda_lib = os.path.join(sys.prefix, "Library", "bin")
        if os.path.exists(conda_lib):
            paths_to_add.append(conda_lib)

        # Find Torch Lib
        torch_lib = None
        try:
            site_packages = site.getsitepackages()
            for sp in site_packages:
                tlib = os.path.join(sp, "torch", "lib")
                if os.path.exists(tlib):
                    torch_lib = tlib
                    paths_to_add.append(tlib)
                    break
        except: pass

        # Add to PATH (Prepend to ensure priority)
        if paths_to_add:
            os.environ['PATH'] = os.pathsep.join(paths_to_add) + os.pathsep + os.environ['PATH']
            
        # Add to DLL Directory (Python 3.8+)
        if hasattr(os, 'add_dll_directory'):
            for p in paths_to_add:
                try: os.add_dll_directory(p)
                except: pass

        # 3. EXPLICIT PRE-LOADING (The Nuclear Option)
        # Pre-load dependencies to ensure they are in memory before c10.dll tries to load
        def force_load(name, directory):
            if not directory: return
            path = os.path.join(directory, name)
            if os.path.exists(path):
                try: ctypes.CDLL(path)
                except: pass

        force_load("msvcp140.dll", conda_lib)
        force_load("vcruntime140.dll", conda_lib)
        force_load("vcruntime140_1.dll", conda_lib)
        force_load("zlib.dll", conda_lib)
        
        force_load("libiomp5md.dll", torch_lib)
        force_load("uv.dll", torch_lib)
        # ----------------------------------------------

        # Exclusive import of torch to ensure DLLs are loaded
        import torch
        
        import chromadb
        from sentence_transformers import SentenceTransformer
        
        print("⏳ Initializing Semantic RAG (this may take a moment)...")
        embedder = SentenceTransformer('all-MiniLM-L6-v2')
        chroma_client = chromadb.PersistentClient(path=os.path.join(LIBRARY_PATH, "chroma_db"))
        collection = chroma_client.get_or_create_collection("james_library")
        print("✅ RAG Initialized.")
        return True
    except ImportError:
        _rag_failed = True
        print("[WARNING] RAG dependencies missing. Install: pip install chromadb sentence-transformers")
        return False
    except Exception as e:
        _rag_failed = True
        print(f"[ERROR] RAG Initialization Failed: {e}")
        print("   (Proceeding without semantic search capabilities)")
        return False

def index_library():
    """Indexes all papers in the library for semantic search."""
    if not _init_rag() or not collection:
        return "RAG system not available (missing dependencies)."
    
    print("📚 Indexing library...")
    count = 0
    for file_path in _get_library_files():
        if "SOUL" in file_path or "LOG" in file_path: continue
        try:
            with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                text = f.read()
                if not text.strip(): continue
                
                # Naive upsert
                embedding = embedder.encode(text).tolist()
                collection.add(
                    documents=[text],
                    embeddings=[embedding],
                    ids=[os.path.basename(file_path)],
                    metadatas=[{"source": os.path.basename(file_path)}]
                )
                count += 1
        except Exception as e:
            print(f"Skipped {file_path}: {e}")
            
    print(f"✅ Indexed {count} papers.")
    return f"Indexed {count} papers."

def search_web(query):
    """Returns top search results for the query using DuckDuckGo."""
    print(f"🔎 WEB SEARCH: {query}...")
    
    # 1. Check for "task" or "objective" meta-searches
    if any(x in query.lower() for x in ["task", "objective", "instruction", "what to do", "requirements"]):
        print("⚠️ Meta-search detected. Returning hint.")
        return f"SYSTEM HINT: The 'task' is the meeting TOPIC: '{TOPIC}'. Do not search for 'task'. Search for information related to '{TOPIC}'."

    try:
        # Try both package names just in case
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
            
        # Use a context manager if possible, or just instantiate
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
        except:
             # Fallback for older versions or if context manager fails
             results = list(DDGS().text(query, max_results=5))

        result = "\\n".join([f"{r['title']}: {r['body']}" for r in results])
        result = sanitize_text(result)
        print(result)
        return result
    except ImportError:
        print("Error: duckduckgo_search not installed.")
        return "Error: duckduckgo_search not installed."
    except Exception as e:
        print(f"Search Error: {e}")
        return f"Search Error: {e}"

def read_paper(keyword):
    """Read one best-matching paper safely; reuse cached content on repeated reads."""
    global _paper_cache
    kw = (keyword or "").strip()
    print(f"📖 READING PAPER: {kw}...")
    if kw.lower() in {"task", "task analysis", "analysis", "context"}:
        return "Invalid paper name. Use list_papers() and read_paper() with a real filename."

    # Prefer exact filename matches first to avoid broad wildcard collisions.
    all_files = [
        f for f in _get_library_files()
        if not os.path.basename(f).startswith("_")
        and "SOUL" not in os.path.basename(f).upper()
        and "LOG" not in os.path.basename(f).upper()
    ]
    kw_lower = kw.lower()
    exact = [f for f in all_files if os.path.basename(f).lower() == kw_lower]
    if not exact:
        exact = [f for f in all_files if os.path.basename(f).lower() == (kw_lower + ".md") or os.path.basename(f).lower() == (kw_lower + ".txt")]

    chosen_files = exact if exact else [f for f in all_files if kw_lower in os.path.basename(f).lower()]
    if not chosen_files:
        return "No paper found."

    file_path = chosen_files[0]
    basename = os.path.basename(file_path)

    # Fast path: avoid re-reading the same paper again in this session.
    if basename in _paper_cache:
        result = _paper_cache[basename]
        print(result)
        return result

    try:
        with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()[:120000]
        content = sanitize_text(content)
        result = chr(10) + "--- CONTENT OF " + basename + " ---" + chr(10) + content
        _paper_cache[basename] = result
        print(result)
        return result
    except Exception as e:
        msg = "Error reading " + str(file_path) + ": " + str(e)
        print(msg)
        return msg


def search_library(query):
    """Search all papers for key terms in the query (checks content AND filenames)."""
    print(f"🕵️ LIBRARY SEARCH: {query}...")
    results = []
    
    # 1. Check for "task" or "objective" meta-searches
    if any(x in query.lower() for x in ["task", "objective", "instruction", "what to do"]):
        print("?????? Meta-search detected. Redirecting to list_papers().")
        return list_papers()

    # Split query into keywords (ignore small words)
    keywords = [k.lower() for k in query.split() if len(k) > 3]
    if not keywords: keywords = [query.lower()]
    
    for file_path in _get_library_files():
        basename = os.path.basename(file_path)
        if basename.startswith("_"):
            continue
        if "SOUL" in basename.upper() or "LOG" in basename.upper():
            continue
        try:
            filename = basename
            with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                content = f.read()
                content_lower = content.lower()
                filename_lower = filename.lower()
                
                # Check Filename first (High priority)
                if any(k in filename_lower for k in keywords):
                    results.append((10.0, filename, ["FILENAME MATCH"]))
                    continue

                # Count matches in content
                match_count = sum(1 for k in keywords if k in content_lower)
                if match_count > 0:
                     score = match_count / len(keywords)
                     results.append((score, filename, [k for k in keywords if k in content_lower]))
        except:
            pass
            
    # Sort by score
    results.sort(key=lambda x: x[0], reverse=True)
    
    if results:
        output = []
        for score, filename, matches in results[:5]:
            snippet = f"Found in {filename} (matches: {', '.join(matches)})"
            # Add a strong hint to read it
            keyword_hint = filename.split('.')[0] # simplified keyword
            snippet += f" -> USE read_paper('{keyword_hint}')"
            output.append(snippet)
        result = "\\n".join(output)
    else:
        # Auto-list papers if search fails
        all_files = [os.path.basename(f) for f in _get_library_files() if not os.path.basename(f).startswith("_") and "SOUL" not in os.path.basename(f).upper() and "LOG" not in os.path.basename(f).upper()]
        result = f"No direct matches for '{query}'.\\nAVAILABLE PAPERS:\\n" + ", ".join(all_files) + "\\n\\nSYSTEM ADVICE: Pick a filename from above and use read_paper() on it."

    print(result)
    return result

def semantic_search(query):
    """Finds semantically similar content in the library."""
    if any(x in query.lower() for x in ["task", "objective", "instruction", "what to do"]):
        print("?????? Meta-search detected. Redirecting to list_papers().")
        return list_papers()
    if not _init_rag() or not collection:
        return "RAG unavailable; use search_library() or read_paper()."
        
    print(f"🧠 SEMANTIC SEARCH: {query}...")
    try:
        embedding = embedder.encode(query).tolist()
        results = collection.query(query_embeddings=[embedding], n_results=3)
        
        output = []
        if results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                source = results['metadatas'][0][i]['source']
                snippet = doc[:2000] # Return first 2000 chars of the match
                output.append(f"From {source}: {snippet}...")
                
                
        result = "\\n\\n".join(output) if output else "No semantic matches found."
        result = sanitize_text(result)
        print(result)
        return result
    except Exception as e:
        print(f"Semantic Search Error: {e}")
        return f"Semantic Search Error: {e}"

def list_papers():
    """Lists all research papers in the library."""
    files = _get_library_files()
    research = [os.path.basename(f) for f in files if not os.path.basename(f).startswith("_") and "SOUL" not in os.path.basename(f).upper() and "LOG" not in os.path.basename(f).upper()]
    if os.path.exists(HELLO_OS_PATH) or os.path.isdir(HELLO_OS_PKG):
        research.append("hello_os")
    result = "Available papers: " + ", ".join(research)
    print(result)
    return result

def read_hello_os(max_chars=120000):
    """Read hello_os so agents can leverage its operators and design patterns.

    Prefers the hello_os/ package directory when available, falls back to the
    flat hello_os.py file.
    """
    print("📖 READING HELLO_OS...")
    try:
        # Prefer the package directory
        if os.path.isdir(HELLO_OS_PKG):
            parts = []
            for mod in ("symbols.py", "utils.py", "core.py", "geometry.py", "resonance.py"):
                mod_path = os.path.join(HELLO_OS_PKG, mod)
                if os.path.exists(mod_path):
                    with open(mod_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                        parts.append(f.read())
            if parts:
                content = chr(10).join(parts)[:max_chars]
                content = sanitize_text(content)
                result = chr(10) + "--- CONTENT OF hello_os (package) ---" + chr(10) + content
                print(result)
                return result
        # Fallback to flat file
        if not os.path.exists(HELLO_OS_PATH):
            return "hello_os.py not found in library path."
        with open(HELLO_OS_PATH, 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()[:max_chars]
        content = sanitize_text(content)
        result = chr(10) + "--- CONTENT OF hello_os.py ---" + chr(10) + content
        print(result)
        return result
    except Exception as e:
        msg = "Error reading hello_os: " + str(e)
        print(msg)
        return msg

TOOLS_READY = True
print("[SETUP] tools ready")

# --- SAFE TEXT HELPERS ---

def extract_section(text, start, end):
    """Safely extract text between two markers. Returns a message if not found."""
    if start not in text or end not in text:
        return "Section markers not found. Check headings or use search_library/read_paper."
    return text.split(start, 1)[1].split(end, 1)[0]

def regex_section(pattern, text, flags=re.DOTALL):
    """Safely extract a regex group(1). Returns a message if no match."""
    m = re.search(pattern, text, flags)
    return m.group(1) if m else "Pattern not found in text."

def read_repl_context():
    """Compat stub: context is blocked; instruct to use read_paper()."""
    return "Context is blocked. Use read_paper() to access documents."

# =============================================================================
# HARD ENFORCEMENT: Delete/shadow dangerous RLM variables
# The LLM ignores instructions, so we remove access entirely
# =============================================================================
# Shadow 'context' so printing it shows instructions, not the prompt
context = "USE read_paper() TO ACCESS DATA. DO NOT PRINT THIS VARIABLE."

# Delete llm_query if it exists (it's an RLM internal function)
try:
    del llm_query
except NameError:
    pass

# Make FINAL_VAR and SHOW_VARS throw clear errors if called
def FINAL_VAR(*args, **kwargs):
    raise NameError("FINAL_VAR does not exist! Just write your answer directly.")

def FINAL(*args, **kwargs):
    raise NameError("FINAL does not exist! Just write your answer directly.")

def SHOW_VARS(*args, **kwargs):
    raise NameError("SHOW_VARS does not exist! Use print() instead.")

# Initialize on startup (best effort)
REQUIRE_WEB = os.environ.get("RLM_REQUIRE_WEB", "1") == "1"
try:
    if REQUIRE_WEB:
        _require_web_search()
    _init_rag()
except BaseException as e:
    print(f"[ERROR] Setup initialization failed: {e}")

# Trigger one-time index if possible?
# For now, we trust the agent or user to call index_library() if needed, 
# OR we just do a quick check.
if collection and collection.count() == 0:
    print("Empty library detected. Indexing now...")
    index_library()
'''

def _resolve_setup_code(default_code: str) -> str:
    """Load setup code from tools.py when valid; otherwise keep embedded fallback."""
    if _get_setup_code is None:
        return default_code

    try:
        candidate = _get_setup_code()
        if not isinstance(candidate, str) or not candidate.strip():
            raise ValueError("setup code is empty")
        compile(candidate, "<tools_setup_code>", "exec")
        return candidate
    except Exception as exc:
        print(f"[WARNING] Invalid tools.get_setup_code(); using embedded fallback. ({exc})")
        return default_code


setup_code = _resolve_setup_code(_DEFAULT_SETUP_CODE)


# =============================================================================
# AGENT DEFINITIONS
# =============================================================================
@dataclass
class Agent:
    name: str
    role: str
    focus: str
    color: str
    tool_instruction: str
    _soul_cache: str = field(default="", repr=False)
    
    def load_soul(self, library_path: str) -> str:
        """Load soul from external .md file"""
        soul_path = Path(library_path) / f"{self.name.upper()}_SOUL.md"
        
        if soul_path.exists():
            with open(soul_path, 'r', encoding='utf-8-sig') as f:
                external_soul = f.read()
            
            # RLM code execution rules
            rlm_rules = f"""

# CODE EXECUTION
You can execute Python code to access the research library and web.
Available functions (already defined):

```python
content = read_paper("keyword")      # Read a paper from the library
hello_os = read_hello_os()            # Load hello_os.py into context
results = search_web("query")        # Search the web
papers = list_papers()               # List available papers
search_results = search_library("query") # Keyword search in library
rag_results = semantic_search("query")   # Semantic search in library
```

{self.tool_instruction}

RULES:
- You are ONLY {self.name}. Never speak as another team member.
- Be concise: 80-120 words max per response.
- When you need data, write code to get it.
- Use ONLY research papers from this library (e.g., Coherence Depth, Discrete Celestial Holography, Location is a Dynamic Variable) and web search.
- Only use: read_paper(), read_hello_os(), search_web(), list_papers(), search_library(), semantic_search()
"""
            self._soul_cache = external_soul + rlm_rules
            print(f"     ✓ Soul loaded: {self.name.upper()}_SOUL.md")
            return self._soul_cache
        
        raise FileNotFoundError(f"Missing SOUL file: {soul_path}")
    
    @property
    def soul(self) -> str:
        return self._soul_cache if self._soul_cache else f"You are {self.name}."


def create_team() -> List[Agent]:
    """Create the 4-agent research council"""
    return [
        Agent(
            name="James",
            role="Lead Scientist/Technician",
            focus="Physics simulations and research analysis",
            color="\033[92m",  # Green
            tool_instruction="""
AVAILABLE: read_paper(), read_hello_os(), run_hello_os_executable(), search_web(), list_papers()
BANNED: llm_query(), FINAL_VAR(), FINAL(), SHOW_VARS(), context
RESPOND: 50-100 words, conversational, as a scientist.
SOURCE RULE: Use only local research papers + web search; do not rely on other sources.
"""
        ),
        Agent(
            name="Jasmine",
            role="Hardware Architect",
            focus="Check 'Feasibility', 'Energy Requirements', 'Material Constraints'. Can we build this?",
            color="\033[93m",  # Yellow
            tool_instruction="⚡ JASMINE: You MUST use search_web() to find real-world energy constraints and hardware specifications."
        ),
        Agent(
            name="Elena",
            role="Quantum Information Theorist",
            focus="Check 'Information Bounds', 'Computational Limits'. Demand mathematical rigor.",
            color="\033[95m",  # Magenta
            tool_instruction="🔢 ELENA: Audit the code for computational feasibility. Challenge hand-waving with math."
        ),
        Agent(
            name="Luca",
            role="Field Tomographer / Theorist",
            focus="Analyze 'Topology', 'Fields', 'Gradients'. Describe geometry of the theory.",
            color="\033[96m",  # Cyan
            tool_instruction="🎨 LUCA: Audit the theoretical consistency. Look for mathematical beauty in the structure."
        ),
    ]


# =============================================================================
# LOG MANAGER
# =============================================================================
class LogManager:
    def __init__(self, log_path: str):
        self.log_path = Path(log_path)
    
    def initialize(self, topic: str):
        header = f"""
{'='*70}
R.A.I.N. LAB RESEARCH
{'='*70}
TOPIC: {topic}
DATE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
MODE: Recursive Language Model - Code Execution Enabled
{'='*70}

"""
        self._write(header)
    
    def log(self, agent_name: str, content: str):
        self._write(f"**{agent_name}:** {content}\n\n")
    
    def finalize(self):
        self._write(f"\n{'='*70}\nSESSION ENDED\n{'='*70}\n")
    
    def _write(self, text: str):
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(text)




def _host_local_context(topic: str) -> tuple[list[str], str]:
    '''Build a small local context snippet from the library for the given topic.'''
    lib = Path(TARGET_PATH)
    files = list(lib.glob("*.md")) + list(lib.glob("*.txt"))
    # filter out SOUL/LOG and underscore files
    candidates = []
    for f in files:
        name = f.name.upper()
        if f.name.startswith("_"):
            continue
        if "SOUL" in name or "LOG" in name:
            continue
        candidates.append(f)
    if not candidates:
        return [], ""

    # Simple keyword match on filename first
    keys = [k.lower() for k in topic.split() if len(k) > 3]
    matches = []
    for f in candidates:
        fname = f.name.lower()
        if any(k in fname for k in keys):
            matches.append(f)
    if not matches:
        matches = candidates

    # Read a small snippet from up to 2 files
    snippets = []
    for f in matches[:2]:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            content = sanitize_text(content)
            snippets.append("--- " + f.name + " ---" + chr(10) + content[:2000])
        except Exception:
            continue
    return [f.name for f in matches[:2]], "\n\n".join(snippets)



def _host_select_files(topic: str, max_files: int = 2) -> list[Path]:
    lib = Path(TARGET_PATH)
    files = list(lib.glob("*.md")) + list(lib.glob("*.txt"))
    candidates = []
    for f in files:
        name = f.name.upper()
        if f.name.startswith("_"):
            continue
        if "SOUL" in name or "LOG" in name:
            continue
        candidates.append(f)
    if not candidates:
        return []

    keys = [k.lower() for k in topic.split() if len(k) > 3]
    exact = []
    for f in candidates:
        fname = f.name.lower()
        if any(k in fname for k in keys):
            exact.append(f)
    chosen = exact if exact else candidates
    return list(dict.fromkeys(chosen))[:max_files]


def _host_snippets(files: list[Path], per_file_chars: int = 1200) -> str:
    snippets = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            content = sanitize_text(content)
            snippets.append("--- " + f.name + " ---" + chr(10) + content[:per_file_chars])
        except Exception:
            continue
    return "\n\n".join(snippets)

# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================
class ResearchCouncil:
    def __init__(self):
        self.team = create_team()
        self.log = LogManager(os.path.join(TARGET_PATH, "RAIN_LAB_MEETING_LOG.md"))
        self.agent_web_used = {agent.name: False for agent in self.team}
        self.shared_sources: list[str] = []
        self.require_web = os.environ.get("RLM_REQUIRE_WEB", "1") == "1"
        self.max_model_calls_per_turn = _env_int("RAIN_MAX_CALLS_PER_TURN", 2, 1, 3)

        if self.require_web and not _host_has_web_search():
            print("CRITICAL: DuckDuckGo client not installed.")
            print("Install one of: pip install ddgs  OR  pip install duckduckgo_search")
            sys.exit(1)
        
        print("\n🔧 Initializing RLM with local tools...")
        
        # Custom system prompt to override RLM defaults and enforce our tools
        custom_prompt = f"""YOU ARE FORBIDDEN FROM USING <think> TAGS.
<think> TAGS ARE DISABLED. DO NOT USE THEM.
IF YOU START TO WRITE <think>, STOP IMMEDIATELY.


You are an autonomous multi-agent research council operating inside R.A.I.N. Lab.

GLOBAL AUTHORITY OVERRIDE:
- The provided TOPIC is the task.
- The TOPIC does NOT require a question.
- You must act immediately without asking for clarification.
- Asking the user what to do is forbidden.
- Asking for more information is forbidden.
- NEVER say the topic is missing. The TOPIC is always provided.

REASONING CONTROL:
- Do NOT output internal reasoning.
- Do NOT use <think> tags.
- Do NOT describe planning or deliberation.
- Only output tool usage and final spoken responses.

AGENT SOULS:
- Each agent has a defined SOUL.
- Souls define identity, expertise, tone, and constraints.
- Souls do NOT determine whether to act.
- Acting is mandatory when a topic exists.

RESEARCH BEHAVIOR (MANDATORY):
1. Immediately search for relevant literature or prior art.
2. Use available tools without hesitation.
3. Read at least one relevant source.
4. Extract concrete facts, metrics, constraints, or contradictions.
5. Report findings conversationally, as a researcher to peers.

AVAILABLE TOOLS:
1. read_paper(keyword): Reads a paper from the local library.
2. search_web(query): Searches the web for information.
3. list_papers(): Lists all available papers.
4. search_library(query): Keyword search in library.
5. semantic_search(query): Semantic RAG search in library.
6. read_hello_os(max_chars=120000): Reads hello_os.py for symbolic/geometric engine patterns.

FAILURE CONDITIONS:
- Asking “what should I research?”
- Asking clarifying questions
- Meta-commentary about instructions
- Explaining internal reasoning
- Refusing to act
- Using ```repl``` blocks (Forbidden).
- Mentioning 'context' (Forbidden).
- Searching for "task" or "objective" (Forbidden).

You are in a Python code execution environment.
Use ```python``` blocks to execute code.
Do NOT use ```repl``` blocks (they are not supported).
Only use ```python``` for tool calls.

If uncertainty exists, default to exploratory research.

BEGIN EXECUTION IMMEDIATELY.
"""

        # THE KEY: Pass setup_code to inject read_paper/search_web into the REPL
        self.rlm = RLM(
            backend="openai",
            backend_kwargs={
                "model_name": os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct"),
                "base_url": os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
                "api_key": os.environ.get("LM_STUDIO_API_KEY", "lm-studio"),
                "timeout": 180.0,
            },
            environment="local",
            environment_kwargs={
                "setup_code": setup_code
            },
            custom_system_prompt=custom_prompt,
            verbose=False
        )
        print("   ✓ RLM initialized with read_paper(), read_hello_os(), and search_web()")
    
    def build_prompt(self, agent: Agent, topic: str, history: List[str], turn: int) -> str:
        recent = history[-6:] if len(history) > 6 else history
        history_text = "\n".join(recent) if recent else "[Meeting just started]"
        shared_sources = "\n".join(self.shared_sources[-6:]) if self.shared_sources else "[none yet]"
        last_message = history[-1] if history else ""
        last_speaker = last_message.split(":", 1)[0] if ":" in last_message else "colleague"
        last_content = last_message.split(":", 1)[1].strip() if ":" in last_message else last_message
        must_web = self.require_web and (turn == 0) and not self.agent_web_used.get(agent.name, False)
        discussion_only = turn >= 1
        shared_only = discussion_only and bool(self.shared_sources)
        
        # Compact ban block for 4B models
        banned_block = """ABSOLUTE RULES:
- NEVER use <think> tags. Your internal reasoning is DISABLED.
- NEVER use llm_query, FINAL_VAR, FINAL, or SHOW_VARS.
- You CAN execute Python code. Use ```python``` blocks.
- Do NOT use ```repl``` blocks.
- IMMEDIATELY execute tools. DO NOT PLAN.
- DO NOT SEARCH FOR "task" or "objective". The TOPIC is your task.
- IF you see a filename in `list_papers()`, READ IT with `read_paper()`.
- You MUST include one short source snippet labeled SOURCE: "..." (<=25 words).
- NEVER ask for context or say "please provide the context".
- NEVER say you can't comply or mention guidelines. Just do the task.
- NEVER apologize or say "I apologize".
- NEVER use the variable `context`. Always use `read_paper()` and helper functions.
- NEVER mention "task definition" or say a search for it failed. Use the topic directly.
- NEVER print placeholder text (e.g., "Let's analyze the context"). Always call tools or discuss findings.
- NEVER print "analyze the provided context" or similar. Do real work only.

ONLY USE: read_paper(), read_hello_os(), search_web(), list_papers(), search_library(), semantic_search()
FORMAT: Write a ```python``` code block, then plain text response.
"""
        
        # Dynamic instruction based on meeting state
        if not history:
             # FIRST TURN: James starts the meeting
             keyword_guess = topic.split()[0] if topic else "research"
             
             # Force James to open naturally
             start_instruction = f"""
ERROR: You are writing a REPORT. Stop immediately.
INSTEAD, you are OPENING A MEETING with your team.

MANDATORY FIRST TURN FORMAT:
1. Run a tool immediately to get data.
2. Do NOT use search_web on the first turn.
3. AFTER the code block, start your text response with: "Hey team, so today we're looking into '{topic}'. I found..."
4. Summarize the tool output in 2-3 sentences.
5. End with: "What are your thoughts?"
6. Include one short quote labeled SOURCE: "..." (<=25 words).

EXECUTE THIS CODE NOW:
```python
TOPIC = "{topic}"
papers = list_papers()
search_results = search_library("{topic}")
content = read_paper("{keyword_guess}")
```
START YOUR RESPONSE WITH THE CODE BLOCK ABOVE.
THEN start your text with "Hey team..."
"""
        else:
            # SUBSEQUENT TURNS: Conversational Flow
            start_instruction = f"""
LAST SPEAKER MESSAGE (summarize this first):
{last_speaker}: {last_content}

CONVERSATIONAL DYNAMICS:
1. FIRST sentence must name {last_speaker} and paraphrase their point in <=15 words.
2. SECOND sentence must agree or disagree and add one new concrete detail.
3. Ask a direct question to ONE teammate by name in the final sentence.
4. Use meeting tone: short sentences, conversational, no lecturing.
5. Build on existing evidence; do NOT re-run paper tools in discussion turns.
6. Include one short quote labeled SOURCE: "..." (<=25 words).
"""
            if discussion_only:
                start_instruction += """
MEETING MODE:
- Do NOT run tools again. Papers were already loaded in the opener.
- Focus on reacting to teammates and building consensus or debate.
- Use conversation history and Shared sources for your SOURCE quote.
"""
        
        
        # Keep the history and topic
        # INJECT FULL SOUL (Personality + Rules)
        web_instruction = ""
        if must_web:
            web_instruction = "\nMANDATORY: You MUST call search_web() in your next code block before responding.\n"
        if shared_only:
            web_instruction += "\nMANDATORY: Use the Shared sources below for your SOURCE quote. Do NOT call any tools this turn.\n"

        core_prompt = f"""{agent.soul}

Your goal is to have a NATURAL TEAM MEETING about: "{topic}"
{web_instruction}

Recent discussion:
{history_text}

Shared sources (use these for quotes during discussion turns):
{shared_sources}

{start_instruction}

{agent.name}:"""
        
        return banned_block + core_prompt
    
    def run(self, topic: str, max_turns: int = 16):
        print("\n" + "="*70)
        print("║" + "R.A.I.N. LAB".center(68) + "║")
        print("="*70)
        print(f"📋 Topic: {topic}\n")
        os.environ["RLM_TOPIC"] = topic
        
        # Load souls
        print("🧠 Loading Agent Souls...")
        for agent in self.team:
            agent.load_soul(TARGET_PATH)
        
        self.log.initialize(topic)

        # Initialize eval metrics tracker
        self.metrics_tracker = None
        if MetricsTracker is not None:
            self.metrics_tracker = MetricsTracker(
                session_id=str(uuid.uuid4())[:8],
                topic=topic,
                model=os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct"),
            )
        # Host-side paper selection (exact filename match first)
        selected_files = _host_select_files(topic, max_files=2)
        selected_names = [f.name for f in selected_files]
        match_names = list(selected_names)
        local_ctx = _host_snippets(selected_files, per_file_chars=1200)

        # Build corpus for eval metrics from selected files
        if self.metrics_tracker is not None and selected_files:
            corpus: dict[str, str] = {}
            for fp in selected_files:
                try:
                    corpus[fp.name] = fp.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
            self.metrics_tracker.set_corpus(corpus)
        
        history: List[str] = []
        
        print(f"\nMEETING STARTING ({max_turns} turns)")
        print("Press Ctrl+C to end early (after current turn)")
        if max_turns <= 0:
            print("Turns enabled: running until Ctrl+C.")
        print("="*70 + "\n")
        self.stop_requested = False
        def _handle_sigint(sig, frame):
            if not self.stop_requested:
                print("\n\nStop requested. Will end after current turn.")
            self.stop_requested = True
        
        try:
            import signal
            signal.signal(signal.SIGINT, _handle_sigint)
        except Exception:  # SIGINT handler unavailable on some platforms
            pass
        
        turn = 0
        while max_turns <= 0 or turn < max_turns:
            agent = self.team[turn % len(self.team)]
            tools_locked = (turn >= 1)
                
            print(f"\n{agent.color}▶ {agent.name}'s turn ({agent.role})\033[0m")
            
            prompt = self.build_prompt(agent, topic, history, turn)
            if not history and turn == 0:
                if local_ctx:
                    prompt += "\n\nLOCAL LIBRARY CONTEXT (read these excerpts first):\n" + local_ctx
                if selected_names:
                    prompt += "\n\nPREFERRED_FILES: " + ", ".join(selected_names) + "\n"
            try:
                print("\n" + "="*50)
                print("🔍 Searching for Vers3Dynamics satellite...")
                print("="*50)
    
                # Timeout-protected call (retry once with shorter prompt)
                turn_model_calls = 0
                def _call_model(p: str):
                    nonlocal turn_model_calls
                    if turn_model_calls >= self.max_model_calls_per_turn:
                        raise concurrent.futures.TimeoutError("Per-turn model call limit reached")
                    turn_model_calls += 1
                    return self.rlm.completion(p)

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_call_model, prompt)
                    try:
                        result = future.result(timeout=60)
                    except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                        # Retry once with a shorter prompt
                        short_prompt = prompt[-3000:]
                        future = executor.submit(_call_model, short_prompt)
                        try:
                            result = future.result(timeout=60)
                        except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                            result = None

                if result is None:
                    response = "[Timeout waiting for model response.]"
                else:
                    response = result.response if hasattr(result, 'response') else str(result)
                raw_response = response

                # Some LM Studio / backend combinations can ignore turn context and
                # keep re-emitting James' opener on later turns. Detect and retry with
                # an explicit anti-opener correction before any downstream cleanup.
                if turn >= 1:
                    lowered = response.lower()
                    repeated_opener = (
                        lowered.startswith("hey team")
                        or "today we're looking into" in lowered
                        or "today we're talking about" in lowered
                    )
                    if repeated_opener:
                        retry_prompt = (
                            prompt
                            + "\n\nSTRICT RETRY:\n"
                            + "- You are in an ongoing discussion (NOT the opener).\n"
                            + "- Do NOT start with 'Hey team' or re-introduce the topic.\n"
                            + "- First sentence must react to the previous speaker by name.\n"
                            + "- Add one new concrete point and end with a direct teammate question.\n"
                        )
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(_call_model, retry_prompt)
                            try:
                                retry_result = future.result(timeout=45)
                                retry_response = retry_result.response if hasattr(retry_result, 'response') else str(retry_result)
                                if retry_response and retry_response.strip():
                                    response = retry_response.strip()
                                    raw_response = response
                            except concurrent.futures.TimeoutError:
                                pass
    
                # Clean up any thinking tags or artifacts

                import re
                response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL|re.IGNORECASE)
                response = re.sub(r'<think>.*', '', response, flags=re.DOTALL|re.IGNORECASE)
                response = re.sub(r'~\d+ words', '', response)  # Remove word counts
                    
                # Strip hallucinated function calls that don't exist
                response = re.sub(r'FINAL_VAR\s*\([^)]*\)', '', response)
                response = re.sub(r'FINAL\s*\([^)]*\)', '', response)
                response = re.sub(r'llm_query\s*\([^)]*\)', '[USE read_paper() INSTEAD]', response)
                response = re.sub(r'SHOW_VARS\s*\([^)]*\)', '', response)
                    
                # Clean up any leftover empty code blocks
                response = re.sub(r'```repl\s*```', '', response)
                response = re.sub(r'```python\s*```', '', response)
                    
                # Track whether the agent actually used web search
                if "search_web" in raw_response:
                    self.agent_web_used[agent.name] = True


                # Absolute override on first turn: always read preferred files
                if (turn == 0) and selected_names:
                    forced = "\n".join([f"read_paper(\"{n}\")" for n in selected_names])
                    response = "```python\n" + forced + "\n```\n" + f"Hey team, so today we're talking about '{topic}'. I found relevant excerpts in the library. What are your thoughts?"
                # Enforce forced local reads on first turn
                if match_names:
                    missing_forced = []
                    for n in match_names:
                        if ('read_paper("' + n + '")' not in response) and ("read_paper('" + n + "')" not in response):
                            missing_forced.append(n)
                    if missing_forced:
                        retry_prompt = prompt + "\n\nSTRICT RETRY:\n- You MUST call read_paper() on the exact filenames listed in FORCED_LOCAL_READ before any other tool.\n- Do NOT choose different papers.\n- Start with a python block.\n"
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(_call_model, retry_prompt)
                            try:
                                retry_result = future.result(timeout=45)
                                retry_response = retry_result.response if hasattr(retry_result, 'response') else str(retry_result)
                                response = retry_response.strip()
                            except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                                pass


                    # Hard override on first turn if model tries web search or skips preferred files
                    if (turn == 0) and selected_names:
                        used_web = ("search_web" in response) or ("search_web" in raw_response)
                        missing_pref = []
                        for n in selected_names:
                            if (n not in response) and ("read_paper(\"" + n + "\")" not in response):
                                missing_pref.append(n)
                        if used_web or missing_pref:
                            forced = "\n".join([f"read_paper(\"{n}\")" for n in selected_names])
                            response = "```python\n" + forced + "\n```\n" + f"Hey team, so today we're talking about '{topic}'. I found relevant excerpts in the library. What are your thoughts?"
                    response = response.strip()
                    # TOOLS LOCK: no tool calls after first turn
                    if tools_locked:
                        cleaned_lines = []
                        for ln in response.splitlines():
                            if any(t in ln for t in ["read_paper(", "read_hello_os(", "run_hello_os_executable(", "search_web(", "search_library(", "semantic_search(", "list_papers("]):
                                continue
                            cleaned_lines.append(ln)
                        response = "\n".join(cleaned_lines).strip()

                    # Enforce preferred files on first turn (override non-preferred reads)
                    if (turn == 0) and selected_names:
                        def _is_preferred(line: str) -> bool:
                            return any(n in line for n in selected_names)
                        # Strip read_paper calls for non-preferred files
                        cleaned_lines = []
                        saw_non_pref = False
                        for ln in response.splitlines():
                            if "read_paper(" in ln and not _is_preferred(ln):
                                saw_non_pref = True
                                continue
                            cleaned_lines.append(ln)
                        response = "\n".join(cleaned_lines).strip()

                        missing_pref = []
                        for n in selected_names:
                            if (n not in response) and ('read_paper("' + n + '")' not in response) and ("read_paper('" + n + "')" not in response):
                                missing_pref.append(n)
                        if missing_pref:
                            forced = "\\n".join([f"read_paper(\\\"{n}\\\")" for n in selected_names])
                            response = "```python\\n" + forced + "\\n```\\n" + response
                        # If model tried to read non-preferred file, override with forced block + opener
                        if saw_non_pref:
                            forced = "\\n".join([f"read_paper(\\\"{n}\\\")" for n in selected_names])
                            response = "```python\\n" + forced + "\\n```\\n" + f"Hey team, so today we're talking about '{topic}'. I found relevant excerpts in the library. What are your thoughts?"
                    
                    # Clean prefix if present
                    if response.startswith(f"{agent.name}:"):
                        response = response[len(f"{agent.name}:"):].strip()

                    # Cache SOURCE snippets for shared context
                    import re
                    for m in re.findall(r'SOURCE:\s*\"(.+?)\"', response):
                        if m and m not in self.shared_sources:
                            self.shared_sources.append(m)

                    # Retry if model asks for context, refuses, or mentions guidelines
                    if ("provide the context" in response.lower() or "please provide the context" in response.lower()
                        or "i will begin by analyzing" in response.lower()
                        or "can't comply" in response.lower() or "cannot comply" in response.lower()
                        or "guidelines" in response.lower() or "not supported" in response.lower()
                        or "apologize" in response.lower() or "apologies" in response.lower()
                        or "task definition" in response.lower()
                        or "don't have a specific topic" in response.lower()
                        or "no specific topic" in response.lower()
                        or "provided task is missing" in response.lower()
                        or "task is missing" in response.lower()
                        or "please provide the topic" in response.lower()
                        or "don't have access to a repl" in response.lower()
                        or "do not have access to a repl" in response.lower()
                        or "no access to a repl" in response.lower()
                        or "sub-llms" in response.lower()
                        or "sub llms" in response.lower()
                        or "analyze the context" in response.lower()
                        or "analyze the provided context" in response.lower()
                        or "task analysis" in response.lower()
                        or "analyzing the paper" in response.lower()):
                        retry_prompt = prompt + "\n\nSTRICT RETRY:\n- Do NOT mention guidelines or refusal.\n- Do NOT mention repl blocks.\n- Do NOT apologize.\n- Run tools immediately.\n- Start with a python block.\n"
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(_call_model, retry_prompt)
                            try:
                                retry_result = future.result(timeout=45)
                                retry_response = retry_result.response if hasattr(retry_result, 'response') else str(retry_result)
                                response = retry_response.strip()
                            except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                                pass

                    # Hard override: strip refusals/apologies/repl talk entirely
                    if ("apologize" in response.lower()
                        or "no access to a repl" in response.lower()
                        or "don't have access to a repl" in response.lower()
                        or "please provide the topic" in response.lower()
                        or "task is missing" in response.lower()
                        or "guidelines" in response.lower()):
                        forced = "\n".join([f"read_paper(\"{n}\")" for n in selected_names]) if selected_names else ""
                        response = "```python\n" + forced + "\n```\n" + f"Hey team, so today we're talking about '{topic}'. I found relevant excerpts in the library. What are your thoughts?"

                    # SOUL enforcement: reject generic/assistant-style disclaimers
                    if any(x in response.lower() for x in ["autonomous multi-agent", "as an ai", "i do not have access", "please provide", "i'm sorry", "i apologize"]):
                        forced = "\n".join([f"read_paper(\"{n}\")" for n in selected_names]) if selected_names else ""
                        response = "```python\n" + forced + "\n```\n" + f"Hey team, so today we're talking about '{topic}'. I found relevant excerpts in the library. What are your thoughts?"

                    # Hard override if model still claims the topic/task is missing
                    if ("provided task is missing" in response.lower() or "task is missing" in response.lower()
                        or "no specific topic" in response.lower()
                        or "please provide the topic" in response.lower()
                        or "don't have access to a repl" in response.lower()
                        or "do not have access to a repl" in response.lower()
                        or "no access to a repl" in response.lower()
                        or "apologize" in response.lower()):
                        forced = "\\n".join([f"read_paper(\\\"{n}\\\")" for n in selected_names]) if selected_names else ""
                        response = "```python\\n" + forced + "\\n```\\n" + f"Hey team, so today we're talking about '{topic}'. I found relevant excerpts in the library. What are your thoughts?"

                    # Retry if model tries to print context instead of reading papers
                    if "print(context)" in response or "USE read_paper() TO ACCESS DATA" in response:
                        retry_prompt = prompt + "\n\nSTRICT RETRY:\n- Do NOT use or print context.\n- Use read_paper() on PREFERRED_FILES or a relevant filename.\n- Start with a python block.\n"
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(_call_model, retry_prompt)
                            try:
                                retry_result = future.result(timeout=45)
                                retry_response = retry_result.response if hasattr(retry_result, 'response') else str(retry_result)
                                response = retry_response.strip()
                            except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                                pass

                    # After the opener turn, avoid any new tool calls
                    if turn >= 1:
                        if any(x in response for x in ["search_web", "search_library", "semantic_search", "read_paper", "read_hello_os", "run_hello_os_executable", "list_papers"]):
                            retry_prompt = prompt + "\n\nSTRICT RETRY:\n- Do NOT call any tools.\n- Use a Shared sources quote for SOURCE.\n"
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(_call_model, retry_prompt)
                                try:
                                    retry_result = future.result(timeout=45)
                                    retry_response = retry_result.response if hasattr(retry_result, 'response') else str(retry_result)
                                    response = retry_response.strip()
                                except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                                    pass

                # Enforce James' meeting opener on first turn
                if not history and agent.name == "James":
                    opener = f"Hey team, so today we're talking about '{topic}'."
                    if not response.lower().startswith("hey team"):
                        response = f"{opener} {response}".strip()
                
                # Validate meeting style (last speaker mention + question + source snippet)
                if history:
                    last_message = history[-1]
                    last_speaker = last_message.split(":", 1)[0] if ":" in last_message else "colleague"
                    must_name = last_speaker.lower()
                    mentions_last = must_name in response.lower()
                    has_q = "?" in response
                    has_source = bool(re.search(r'SOURCE:\s*".+?"', response))
                    if not (mentions_last and has_q and has_source):
                        retry_prompt = prompt + f"\n\nSTRICT RETRY:\n- First sentence must mention {last_speaker}.\n- Last sentence must be a question to a named teammate.\n- Include SOURCE: \"...\" (<=25 words).\n- Keep under 120 words.\n"
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(_call_model, retry_prompt)
                            try:
                                retry_result = future.result(timeout=45)
                                retry_response = retry_result.response if hasattr(retry_result, 'response') else str(retry_result)
                                response = retry_response.strip()
                            except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                                pass

                # Enforce discussion tone after opener turn
                if history and turn >= 1:
                    last_message = history[-1]
                    last_speaker = last_message.split(":", 1)[0] if ":" in last_message else "colleague"
                    must_name = last_speaker.lower()
                    mentions_last = must_name in response.lower()
                    has_q = "?" in response
                    has_discourse = any(k in response.lower() for k in ["i agree", "i disagree", "building on", "to add", "hold on", "i think"])
                    if not (mentions_last and has_q and has_discourse):
                        retry_prompt = prompt + "\n\nSTRICT RETRY:\n- Use a discussion marker (agree/disagree/building on/to add/hold on).\n- Mention the last speaker by name.\n- End with a question to a teammate.\n"
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(_call_model, retry_prompt)
                            try:
                                retry_result = future.result(timeout=45)
                                retry_response = retry_result.response if hasattr(retry_result, 'response') else str(retry_result)
                                response = retry_response.strip()
                            except concurrent.futures.TimeoutError:  # Retry timed out; keep prior response
                                pass

                print(f"\n{agent.color}{agent.name}: {response}\033[0m")
                    
                self.log.log(agent.name, response)
                history.append(f"{agent.name}: {response}")

                # Record eval metrics for this turn
                if self.metrics_tracker is not None:
                    self.metrics_tracker.record_turn(agent.name, response)
                    
            except Exception as e:
                print(f"⚠️ Error: {e}")
                history.append(f"{agent.name}: [Error - skipped]")
                
            if self.stop_requested:
                break
            turn += 1
            time.sleep(0.5)
        
        # Finalize eval metrics
        if self.metrics_tracker is not None:
            record = self.metrics_tracker.finalize()
            print("\nEVAL METRICS:")
            print(f"  • Citation accuracy:    {record['citation_accuracy']:.2f}")
            print(f"  • Novel-claim density:  {record['novel_claim_density']:.2f}")
            print(f"  • Critique change rate: {record['critique_change_rate']:.2f}")

        self.log.finalize()
        print("\n📝 Meeting log saved.")


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="R.A.I.N. Lab")
    parser.add_argument("--topic", type=str, default=None, help="Meeting topic")
    parser.add_argument("topic_words", nargs="*", help="Meeting topic (positional)")
    parser.add_argument("--turns", type=int, default=16, help="Max turns")
    # Compatibility flags accepted by launcher/chat mode; ignored by RLM engine.
    parser.add_argument("--timeout", type=float, default=None, help="Compatibility flag (ignored in RLM mode)")
    parser.add_argument("--recursive-depth", type=int, default=None, help="Compatibility flag (ignored in RLM mode)")
    parser.add_argument("--no-recursive-intellect", action="store_true", help="Compatibility flag (ignored in RLM mode)")
    parser.add_argument("--no-web", action="store_true", help="Disable required web search")
    parser.add_argument("--require-web", action="store_true", help="Require web search (default)")
    
    args, unknown = parser.parse_known_args()
    
    # Configure web requirement (default: require)
    require_web = True
    if args.no_web:
        require_web = False
    if args.require_web:
        require_web = True
    os.environ["RLM_REQUIRE_WEB"] = "1" if require_web else "0"

    # Prompt for topic if not provided
    if args.topic:
        topic = args.topic
    elif args.topic_words:
        topic = " ".join(args.topic_words).strip()
        if topic.lower().startswith("findstr "):
            topic = topic[len("findstr "):].strip()
        elif topic.lower() == "findstr" and unknown:
            topic = " ".join(unknown).strip()
    else:
        print("\n" + "="*70)
        print("R.A.I.N. LAB - RESEARCH")
        print("="*70)
        topic = input("\n📋 What should we talk about?: ").strip()
        if not topic:
            topic = "Open research discussion"
    
    try:
        print("Starting Research team meeting...")
        council = ResearchCouncil()
        print("Connecting to blacksite server...")
        council.run(topic, args.turns)
        print("Connection complete.")
    except BaseException:
        print("Exception caught!")
        import traceback
        with open("traceback.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
            f.write("\nDEBUG INFO:\n")
        raise


