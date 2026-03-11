# 🌧️ Vers3Dynamics R.A.I.N. - Novelty Detection System

## The Simple Version - Exactly As Specified

This is the **streamlined implementation** of your exact requirements for preventing "wheel reinvention."

---

## The Problem It Solves

**Before**: AI might "discover" things you already know (like your Resonance Capsule) or well-known phenomena (like Chladni patterns) and claim them as new.

**After**: AI uses **3-tier triangulation**:
1. ✓ Check YOUR internal knowledge base
2. ✓ Search online databases  
3. ✓ Only claim "unique prior art" if NOT found in either

---

## Quick Setup (PowerShell)

```powershell
# Run the installer
.\INSTALL_RAIN.ps1
```

This creates:
- `VERS3_KNOWLEDGE.txt` - Your internal reference manual
- `rain_unique.py` - The AI scientist

---

## Manual Setup (3 Steps)

### Step 1: Create Knowledge Base

Create `VERS3_KNOWLEDGE.txt`:

```text
=== VERS3DYNAMICS INTERNAL KNOWLEDGE BASE ===

CORE PHILOSOPHY:
- We focus on "Resonant Intelligence" and "Recursive Architecture for Intelligent Nexus" (R.A.I.N.).
- We believe sound is a heuristic signal for complex system geometry.

EXISTING PROJECTS (DO NOT CLAIM AS NEW):
1. Vers3 Resonance Capsule: A tool translating spatial data into sound/visuals.
2. Quantum Field Tamer: A retro-style simulation of field interactions.
3. ATOM Framework: Our proprietary method for dynamic resonance rooting.

KEY TERMINOLOGY:
- "Dynamic Resonance Rooting": The process of stabilizing a frequency into a geometric form.
- "Cymatic coherence": The measure of how stable a standing wave is (0.0 to 1.0).

RESEARCH GOALS:
- Find frequencies that exhibit "Hyper-Stability" (Coherence > 0.99).
- Identify "Interference Bridges" where two dissonant frequencies lock into a new consonant geometry.
```

### Step 2: Install Dependencies

```bash
# Required
pip install anthropic

# Optional (for real web search)
pip install duckduckgo-search
```

### Step 3: Run Ollama

```bash
ollama serve
ollama pull qwen2.5-coder
```

---

## Usage

```bash
python rain_unique.py
```

The AI will:
1. Load YOUR knowledge base
2. Monitor simulated sensor data every 15 seconds
3. Apply triangulation to each reading
4. File memos only for novel findings

---

## Example Output

### Validation (You Already Know This)

```
🤖 Thought: Sensor shows 432Hz. Checking Knowledge Base...
           This matches our 'Resonance Capsule' project.
           Searching online... 432Hz widely discussed.
           Conclusion: VALIDATION, not new art.
           Novelty Score: 2/10. Logging as routine update.

📄 Memo filed: '432 Hz Validation' (Novelty: 2)
```

### Breakthrough (Nobody Knows This!)

```
🤖 Thought: Sensor shows interference at 447.3Hz with 3:2 ratio.
           Checking Knowledge Base... No mention in our projects.
           Searching online for '447.3Hz cymatic bridge'...
           No results found.
           Conclusion: UNIQUE PRIOR ART.
           Novelty Score: 9/10. Filing High Priority Memo.

📄 Memo filed: 'Novel Interference Bridge' (Novelty: 9)
```

---

## Configuration

Edit these variables in `rain_unique.py`:

```python
MODEL = "qwen2.5-coder"        # Ollama model
SHIFT_INTERVAL = 15            # Seconds between checks
KNOWLEDGE_BASE_FILE = "VERS3_KNOWLEDGE.txt"
LAB_NOTEBOOK = "VERS3_INTERNAL_LOGS.md"
```

---

## Customization

### Change Check Interval

```python
SHIFT_INTERVAL = 30  # Check every 30 seconds
```

### Use Different Model

```python
MODEL = "llama3.1"   # or any other Ollama model
```

### Add Your Projects

Edit `VERS3_KNOWLEDGE.txt`:

```text
EXISTING PROJECTS:
4. My New Tool: Description of what it does
5. Another Project: Its purpose and frequencies
```

---

## Files Generated

- `VERS3_INTERNAL_LOGS.md` - All filed memos
- `VERS3_KNOWLEDGE.txt` - Your reference manual (edit this!)
- `rain_unique.py` - The AI scientist

---

## Novelty Scoring

**1-3**: Validation (in your KB or widely known)
**4-6**: Public Domain (found online but not in your work)
**7-8**: Interesting (minor novelty)
**9-10**: 🚨 HIGH PRIORITY (unique prior art)

---

## Stopping the System

Press `Ctrl+C` to stop.

You'll see a summary:
```
Session Summary:
  Total cycles: 45
  Memos filed: 12
```

---

## What Makes This Different

This is the **exact specification you requested**:
- ✓ Simple, focused implementation
- ✓ Your exact triangulation logic
- ✓ PowerShell installer
- ✓ Continuous monitoring mode
- ✓ No unnecessary complexity

**This is NOT the comprehensive R.A.I.N. system** (that's in `rain_project/`).

**This IS the streamlined "employee" version** that runs shifts and files memos.

---

## Comparison

### This Version (`rain_unique.py`)
- Continuous monitoring mode
- Simulated sensor data
- Auto-filing memos
- Runs "shifts" like an employee
- Simple triangulation
- PowerShell friendly

### Full R.A.I.N. (`rain_project/`)
- Interactive research mode
- Real acoustic analysis (FFT, Chladni simulation)
- Literature database
- Experiment design
- Comprehensive tools
- Educational documentation

**Use this version** for: Automated novelty monitoring
**Use full R.A.I.N.** for: Interactive research and analysis

---

## Troubleshooting

**"Error connecting to Ollama"**
```bash
ollama serve
```

**"Model not found"**
```bash
ollama pull qwen2.5-coder
```

**Want real web search?**
```bash
pip install duckduckgo-search
```

**Change model**
Edit line 17 in `rain_unique.py`:
```python
MODEL = "llama3.1"  # or your preferred model
```

---

## That's It!

Simple, focused, and exactly as you specified.

Run it:
```bash
python rain_unique.py
```

Watch it triangulate:
1. Check your work
2. Check online
3. File memos for real discoveries

🌧️ **Intelligent novelty detection for Vers3Dynamics**
