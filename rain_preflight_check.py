"""
R.A.I.N. LAB PRE-FLIGHT DIAGNOSTIC
Verifies all prerequisites before running rain_lab_meeting.py
"""

import sys
import os
import glob
from pathlib import Path
import io

# Force UTF-8 for Windows consoles
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ANSI color codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

def print_header(text):
    print(f"\n{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}{text.center(70)}{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}\n")

def print_success(text):
    print(f"{GREEN}✓ {text}{RESET}")

def print_warning(text):
    print(f"{YELLOW}⚠ {text}{RESET}")

def print_error(text):
    print(f"{RED}✗ {text}{RESET}")

def print_info(text):
    print(f"{BLUE}ℹ {text}{RESET}")

# Target library path — honour the env-var, then fall back to the repo root.
LIBRARY_PATH = os.environ.get(
    "JAMES_LIBRARY_PATH",
    os.path.dirname(os.path.abspath(__file__)),
)

print_header("R.A.I.N. LAB PRE-FLIGHT CHECK")
print(f"Target library: {LIBRARY_PATH}\n")

all_checks_passed = True

# =============================================================================
# CHECK 1: LIBRARY PATH EXISTS
# =============================================================================
print(f"{BOLD}[1/6] Checking Library Path...{RESET}")
if os.path.exists(LIBRARY_PATH):
    print_success(f"Library path exists: {LIBRARY_PATH}")
else:
    print_error(f"Library path NOT found: {LIBRARY_PATH}")
    print_info("Create this directory or update LIBRARY_PATH in rain_lab_meeting.py")
    all_checks_passed = False

# =============================================================================
# CHECK 2: SOUL FILES
# =============================================================================
print(f"\n{BOLD}[2/6] Checking Soul Files...{RESET}")
required_souls = ["JAMES_SOUL.md", "JASMINE_SOUL.md", "ELENA_SOUL.md", "LUCA_SOUL.md"]
missing_souls = []

for soul_file in required_souls:
    soul_path = os.path.join(LIBRARY_PATH, soul_file)
    if os.path.exists(soul_path):
        print_success(f"Found: {soul_file}")
    else:
        print_error(f"Missing: {soul_file}")
        missing_souls.append(soul_file)
        all_checks_passed = False

if missing_souls:
    print_warning(f"Missing {len(missing_souls)} soul file(s). Agents will use fallback personalities.")

# =============================================================================
# CHECK 3: RESEARCH PAPERS
# =============================================================================
print(f"\n{BOLD}[3/6] Checking Research Papers...{RESET}")
md_files = glob.glob(os.path.join(LIBRARY_PATH, "*.md"))
txt_files = glob.glob(os.path.join(LIBRARY_PATH, "*.txt"))

# Filter out soul files and log files
research_papers = [
    f for f in (md_files + txt_files)
    if "SOUL" not in f.upper() and "LOG" not in f.upper()
]

if research_papers:
    print_success(f"Found {len(research_papers)} research paper(s):")
    for paper in research_papers[:5]:  # Show first 5
        print(f"  • {os.path.basename(paper)}")
    if len(research_papers) > 5:
        print(f"  • ... and {len(research_papers) - 5} more")
    
    # Check specifically for Guarino papers
    guarino_papers = [p for p in research_papers if "guarino" in p.lower()]
    if guarino_papers:
        print_success(f"Found {len(guarino_papers)} Guarino paper(s)")
    else:
        print_warning("No Guarino papers found (topic mentioned in your query)")
else:
    print_warning("No research papers found in library")
    print_info("The agents will only be able to use web search")

# =============================================================================
# CHECK 4: RLM LIBRARY
# =============================================================================
print(f"\n{BOLD}[4/6] Checking RLM Library...{RESET}")

# Try multiple possible locations
rlm_paths = [
    os.path.join(LIBRARY_PATH, "rlm"),
    os.path.join(LIBRARY_PATH, "rlm-main"),
    os.path.join(LIBRARY_PATH, "rlm-main", "rlm-main"),
]

rlm_found = False
for rlm_path in rlm_paths:
    if os.path.exists(rlm_path):
        print_success(f"RLM directory found: {rlm_path}")
        rlm_found = True
        
        # Check if we can actually import it
        sys.path.insert(0, rlm_path)
        try:
            from rlm import RLM
            print_success("RLM module imports successfully")
            break
        except ImportError as e:
            print_error(f"RLM directory exists but import failed: {e}")
            all_checks_passed = False
            break

if not rlm_found:
    print_error("RLM library not found in expected locations")
    print_info("Install RLM in one of these locations:")
    for path in rlm_paths:
        print(f"  • {path}")
    all_checks_passed = False

# =============================================================================
# CHECK 5: PYTHON DEPENDENCIES
# =============================================================================
print(f"\n{BOLD}[5/6] Checking Python Dependencies...{RESET}")

dependencies = {
    "duckduckgo-search": "ddgs",  # package name : import name
}

for package, import_name in dependencies.items():
    try:
        __import__(import_name)
        print_success(f"{package} installed")
    except ImportError:
        print_error(f"{package} NOT installed")
        print_info(f"Install with: pip install {package}")
        all_checks_passed = False

# =============================================================================
# CHECK 6: LM STUDIO API
# =============================================================================
print(f"\n{BOLD}[6/6] Checking LM Studio API...{RESET}")

try:
    import requests
    import json
    
    api_url = "http://127.0.0.1:1234/v1/models"
    
    try:
        response = requests.get(api_url, timeout=5)
        
        if response.status_code == 200:
            print_success("LM Studio API is running")
            
            try:
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    model_name = data["data"][0].get("id", "unknown")
                    print_success(f"Model loaded: {model_name}")
                else:
                    print_warning("API responding but no model loaded")
                    print_info("Load a model in LM Studio (13B+ recommended)")
            except json.JSONDecodeError:
                print_warning("API responding but returned invalid JSON")
        else:
            print_error(f"LM Studio API returned status {response.status_code}")
            all_checks_passed = False
    
    except requests.exceptions.ConnectionError:
        print_error("Cannot connect to LM Studio at http://127.0.0.1:1234")
        print_info("Start LM Studio and ensure it's running on port 1234")
        all_checks_passed = False
    
    except requests.exceptions.Timeout:
        print_error("LM Studio API request timed out")
        all_checks_passed = False

except ImportError:
    print_warning("'requests' library not installed - skipping API check")
    print_info("Install with: pip install requests")

# =============================================================================
# CHECK 7: UTF-8 ENCODING TEST
# =============================================================================
print(f"\n{BOLD}[7/7] Testing UTF-8 Encoding...{RESET}")

test_chars = "ΨG π² μ η σ α β Ω"
try:
    print(f"Test characters: {test_chars}")
    print_success("UTF-8 encoding working correctly")
except UnicodeEncodeError:
    print_error("UTF-8 encoding failed")
    print_info("Run with: python -X utf8 rain_lab_meeting.py")
    all_checks_passed = False

# =============================================================================
# FINAL SUMMARY
# =============================================================================
print_header("PRE-FLIGHT SUMMARY")

if all_checks_passed:
    print(f"{GREEN}{BOLD}✓ ALL SYSTEMS GO{RESET}")
    print(f"\n{BLUE}Ready to launch R.A.I.N. Lab meeting:{RESET}")
    print(f"  cd \"{LIBRARY_PATH}\"")
    print(f"  python -X utf8 rain_lab_meeting.py")
    print(f"\n{BLUE}When prompted, enter topic:{RESET} Guarino Metric")
else:
    print(f"{RED}{BOLD}✗ PRE-FLIGHT FAILED{RESET}")
    print(f"\n{YELLOW}Fix the issues above before running the meeting.{RESET}")
    print(f"\n{BLUE}Common fixes:{RESET}")
    print(f"  • Install RLM: Download from GitHub and place in {LIBRARY_PATH}")
    print(f"  • Install dependencies: pip install duckduckgo-search requests")
    print(f"  • Start LM Studio: Ensure it's running on port 1234")
    print(f"  • Copy soul files: Move JAMES_SOUL.md, etc. to {LIBRARY_PATH}")

print("\n")
sys.exit(0 if all_checks_passed else 1)
