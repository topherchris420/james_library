# 🐙 James and the R.A.I.N. Lab

**Think with AI teammates who challenge your ideas, stress-test your plans, and remember everything.**

<p align="center">
  <img src="assets/rain_lab.png" alt="R.A.I.N. Lab logo" width="800" />
</p>

<p align="center">🌐
  <a href="README.zh-CN.md">简体中文</a> •
  <a href="README.ja.md">日本語</a> •
  <a href="README.ru.md">Русский</a> •
  <a href="README.fr.md">Français</a> •
  <a href="README.vi.md">Tiếng Việt</a>
</p>

---

## What It Feels Like

Imagine a research meeting where multiple AI advisors each bring a different perspective. One plays devil's advocate. Another looks for gaps in your logic. A third checks if your claims hold up. They debate. They document. They remember.

That's the R.A.I.N. Lab.

You bring the question. James and his team explore it from multiple angles, challenge weak spots, verify facts, and hand you back something you can actually use — a clear analysis, a decision framework, or a list of what still needs testing.

All on your own computer. Private. No cloud. No one is watching.

---

## What You Can Do

| Use case | What happens |
|----------|--------------|
| **Validate an idea** | Multiple agents pressure-test your assumption from different angles |
| **Compare strategies** | Get structured debate on tradeoffs before you commit |
| **Research a topic** | Agents explore competing viewpoints and preserve disagreements |
| **Plan a decision** | Document reasoning trails you can review, share, or rerun later |
| **Sound & physics exploration** | Deep technical workflows for resonance, frequency, and geometry |

**The result:** Fewer blind spots. More confidence. Outputs you can present to others.

---

## Try It Now

No setup required for the demo:

```
python rain_lab.py
```

Press Enter. That's it. James will walk you through the rest.

On Windows, you can also double-click `INSTALL_RAIN.cmd` to create shortcuts.
On macOS/Linux, run `./install.sh` for a one-click setup.

---

## Getting Started

### Step 1: Try the Demo

```bash
python rain_lab.py
```

Press Enter for instant demo mode. No model, no config — just see how it works.

### Step 2: Run Your First Topic

```bash
python rain_lab.py --mode beginner --topic "your question here"
```

This opens a guided flow where James helps you explore one idea thoroughly.

### Step 3: Set Up Your AI (Optional)

Want to use your own AI model (runs locally, stays private)?

```bash
python rain_lab.py --mode first-run
```

The installer helps you connect to LM Studio or Ollama. Both run on your machine — no data leaves your computer.

---

## Why It's Different

| Regular AI chat | R.A.I.N. Lab |
|-----------------|--------------|
| One answer, right or wrong | Multiple agents debate and verify |
| Disagreement gets glossed over | Disagreement is preserved and compared |
| Chat log that fades away | Session logs, share cards, and posters you can keep |
| Everything in the cloud | Everything stays on your machine |

---

## Features

- **Multi-agent research** — James plus specialized agents explore from different angles
- **Structured debate** — Tradeoffs and disagreements get surfaced, not flattened
- **Verification workflows** — Certain disputes get settled through checks, not just opinions
- **Memory that persists** — Conversations are summarized and stored automatically
- **Shareable outputs** — Session cards, posters, and HTML reports
- **Local-first** — No cloud dependency. Your data stays yours.
- **Available in 6 languages** — 中文, 日本語, Русский, Français, Tiếng Việt, English

---

## Requirements

- **Python 3.10+** (free download for Windows/Mac/Linux)
- **Optional:** LM Studio or Ollama for local AI models
- **Optional:** Rust toolchain for the fast runtime layer

Python works without any of the optional parts. The more you add, the faster and more powerful it gets.

---

## Documentation

- [Start Here](START_HERE.md) — Guided walkthrough
- [Beginner Guide](docs/getting-started/README.md)
- [One-Click Install](docs/one-click-bootstrap.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Research Papers](https://topherchris420.github.io/research/)

---

## For Developers

<details>
<summary>Click to expand</summary>

R.A.I.N. Lab is built in Python + Rust. If you want to hack on it:

```bash
git clone https://github.com/topherchris420/james_library.git
cd james_library

# Python setup
uv python install 3.12
uv venv .venv --python 3.12
uv pip sync --python .venv/bin/python requirements-dev-pinned.txt

# Rust setup (optional, for the fast runtime)
cargo build --release --locked

# Run
uv run --python .venv/bin/python rain_lab.py --mode first-run
```

**Testing:**
```bash
ruff check .
pytest -q
cargo fmt --all
cargo clippy --all-targets -- -D warnings
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [CONTRIBUTING.md](CONTRIBUTING.md) for details.

</details>

---

## License

MIT. Built by [Vers3Dynamics](https://vers3dynamics.com/), special thanks to ZeroClaw

<a href="https://star-history.com/#topherchris420/james_library&type=date">
  <img src="https://api.star-history.com/image?repos=topherchris420/james_library&type=date&theme=dark" alt="Star History" width="200" />
</a>
