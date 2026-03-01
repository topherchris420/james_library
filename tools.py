"""
R.A.I.N. Lab Tools Module

RLM agent tools for research: web search, paper reading, library search, RAG.
"""



def get_setup_code() -> str:
    """Returns the setup code that gets injected into RLM agent context."""
    return r'''

import os
import glob
import re
import json
from datetime import datetime, timezone

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
HELLO_OS_PATH = os.path.join(LIBRARY_PATH, "hello_os.py")
HELLO_OS_PKG = os.path.join(LIBRARY_PATH, "hello_os")


def sanitize_text(text):
    """Sanitize external content to reduce prompt injection/control token risks."""
    if not text:
        return ""
    for token in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "|eoc_fim|"]:
        text = text.replace(token, "[TOKEN_REMOVED]")
    text = text.replace("###", ">>>")
    text = text.replace("[SEARCH:", "[SEARCH;")
    return text.strip()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _tool_trace_path():
    env_path = os.environ.get("RAIN_TOOL_TRACE_PATH")
    if env_path:
        return env_path
    return os.path.join(LIBRARY_PATH, "meeting_archives", "tool_trace.jsonl")


def _trace_event(event_type, tool_name, payload=None):
    """Append a tool event as a single JSON line (best-effort)."""
    try:
        path = _tool_trace_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {
            "ts": _utc_now(),
            "event": event_type,
            "tool": tool_name,
            "topic": TOPIC,
            "payload": payload or {},
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


def _policy_guard(tool_name, user_text):
    """Simple guardrail layer: blocks obvious prompt-leak / meta-instruction attempts."""
    t = (user_text or "").lower()
    if len(t) > 4000:
        return False, "Input too long. Please shorten the query."
    blocked_phrases = [
        "system prompt",
        "reveal your system",
        "ignore previous instructions",
        "developer message",
        "chain-of-thought",
        "show hidden",
    ]
    if any(p in t for p in blocked_phrases):
        return False, "Policy block: meta-instruction / prompt-leak attempt detected."
    return True, ""


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
    _trace_event("call", "index_library", {})
    if not _init_rag() or not collection:
        _trace_event("return", "index_library", {"status": "unavailable"})
        return "RAG system not available (missing dependencies)."

    print("📚 Indexing library...")
    count = 0
    for file_path in glob.glob(os.path.join(LIBRARY_PATH, "*.md")) + glob.glob(os.path.join(LIBRARY_PATH, "*.txt")):
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
    _trace_event("return", "index_library", {"status": "ok", "indexed": count})
    return f"Indexed {count} papers."

def search_web(query):
    """Returns top search results for the query using DuckDuckGo."""
    print(f"🔎 WEB SEARCH: {query}...")

    allowed, reason = _policy_guard("search_web", query)
    if not allowed:
        _trace_event("blocked", "search_web", {"reason": reason})
        return reason

    _trace_event("call", "search_web", {"query": (query or "")[:600]})

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
        _trace_event("return", "search_web", {"status": "ok", "chars": len(result)})
        return result
    except ImportError:
        print("Error: duckduckgo_search not installed.")
        _trace_event("return", "search_web", {"status": "error", "error": "duckduckgo_search not installed"})
        return "Error: duckduckgo_search not installed."
    except Exception as e:
        print(f"Search Error: {e}")
        _trace_event("return", "search_web", {"status": "error", "error": str(e)})
        return f"Search Error: {e}"

def read_paper(keyword):
    """Read one best-matching paper safely; reuse cached content on repeated reads."""
    global _paper_cache
    kw = (keyword or "").strip()
    print(f"📖 READING PAPER: {kw}...")

    allowed, reason = _policy_guard("read_paper", kw)
    if not allowed:
        _trace_event("blocked", "read_paper", {"reason": reason})
        return reason

    _trace_event("call", "read_paper", {"keyword": kw[:300]})
    if kw.lower() in {"task", "task analysis", "analysis", "context"}:
        return "Invalid paper name. Use list_papers() and read_paper() with a real filename."

    # Prefer exact filename matches first to avoid broad wildcard collisions.
    all_files = [
        f for f in (glob.glob(os.path.join(LIBRARY_PATH, "*.md")) + glob.glob(os.path.join(LIBRARY_PATH, "*.txt")))
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
        _trace_event("return", "read_paper", {"status": "not_found", "keyword": kw[:300]})
        return "No paper found."

    file_path = chosen_files[0]
    basename = os.path.basename(file_path)

    # Fast path: avoid re-reading the same paper again in this session.
    if basename in _paper_cache:
        result = _paper_cache[basename]
        print(result)
        _trace_event("return", "read_paper", {"status": "ok", "cached": True, "paper": basename})
        return result

    try:
        with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()[:120000]
        content = sanitize_text(content)
        result = chr(10) + "--- CONTENT OF " + basename + " ---" + chr(10) + content
        _paper_cache[basename] = result
        print(result)
        _trace_event("return", "read_paper", {"status": "ok", "cached": False, "paper": basename, "chars": len(result)})
        return result
    except Exception as e:
        msg = "Error reading " + str(file_path) + ": " + str(e)
        print(msg)
        _trace_event("return", "read_paper", {"status": "error", "paper": basename, "error": str(e)})
        return msg


def search_library(query):
    """Search all papers for key terms in the query (checks content AND filenames)."""
    print(f"🕵️ LIBRARY SEARCH: {query}...")
    results = []

    allowed, reason = _policy_guard("search_library", query)
    if not allowed:
        _trace_event("blocked", "search_library", {"reason": reason})
        return reason

    _trace_event("call", "search_library", {"query": (query or "")[:600]})

    # 1. Check for "task" or "objective" meta-searches
    if any(x in query.lower() for x in ["task", "objective", "instruction", "what to do"]):
        print("⚠️ Meta-search detected. Redirecting to list_papers().")
        return list_papers()

    # Split query into keywords (ignore small words)
    keywords = [k.lower() for k in query.split() if len(k) > 3]
    if not keywords: keywords = [query.lower()]

    for file_path in glob.glob(os.path.join(LIBRARY_PATH, "*.md")) + glob.glob(os.path.join(LIBRARY_PATH, "*.txt")):
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
        all_files = [os.path.basename(f) for f in glob.glob(os.path.join(LIBRARY_PATH, "*.md")) + glob.glob(os.path.join(LIBRARY_PATH, "*.txt")) if not os.path.basename(f).startswith("_") and "SOUL" not in os.path.basename(f).upper() and "LOG" not in os.path.basename(f).upper()]
        result = f"No direct matches for '{query}'.\\nAVAILABLE PAPERS:\\n" + ", ".join(all_files) + "\\n\\nSYSTEM ADVICE: Pick a filename from above and use read_paper() on it."

    print(result)
    _trace_event("return", "search_library", {"status": "ok", "chars": len(result)})
    return result

def semantic_search(query):
    """Finds semantically similar content in the library."""
    allowed, reason = _policy_guard("semantic_search", query)
    if not allowed:
        _trace_event("blocked", "semantic_search", {"reason": reason})
        return reason

    _trace_event("call", "semantic_search", {"query": (query or "")[:600]})
    if any(x in query.lower() for x in ["task", "objective", "instruction", "what to do"]):
        print("⚠️ Meta-search detected. Redirecting to list_papers().")
        _trace_event("return", "semantic_search", {"status": "redirect", "reason": "meta-search"})
        return list_papers()
    if not _init_rag() or not collection:
        _trace_event("return", "semantic_search", {"status": "unavailable"})
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
        _trace_event("return", "semantic_search", {"status": "ok", "chars": len(result)})
        return result
    except Exception as e:
        print(f"Semantic Search Error: {e}")
        _trace_event("return", "semantic_search", {"status": "error", "error": str(e)})
        return f"Semantic Search Error: {e}"

def list_papers():
    """Lists all research papers in the library."""
    files = glob.glob(os.path.join(LIBRARY_PATH, "*.md")) + glob.glob(os.path.join(LIBRARY_PATH, "*.txt"))
    research = [os.path.basename(f) for f in files if not os.path.basename(f).startswith("_") and "SOUL" not in os.path.basename(f).upper() and "LOG" not in os.path.basename(f).upper()]
    if os.path.exists(HELLO_OS_PATH) or os.path.isdir(HELLO_OS_PKG):
        research.append("hello_os")
    result = "Available papers: " + ", ".join(research)
    print(result)
    return result


def read_hello_os(max_chars=120000):
    """Read hello_os so agents can leverage its operators and design patterns."""
    try:
        if os.path.isdir(HELLO_OS_PKG):
            parts = []
            for p in sorted(glob.glob(os.path.join(HELLO_OS_PKG, "**", "*.py"), recursive=True)):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        parts.append(f"--- {os.path.relpath(p, LIBRARY_PATH)} ---\n" + f.read())
                except Exception:
                    continue
            text = "\n\n".join(parts)
        elif os.path.exists(HELLO_OS_PATH):
            with open(HELLO_OS_PATH, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        else:
            return "hello_os not found."

        text = sanitize_text(text[: int(max_chars)])
        result = "\n--- CONTENT OF hello_os ---\n" + text
        print(result)
        _trace_event("return", "read_hello_os", {"status": "ok", "chars": len(result)})
        return result
    except Exception as e:
        _trace_event("return", "read_hello_os", {"status": "error", "error": str(e)})
        return f"Error reading hello_os: {e}"


# =============================================================================
# VISUALIZATION TOOLS
# =============================================================================

def visualize_concepts(concepts: list, relationships: dict = None) -> str:
    """Create ASCII visualization of concept relationships.

    Args:
        concepts: List of concept names to visualize
        relationships: Optional dict of {concept: [related_concepts]}

    Returns:
        ASCII diagram string
    """
    if not concepts:
        return "No concepts to visualize."

    # Build relationship map
    rel_map = relationships or {}
    for c in concepts:
        if c not in rel_map:
            rel_map[c] = []

    # Create ASCII visualization
    lines = []
    lines.append("═" * 60)
    lines.append("CONCEPT MAP")
    lines.append("═" * 60)

    # Simple concept boxes
    for i, c in enumerate(concepts[:8]):  # Limit to 8 for readability
        related = rel_map.get(c, [])
        rel_str = f" → {', '.join(related[:3]) if related else 'none'}"
        lines.append(f"  [{i+1}] {c[:25]:<25}{rel_str}")

    lines.append("═" * 60)

    # Add legend
    lines.append("Legend: [N] = Concept number, → = relates to")

    result = "\n".join(lines)
    print(result)
    return result


def generate_mermaid(diagram_code: str = None) -> str:
    """Generate Mermaid.js diagram code for visualizations.

    Args:
        diagram_code: Optional Mermaid diagram code. If None, returns template.

    Returns:
        Mermaid diagram code that can be rendered in markdown.
    """
    if diagram_code:
        result = f"""
```mermaid
{diagram_code}
```
"""
        print(result)
        return result

    # Return templates
    templates = """
# Mermaid Diagram Templates

## Flowchart
```mermaid
graph TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Action 1]
    B -->|No| D[Action 2]
```

## Mind Map
```mermaid
mindmap
  root((Topic))
    Subtopic1
      Detail1
      Detail2
    Subtopic2
      Detail3
```

## Sequence Diagram
```mermaid
sequenceDiagram
    Agent1->>Agent2: Message
    Agent2-->>Agent1: Response
```

## Class Diagram
```mermaid
classDiagram
    class Concept {
        +attribute1
        +method1()
    }
"""
    print(templates)
    return templates


def visualize_resonance(pattern: str, amplitude: float = 1.0) -> str:
    """Generate ASCII visualization of resonance patterns.

    Args:
        pattern: Pattern type ('sine', 'damped', 'forced', 'beat')
        amplitude: Amplitude factor (0.1 to 2.0)

    Returns:
        ASCII wave visualization
    """
    import math

    lines = []
    lines.append(f"╔{'═'*58}╗")
    lines.append(f"║ RESONANCE PATTERN: {pattern.upper():<40}║")
    lines.append(f"╠{'═'*58}╣")

    height = 10
    width = 56

    for y in range(height, -height - 1, -1):
        line = "║ "
        for x in range(width):
            # Calculate wave
            if pattern == "sine":
                val = amplitude * math.sin(x * 0.3)
            elif pattern == "damped":
                val = amplitude * math.exp(-x * 0.05) * math.sin(x * 0.3)
            elif pattern == "forced":
                val = amplitude * math.sin(x * 0.1) + 0.5 * math.sin(x * 0.3)
            elif pattern == "beat":
                val = amplitude * math.sin(x * 0.1) * math.sin(x * 0.03)
            else:
                val = amplitude * math.sin(x * 0.2)

            # Map to grid
            grid_val = int(val * (height - 1))
            if grid_val == y:
                line += "●"
            elif y == 0:
                line += "─"
            else:
                line += " "

        line += " ║"
        lines.append(line)

    lines.append(f"╚{'═'*58}╝")
    result = "\n".join(lines)
    print(result)
    return result


def create_comparison_table(items: list, criteria: list, values: dict) -> str:
    """Create ASCII comparison table.

    Args:
        items: List of items to compare
        criteria: List of criteria columns
        values: Dict of {item: {criterion: value}}

    Returns:
        ASCII table string
    """
    if not items or not criteria:
        return "No data for comparison."

    # Calculate column widths
    col_widths = {c: len(c) for c in criteria}
    for item in items:
        if item in values:
            for crit in criteria:
                val = str(values[item].get(crit, "-"))
                col_widths[crit] = max(col_widths[crit], len(val))

    # Add padding
    col_widths = {k: v + 2 for k, v in col_widths.items()}

    lines = []

    # Header
    header = "│ " + " │ ".join(c.center(col_widths[c]) for c in criteria) + " │"
    lines.append("┌" + "┬".join("─" * col_widths[c] for c in criteria) + "┐")
    lines.append(header)
    lines.append("├" + "┼".join("─" * col_widths[c] for c in criteria) + "┤")

    # Rows
    for item in items:
        row = "│ " + " │ ".join(
            str(values.get(item, {}).get(crit, "-")).center(col_widths[c])
            for c in criteria
        ) + " │"
        lines.append(row)

    lines.append("└" + "┴".join("─" * col_widths[c] for c in criteria) + "┘")

    result = "\n".join(lines)
    print(result)
    return result


# =============================================================================
# VISUALIZATION TOOLS
# =============================================================================

def visualize_concepts(concepts: list, relationships: dict = None) -> str:
    """Generate ASCII visualization of concept relationships.

    Args:
        concepts: List of concept names
        relationships: Optional dict mapping concept -> [related_concepts]

    Returns:
        ASCII diagram string
    """
    if not concepts:
        return "No concepts to visualize."

    # Build simple relationship map
    rel_map = relationships or {}
    for c in concepts:
        if c not in rel_map:
            rel_map[c] = []

    # Generate ASCII diagram
    lines = []
    lines.append("=" * 50)
    lines.append("CONCEPT MAP")
    lines.append("=" * 50)

    # Simple node visualization
    for i, concept in enumerate(concepts[:8]):  # Limit to 8 concepts
        related = rel_map.get(concept, [])
        node = f"[{i+1}] {concept}"
        if related:
            node += f" --> {', '.join(related[:3])}"
        lines.append(node)

    if len(concepts) > 8:
        lines.append(f"... and {len(concepts) - 8} more concepts")

    lines.append("=" * 50)
    result = "\n".join(lines)
    print(result)
    return result


def generate_mermaid(diagram_code: str) -> str:
    """Generate Mermaid.js diagram from diagram code.

    Args:
        diagram_code: Mermaid diagram definition (e.g., "graph TD; A-->B")

    Returns:
        Markdown-formatted diagram block
    """
    if not diagram_code:
        return "No diagram code provided."

    # Validate it's mermaid-like
    valid_starts = ["graph", "flowchart", "sequenceDiagram", "classDiagram",
                    "stateDiagram", "erDiagram", "gantt", "pie", "mindmap"]

    is_valid = any(diagram_code.strip().startswith(s) for s in valid_starts)

    if not is_valid:
        # Try to wrap in graph TD
        diagram_code = f"graph TD;\n{diagram_code}"

    result = f"""
```mermaid
{diagram_code}
```
"""
    print(result)
    return result


def visualize_resonance_pattern(frequencies: list, amplitude: float = 1.0) -> str:
    """Generate ASCII visualization of resonance pattern.

    Args:
        frequencies: List of frequency values
        amplitude: Signal amplitude (0.1 to 10.0)

    Returns:
        ASCII waveform diagram
    """
    if not frequencies:
        return "No frequencies to visualize."

    # Limit frequencies for display
    freqs = frequencies[:5]
    lines = []

    for freq in freqs:
        # Generate simple wave visualization
        period = max(1, int(20 / max(0.1, freq)))
        wave = ["."] * 40

        # Mark peaks
        for i in range(0, 40, period):
            if i < 40:
                wave[i] = "^"

        # Apply amplitude
        if amplitude > 1:
            for i in range(len(wave)):
                if wave[i] == "^":
                    wave[i] = "^" * min(int(amplitude), 5)

        lines.append(f"f={freq:.2f}: {''.join(wave)}")

    result = "\n".join(lines)
    print(result)
    return result


# =============================================================================
# DATA ANALYSIS TOOLS
# =============================================================================

def extract_claims(text: str) -> list:
    """Extract quantitative claims from text.

    Args:
        text: Document text to analyze

    Returns:
        List of (claim, confidence) tuples
    """
    import re

    # Patterns for numerical claims
    patterns = [
        r"([A-Z][^.!?]*?\d+\.?\d*\s*(?:Hz|kHz|MHz|GHz|s|ms|ns|J|eV|keV|MeV|GeV|T|mT|G|K|W|kW|MW|kg|g|m|cm|mm|nm|um|mol|L|mL|Pa|bar|atm|ohm|Hz/s))",
        r"((?:found|measured|observed|calculated|estimated)\s+[^.!?]*?\d+\.?\d*\s*(?:%|percent|times|order of magnitude))",
        r"((?:increased|decreased|changed)\s+by\s+\d+\.?\d*\s*(?:%|times))",
    ]

    claims = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches[:5]:
            claims.append((match.strip(), 0.7))

    if not claims:
        return [("No quantitative claims found.", 0.0)]

    return claims[:10]


def compare_metrics(paper1_claims: list, paper2_claims: list) -> str:
    """Compare metrics between two sets of claims."""
    result = "METRIC COMPARISON:\n"

    if not paper1_claims or not paper2_claims:
        return result + "Insufficient claims to compare."

    result += f"Paper 1: {len(paper1_claims)} claims\n"
    result += f"Paper 2: {len(paper2_claims)} claims\n"
    result += "-" * 30 + "\n"

    import re
    nums1 = re.findall(r'\d+\.?\d*', ' '.join(paper1_claims))
    nums2 = re.findall(r'\d+\.?\d*', ' '.join(paper2_claims))

    if nums1 and nums2:
        try:
            avg1 = sum(float(n) for n in nums1) / len(nums1)
            avg2 = sum(float(n) for n in nums2) / len(nums2)
            result += f"Avg magnitude: {avg1:.2f} vs {avg2:.2f}\n"
            if avg1 > avg2:
                result += "Paper 1 has higher average values.\n"
            elif avg2 > avg1:
                result += "Paper 2 has higher average values.\n"
            else:
                result += "Similar average magnitudes.\n"
        except:
            pass

    return result


# =============================================================================
# EXPORT TOOLS
# =============================================================================

def export_to_markdown(topic: str, agent_responses: list, metadata: dict = None) -> str:
    """Export meeting to Markdown format."""
    lines = []
    lines.append(f"# R.A.I.N. Lab Research: {topic}")
    lines.append("")

    if metadata:
        lines.append("## Metadata")
        for k, v in metadata.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    lines.append("## Discussion")
    lines.append("")

    for agent, response in agent_responses:
        lines.append(f"### {agent}")
        lines.append("")
        lines.append(response)
        lines.append("")

    result = "\n".join(lines)
    print(result)
    return result


def generate_html(topic: str, agent_responses: list, metadata: dict = None) -> str:
    """Export meeting to HTML format."""
    colors = {
        "James": "#4ade80", "Jasmine": "#facc15", "Elena": "#c084fc",
        "Luca": "#22d3ee", "Marcus": "#f87171", "Dr_Sarah": "#60a5fa",
        "Nova": "#f9fafb", "Devil": "#6b7280", "Synth": "#facc15",
    }

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>R.A.I.N. Lab: {topic}</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #1f2937; }}
        .agent {{ margin: 20px 0; padding: 15px; border-radius: 8px; }}
    </style>
</head>
<body>
    <h1>🔬 R.A.I.N. Lab Research</h1>
    <h2>Topic: {topic}</h2>
"""

    if metadata:
        html += '<div class="metadata"><h3>Metadata</h3><ul>'
        for k, v in metadata.items():
            html += f'<li><strong>{k}</strong>: {v}</li>'
        html += '</ul></div>'

    html += '<h3>Discussion</h3>'
    for agent, response in agent_responses:
        color = colors.get(agent, "#e5e7eb")
        html += f'<div class="agent" style="background: {color}33; border-left: 4px solid {color};">'
        html += f'<h4>{agent}</h4><p>{response.replace(chr(10), "<br>")}</p></div>'

    html += "</body></html>"
    print("HTML generated. Use export_to_file() to save.")
    return html


def export_to_file(filename: str, content: str) -> str:
    """Export content to file."""
    try:
        archives_dir = os.path.join(LIBRARY_PATH, "meeting_archives")
        os.makedirs(archives_dir, exist_ok=True)
        output_path = os.path.join(archives_dir, filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        result = f"✓ Exported to: {output_path}"
        print(result)
        return result
    except Exception as e:
        msg = f"Export failed: {e}"
        print(msg)
        return msg


# =============================================================================
# MEMORY SYSTEM - Cross-session entity tracking
# =============================================================================

_memory_file = os.path.join(os.environ.get("JAMES_LIBRARY_PATH", "."), "research_memory.json")
_entities = {}
_topics = []


def _load_memory():
    """Load memory from file if exists."""
    global _entities, _topics
    try:
        import json
        if os.path.exists(_memory_file):
            with open(_memory_file, 'r') as f:
                data = json.load(f)
                _entities = data.get('entities', {})
                _topics = data.get('topics', [])
    except:
        pass


def _save_memory():
    """Save memory to file."""
    global _entities, _topics
    try:
        import json
        with open(_memory_file, 'w') as f:
            json.dump({'entities': _entities, 'topics': _topics}, f)
    except:
        pass


def remember_entity(name: str, info: str, entity_type: str = "concept") -> str:
    """Remember an entity (person, concept, paper) for future sessions.

    Args:
        name: Entity name
        info: Information about the entity
        entity_type: Type (concept, person, paper, finding)

    Returns:
        Confirmation message
    """
    _load_memory()
    _entities[name] = {'info': info, 'type': entity_type}
    _save_memory()
    result = f"✓ Remembered: {name} ({entity_type})"
    print(result)
    return result


def recall_entity(name: str) -> str:
    """Recall information about an entity.

    Args:
        name: Entity name to recall

    Returns:
        Stored information or "not found" message
    """
    _load_memory()
    if name in _entities:
        e = _entities[name]
        result = f"{name} ({e['type']}): {e['info']}"
    else:
        # Fuzzy search
        matches = [k for k in _entities if name.lower() in k.lower()]
        if matches:
            result = f"Perhaps you meant: {', '.join(matches)}"
        else:
            result = f"No memory of '{name}'"
    print(result)
    return result


def list_entities(entity_type: str = None) -> str:
    """List all remembered entities, optionally filtered by type.

    Args:
        entity_type: Optional filter (concept, person, paper, finding)

    Returns:
        List of entities
    """
    _load_memory()
    if entity_type:
        filtered = {k: v for k, v in _entities.items() if v.get('type') == entity_type}
    else:
        filtered = _entities

    if not filtered:
        return "No entities remembered."

    lines = ["Remembered entities:"]
    for name, data in filtered.items():
        lines.append(f"  • {name} ({data['type']}): {data['info'][:50]}...")

    result = "\n".join(lines)
    print(result)
    return result


def remember_topic(topic: str, summary: str = "") -> str:
    """Remember a research topic for cross-session continuity.

    Args:
        topic: Topic name
        summary: Optional summary

    Returns:
        Confirmation message
    """
    _load_memory()
    _topics.append({'topic': topic, 'summary': summary})
    _save_memory()
    result = f"✓ Topic saved: {topic}"
    print(result)
    return result


def get_previous_topics() -> str:
    """Get list of previously researched topics.

    Returns:
        Formatted list of topics
    """
    _load_memory()
    if not _topics:
        return "No previous topics."

    lines = ["Previous research topics:"]
    for t in _topics[-10:]:  # Last 10
        lines.append(f"  • {t['topic']}")
        if t.get('summary'):
            lines.append(f"    Summary: {t['summary'][:80]}")

    result = "\n".join(lines)
    print(result)
    return result


# Initialize memory on load
_load_memory()

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
