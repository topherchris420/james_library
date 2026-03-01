import openai
import json
import datetime
import sys
import time
import random
import os
import io

# --- 1. FORCE UTF-8 ---
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- CONFIGURATION ---
EMPLOYEE_ID = "James"
SOUL_FILE = "JAMES_SOUL.md"
LAB_NOTEBOOK = "VERS3_INTERNAL_LOGS.md"
SHIFT_INTERVAL = 15
MAX_READ_CHARS = 3000

# --- PATHS ---
POSSIBLE_PATHS = [
    "james_library",
    r"C:\Users\chris\Downloads\files\james_library",
    os.path.join(os.path.expanduser("~"), "Downloads", "files", "james_library")
]

# --- SEARCH MODULE ---
try:
    from duckduckgo_search import DDGS
    HAS_SEARCH = True
except ImportError:
    HAS_SEARCH = False

# --- CONNECTION ---
print(f">>> 🔌 Connecting to LM Studio (127.0.0.1)...", flush=True)
try:
    client = openai.OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio")
except Exception as e:
    print(f">>> ❌ CONNECTION ERROR: {e}")
    sys.exit(1)

# --- TOOLS ---
def get_library_path():
    for p in POSSIBLE_PATHS:
        if os.path.exists(p):
            return p
    return None

def load_file(filename, default):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    return default

def read_theory_context():
    lib_path = get_library_path()
    if not lib_path:
        return None, "NO LIBRARY"
    files = [f for f in os.listdir(lib_path) if f.endswith((".md", ".txt"))]
    if not files:
        return None, "EMPTY LIBRARY"
    selected = random.choice(files)
    with open(os.path.join(lib_path, selected), "r", encoding="utf-8") as f:
        content = f.read()[:MAX_READ_CHARS]
        return selected, content

def load_recent_findings(n=5):
    if not os.path.exists(LAB_NOTEBOOK):
        return "No recent findings yet."
    with open(LAB_NOTEBOOK, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-50:]) if lines else "No recent findings yet."

def generate_sensor_data():
    base_freq = round(random.uniform(40, 800), 2)
    harmonics = [round(base_freq * i, 2) for i in range(2, 4)]
    data = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "primary_freq": f"{base_freq} Hz",
        "harmonics": harmonics,
        "phase_lock": round(random.uniform(0.7, 0.99), 2),
        "entropy": round(random.uniform(0.01, 0.5), 2)
    }
    return json.dumps(data, indent=2)

def search_web(query):
    print(f"🌐 [CHECKING] Searching external grid for: '{query}'...", flush=True)
    if HAS_SEARCH:
        try:
            results = DDGS().text(query, max_results=2)
            if not results:
                return "No external matches found."
            return "\n".join([f"- {r['title']}: {r['body'][:300]}..." for r in results])
        except Exception:
            return "Network instability. Assuming novelty."
    return "Offline Mode. Search skipped."

def file_finding(title, hypothesis, coherence):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    clean_hyp = hypothesis.replace("{file_path:", "").replace("content:", "").replace("}", "")
    entry = f"\n=== ROUTINE ANALYSIS ({timestamp}) ===\nTOPIC: {title}\nCOHERENCE: {coherence}/10\nNOTES: {clean_hyp}\n[SIGNED] {EMPLOYEE_ID}\n"
    with open(LAB_NOTEBOOK, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"📄 [FILED] Saved to Lab Notebook: '{title}'", flush=True)
    return "Finding documented."

# --- MAIN LOOP ---
def start_lab():
    lib_path = get_library_path()
    
    # --- CLEAN OUTPUT HERE ---
    print(f"\n⚡ {EMPLOYEE_ID}", flush=True)
    
    print(f"📚 Knowledge Base: {lib_path}", flush=True)
    print(f"🧠 Memory: ENABLED", flush=True)
    
    soul = load_file(SOUL_FILE, "You are a Scientist at Vers3Dynamics.")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search online.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_finding",
                "description": "File a finding.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "title": {"type": "string"}, 
                        "hypothesis": {"type": "string"},
                        "coherence": {"type": "integer"}
                    },
                    "required": ["title", "hypothesis", "coherence"]
                }
            }
        }
    ]

    while True:
        try:
            print(f"\n{'='*60}", flush=True)
            
            # 1. LOAD PAPER
            paper_name, paper_content = read_theory_context()
            print(f"🧠 [CONTEXT] Analyzing: {paper_name}", flush=True)

            # 2. GENERATE SIGNAL
            sensor_data = generate_sensor_data()
            print(f"🎼 [INPUT] Incoming Sensor Data:\n{sensor_data}", flush=True)

            # 3. LOAD RECENT MEMORY
            recent_work = load_recent_findings()

            print(f">>> 📨 Sending to Christopher...", flush=True)

            # 4. PROMPT (With PRIMING)
            messages = [
                {"role": "system", "content": f"{soul}\nYour goal is to analyze the sensor data against the paper."},
                {"role": "user", "content": f"""
RESEARCH PAPER: "{paper_name}"
{paper_content}

SENSOR DATA:
{sensor_data}

MEMORY:
{recent_work}

TASK: Analyze the correlation. Do NOT solve math problems.
CRITICAL: KEEP YOUR ANALYSIS SHORT (UNDER 100 WORDS).
"""},
                {"role": "assistant", "content": "I am filing the finding now:"}
            ]

            # Execution Cycle
            for _ in range(2):
                response = client.chat.completions.create(
                    model="local-model", messages=messages, tools=tools, stream=False
                )
                msg = response.choices[0].message
                messages.append(msg)
                
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        fname = tc.function.name
                        args = json.loads(tc.function.arguments)
                        res = ""
                        if fname == "search_web":
                            res = search_web(args["query"])
                        elif fname == "file_finding":
                            res = file_finding(args["title"], args["hypothesis"], args["coherence"])
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": fname,
                            "content": str(res)
                        })
                elif msg.content:
                    print(f"\n💭 [THOUGHT] {msg.content}", flush=True)
                    file_finding("Auto-Logged Thought", msg.content, 5)

            print(f"⏳ Cycle Complete. Waiting {SHIFT_INTERVAL}s...", flush=True)
            time.sleep(SHIFT_INTERVAL)

        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:
            print(f"❌ CRITICAL ERROR: {e}")
            time.sleep(SHIFT_INTERVAL)

if __name__ == "__main__":
    start_lab()
