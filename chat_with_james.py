import sys
import io
import os

# Add the RLM library to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "rlm-main", "rlm-main"))

from rlm import RLM

# --- 1. FORCE UTF-8 ---
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- CONFIGURATION ---
LIBRARY_PATH = os.environ.get("JAMES_LIBRARY_PATH", os.path.dirname(__file__))
MODEL_NAME = os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct")
BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
MAX_PAPER_CHARS = 6000  # Limits paper size to fit in context

# --- INITIALIZE RLM ---
james_rlm = RLM(
    backend="openai",
    backend_kwargs={
        "model_name": MODEL_NAME,
        "base_url": BASE_URL
    },
    environment="local",  # Allows code execution on your machine
    verbose=True,  # Shows chain-of-thought and code execution
)

# --- LOCATE THE SOUL ---
soul_paths = [
    os.path.join(LIBRARY_PATH, "JAMES_SOUL.md"),
    r"james_library\JAMES_SOUL.md",
    r"JAMES_SOUL.md"
]

james_personality = "You are James, a visionary scientist at Vers3Dynamics. You are intense, curious, and precise."

for path in soul_paths:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            james_personality = f.read()
        print(f"🧬 Soul Loaded from: {path}")
        break

print(f"\n⚡ James is listening. (RLM Mode - Can execute Python code!)")
print(f"Commands:\n  /list  -> Show available research papers")
print(f"  /read [name] -> Load a paper into James's memory (e.g., '/read friction')")
print(f"  quit   -> Exit\n")

# --- BUILD CONTEXT ---
# RLM uses a single prompt approach, so we'll build context as a string
base_context = f"""INTERNAL SYSTEM COMMAND: Activate Persona 'JAMES'.

PROFILE:
{james_personality}

USER: Christopher (Lead Researcher).

INSTRUCTION: Stay in character. You have access to a library. When the user loads a paper, analyze it.
You can write and execute Python code to perform calculations, analysis, or any other task.
When asked to calculate or compute something, write Python code to do so.
"""

# Track conversation history and loaded papers
conversation_history = []
loaded_papers = []


def list_papers():
    if not os.path.exists(LIBRARY_PATH):
        return "❌ Library folder not found."
    files = [f for f in os.listdir(LIBRARY_PATH) if f.endswith((".md", ".txt"))]
    if not files:
        return "❌ Library is empty."
    return "\n".join([f"📄 {f}" for f in files])


def read_paper(keyword):
    if not os.path.exists(LIBRARY_PATH):
        return None, "Library not found."
    
    files = [f for f in os.listdir(LIBRARY_PATH) if f.endswith((".md", ".txt"))]
    # Find best match
    match = next((f for f in files if keyword.lower() in f.lower()), None)
    
    if match:
        with open(os.path.join(LIBRARY_PATH, match), "r", encoding="utf-8") as f:
            content = f.read()[:MAX_PAPER_CHARS]  # Truncate to fit context
        return match, content
    return None, "File not found."


def build_prompt(user_message):
    """Build the full prompt including context, papers, and conversation history."""
    prompt_parts = [base_context]
    
    # Add loaded papers
    if loaded_papers:
        prompt_parts.append("\n--- LOADED RESEARCH PAPERS ---")
        for paper_name, paper_content in loaded_papers:
            prompt_parts.append(f"\n[{paper_name}]:\n{paper_content}\n")
    
    # Add recent conversation history (limit to last 10 exchanges to manage context)
    if conversation_history:
        prompt_parts.append("\n--- CONVERSATION HISTORY ---")
        for role, content in conversation_history[-20:]:  # Last 10 exchanges (20 messages)
            prefix = "Christopher" if role == "user" else "James"
            prompt_parts.append(f"\n{prefix}: {content}")
    
    # Add current user message
    prompt_parts.append(f"\nChristopher: {user_message}")
    prompt_parts.append("\nJames:")
    
    return "\n".join(prompt_parts)


while True:
    try:
        user_input = input("\n👤 Christopher: ")
        if user_input.lower() in ["quit", "exit"]:
            break
        
        # --- COMMAND HANDLING ---
        if user_input.lower() == "/list":
            print(f"\n📚 Library Contents:\n{list_papers()}")
            continue

        if user_input.lower().startswith("/read"):
            keyword = user_input.replace("/read", "").strip()
            if not keyword:
                print("⚠️ Please specify a name (e.g., '/read friction')")
                continue
            
            fname, content = read_paper(keyword)
            if fname:
                print(f"📖 Reading '{fname}' into memory...", end="", flush=True)
                loaded_papers.append((fname, content))
                print(" Done.")
                # Auto-prompt James to acknowledge the paper
                user_input = f"I have just loaded the paper '{fname}'. Please analyze it briefly."
            else:
                print(f"❌ Could not find a paper matching '{keyword}'")
                continue

        # --- NORMAL CHAT WITH RLM ---
        conversation_history.append(("user", user_input))
        
        print("⚡ James: ", end="", flush=True)
        
        # Build the full prompt and send to RLM
        full_prompt = build_prompt(user_input)
        result = james_rlm.completion(full_prompt)
        
        # Get the response
        response = result.response if hasattr(result, 'response') else str(result)
        
        print(response)
        
        conversation_history.append(("assistant", response))
        
    except KeyboardInterrupt:
        break

print("\n👋 James signing off.")
