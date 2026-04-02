# Research README Repositioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `README.md` so it tells the research-panel product story first, while preserving the repo's current install, clone, and contributor setup details.

**Architecture:** Keep the scope intentionally narrow. Update the public-facing README copy in `README.md` and lock the new story in with a focused regression in `tests/test_product_cohesion_docs.py`. Do not rewrite translations or broader docs in this plan; this is a top-level README repositioning only.

**Tech Stack:** Markdown, pytest docs-cohesion tests, existing repository documentation conventions.

---

## File Map

- Modify: `README.md`
  - Replace the coding-agent-runtime headline story with the approved research-panel product story.
  - Keep translation links, install markers, clone instructions, and developer setup material.
- Modify: `tests/test_product_cohesion_docs.py`
  - Add a focused regression test for the README's new top-level positioning.

## Architectural Notes

- The README should now behave like a product page first and an OSS repo second.
- `R.A.I.N. Lab` is the product; `James` is the assistant inside the product.
- The first "try it now" path should point to the hosted public research-panel experience at `https://lab.vers3dynamics.com`.
- Existing docs cohesion checks already require these README markers and must continue to pass:
  - `python rain_lab.py`
  - `INSTALL_RAIN.cmd`
  - `./install.sh`
  - `https://github.com/topherchris420/james_library.git`
  - `cd james_library`
- Do not change translated README files in this plan.

---

### Task 1: Lock the README Positioning Contract

**Files:**
- Modify: `tests/test_product_cohesion_docs.py`

- [ ] **Step 1: Add a failing README positioning regression**

```python
def test_readme_leads_with_research_panel_positioning(repo_root: Path) -> None:
    text = _read(repo_root, "README.md")

    assert "# R.A.I.N. Lab" in text
    assert (
        "A private-by-default expert panel in a box for researchers, independent thinkers, "
        "and R&D teams."
    ) in text
    assert (
        "Ask a raw research question. R.A.I.N. Lab assembles multiple expert perspectives, "
        "grounds strong claims in papers or explicit evidence, and returns the strongest "
        "explanations, disagreements, and next moves."
    ) in text
    assert (
        "Most tools help you find papers. R.A.I.N. Lab helps you think with a room full of experts."
        in text
    )
    assert "James is the assistant inside R.A.I.N. Lab" in text
    assert "https://lab.vers3dynamics.com" in text
    assert "# James and the R.A.I.N. Lab" not in text
    assert (
        "The local-first autonomous coding agent runtime for Rust, Python, and hardware-adjacent teams."
        not in text
    )
```

- [ ] **Step 2: Run the new regression to confirm the current README fails**

Run: `pytest tests/test_product_cohesion_docs.py::test_readme_leads_with_research_panel_positioning -v`

Expected: FAIL because the current README still leads with `James and the R.A.I.N. Lab` and the coding-agent-runtime tagline.

---

### Task 2: Rewrite the README Around the Research-Panel Story

**Files:**
- Modify: `README.md`
- Modify: `tests/test_product_cohesion_docs.py`

- [ ] **Step 1: Rewrite the top-level README copy**

Replace the current top sections of `README.md` with the following structure and copy:

```md
# R.A.I.N. Lab

**A private-by-default expert panel in a box for researchers, independent thinkers, and R&D teams.**

<p align="center">
  <img src="assets/rain_lab.png" alt="R.A.I.N. Lab logo" width="800" />
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> •
  <a href="README.ja.md">日本語</a> •
  <a href="README.ru.md">Русский</a> •
  <a href="README.fr.md">Français</a> •
  <a href="README.vi.md">Tiếng Việt</a>
</p>

---

## What It Does

Ask a raw research question. R.A.I.N. Lab assembles multiple expert perspectives, grounds strong claims in papers or explicit evidence, and returns the strongest explanations, disagreements, and next moves.

Most tools help you find papers. R.A.I.N. Lab helps you think with a room full of experts.

James is the assistant inside R.A.I.N. Lab who helps run the panel, guide the workflow, and carry the question through local sessions.

---

## Try It Now

### Public Research Panel

Start with the hosted experience:

- https://lab.vers3dynamics.com

Bring one hard question and start the debate.

### Local and Private

Run the local experience:

```bash
python rain_lab.py
```

On Windows, you can also double-click `INSTALL_RAIN.cmd` to create shortcuts. On macOS/Linux, run `./install.sh` for a one-click setup.
```

- [ ] **Step 2: Rewrite the rest of the README so it stays product-first**

Update the remaining sections so they read like this:

```md
## Who It Is For

- Researchers pressure-testing a question before they commit to an explanation
- Independent thinkers exploring a hard problem from multiple angles
- R&D teams mapping competing explanations before they build

## What You Can Do

| Use case | What happens |
|----------|--------------|
| **Pressure-test a research question** | Multiple expert perspectives attack the same question from different angles |
| **Surface competing explanations** | The panel makes disagreements explicit instead of flattening everything into one answer |
| **Trace strong claims back to evidence** | Papers and explicit sources stay attached to the output where possible |
| **Leave with next moves** | The synthesis highlights what to read, test, challenge, or investigate next |
| **Work privately when needed** | Local workflows and model connections can stay on your own machine |

## Why It Is Different

| Generic AI chat | R.A.I.N. Lab |
|-----------------|--------------|
| One answer, right or wrong | Multiple perspectives in tension |
| Weak evidence discipline | Strong claims tied to papers or explicit evidence |
| Little visibility into disagreement | Open disagreement and synthesis are part of the product |
| Cloud-first by default | Private-by-default workflows are supported |

## Local and Private Workflow

If you want the private local path, James is the assistant inside R.A.I.N. Lab who helps guide the workflow.

### Step 1: Start the local demo

```bash
python rain_lab.py
```

### Step 2: Run a guided local session

```bash
python rain_lab.py --mode beginner --topic "What is the strongest interpretation of these conflicting results?"
```

### Step 3: Connect your model stack

```bash
python rain_lab.py --mode first-run
```

The installer helps you connect to LM Studio or Ollama for private local use.

## Features

- **Multi-expert panel responses** — one question, several disciplined perspectives
- **Evidence-grounded outputs** — strong claims can be tied to papers or explicit sources
- **Synthesis you can act on** — disagreements, strongest explanations, and next moves in one place
- **Private-by-default workflows** — local sessions and model connections can stay on your machine
- **Context and cost controls** — long-loop context management and budget-aware operation remain available
- **Python + Rust implementation** — the runtime stays extensible for contributors and advanced users

## Requirements

- **Python 3.10+**
- **Optional:** LM Studio or Ollama for local AI models
- **Optional:** Rust toolchain for the fast runtime layer

## Documentation

- [Start Here](START_HERE.md)
- [Beginner Guide](docs/getting-started/README.md)
- [One-Click Install](docs/one-click-bootstrap.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Research Papers](https://topherchris420.github.io/research/)
```

- [ ] **Step 3: Keep the contributor section but move it behind the product story**

Keep the existing developer section in `README.md`, preserving:

```md
## For Developers

<details>
<summary>Click to expand</summary>

git clone https://github.com/topherchris420/james_library.git
cd james_library

...

ruff check .
pytest -q
cargo fmt --all
cargo clippy --all-targets -- -D warnings

</details>
```

The developer section should still include:

- `git clone https://github.com/topherchris420/james_library.git`
- `cd james_library`
- Python setup
- Rust setup
- test commands

- [ ] **Step 4: Run the docs cohesion tests**

Run: `pytest tests/test_product_cohesion_docs.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_product_cohesion_docs.py
git commit -m "copy: reposition README around research panel"
```

---

### Task 3: Final Verification

**Files:**
- Modify: none
- Test: `tests/test_product_cohesion_docs.py`

- [ ] **Step 1: Re-run the README positioning regression alone**

Run: `pytest tests/test_product_cohesion_docs.py::test_readme_leads_with_research_panel_positioning -v`

Expected: PASS

- [ ] **Step 2: Verify the key README markers directly**

Run: `rg -n "expert panel in a box|room full of experts|lab\\.vers3dynamics\\.com|python rain_lab.py|INSTALL_RAIN\\.cmd|\\./install\\.sh|James is the assistant" README.md`

Expected: output contains all of the new product markers plus the required install markers.

- [ ] **Step 3: Confirm the old runtime-first headline is gone**

Run: `rg -n "local-first autonomous coding agent runtime|James and the R\\.A\\.I\\.N\\. Lab" README.md`

Expected: no matches

---

## Plan Self-Review

### Spec Coverage

- The README becomes product-first and user-first.
- `R.A.I.N. Lab` is the product and `James` is the assistant.
- The hosted public experience is the first "try it now" path.
- The README explicitly names researchers, independent thinkers, and R&D teams.
- Contributor setup remains available lower in the file.

### Placeholder Scan

- No `TODO`, `TBD`, or "update the copy later" steps remain.
- All code-changing steps name exact files and show the intended content.
- All verification steps include exact commands and expected outcomes.

### Type and Interface Consistency

- The README consistently uses `R.A.I.N. Lab` as the product name.
- The README consistently treats `James` as the assistant inside the product.
- The README continues to preserve the install and clone markers required by existing docs tests.
