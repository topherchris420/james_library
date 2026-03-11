import os
import glob
import shutil

repo_dir = r"c:\Users\chris\Downloads\james_library"
papers_dir = os.path.join(repo_dir, "papers")

if not os.path.exists(papers_dir):
    os.makedirs(papers_dir)

# Move papers
md_files = glob.glob(os.path.join(repo_dir, "*.md"))
txt_files = glob.glob(os.path.join(repo_dir, "*.txt"))

ignore_files = [
    "AGENTS.md", "ARCHITECTURE.md", "CHANGELOG.md", "CLAUDE.md", "CODE_REVIEW.md", "CONTRIBUTING.md",
    "ELENA_SOUL.md", "JAMES_SOUL.md", "JASMINE_SOUL.md", "LUCA_SOUL.md", "PRODUCT_ROADMAP.md",
    "RAIN_LAB_MEETING_LOG.md", "README.md", "README_JAMES_READER.md", "README_SIMPLE.md",
    "RELEASE_CHECKLIST.md", "SECURITY.md"
]

ignore_txt = [
    "requirements.txt", "requirements-dev.txt", "requirements-pinned.txt",
    "requirements-dev-pinned.txt", "requirements-lock.txt", "requirements-reader.txt"
]

for f in md_files:
    basename = os.path.basename(f)
    if basename not in ignore_files:
        print(f"Moving {basename} to papers/")
        shutil.move(f, os.path.join(papers_dir, basename))
        
for f in txt_files:
    basename = os.path.basename(f)
    if basename not in ignore_txt:
        print(f"Moving {basename} to papers/")
        shutil.move(f, os.path.join(papers_dir, basename))

# Refactor tools.py
tools_path = os.path.join(repo_dir, "tools.py")
with open(tools_path, "r", encoding="utf-8") as f:
    content = f.read()

# Define the new get_setup_code
new_get_setup = """import os
import sys

def get_setup_code() -> str:
    \"\"\"Returns the setup code that gets injected into RLM agent context.\"\"\"
    with open(__file__, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "# --- SETUP CODE BEGINS HERE ---" in content and "# --- SETUP CODE ENDS HERE ---" in content:
        setup_block = content.split("# --- SETUP CODE BEGINS HERE ---", 1)[1].split("# --- SETUP CODE ENDS HERE ---", 1)[0]
        # Auto-execute initialization inside RLM context
        return setup_block + "\\n\\n_run_initialization()\\n"
    return ""

# --- SETUP CODE BEGINS HERE ---
"""

# Extract the body of the raw string
start_idx = content.find("r'''") + 4
end_idx = content.find("'''", start_idx)

body = content[start_idx:end_idx]

# Remove the r''' and '''
# Replace get_setup_code entirely
# Find where get_setup_code starts: `def get_setup_code() -> str:`
start_def = content.find("def get_setup_code() -> str:")
end_def = end_idx + 3

# Wrap the initialization logic in a function so it doesn't auto-run on import
body = body.replace('''# Initialize on startup (best effort)
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
    index_library()''', '''def _run_initialization():
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
        index_library()''')


new_content = content[:start_def] + new_get_setup + body + "\n# --- SETUP CODE ENDS HERE ---\n" + content[end_def:]

with open(tools_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("Refactored tools.py!")
