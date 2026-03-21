# R.A.I.N. Lab: A Local-First Research Assistant That Verifies Its Own Answers

R.A.I.N. Lab is an open-source multi-agent research assistant for **academic researchers, R&D teams, and privacy-conscious organizations** who need AI-generated conclusions they can actually trust. It solves the core problem with multi-agent AI systems — agents that either agree too quickly or argue forever — by automatically translating unresolved debates into formal logic and settling them with a mathematically guaranteed SAT solver running inside a secure sandbox.

**Your data never leaves your machine. Every conclusion comes with proof, not probability.**

---

## How It Works

1. **Explore** — Specialist AI agents investigate your research question from different angles.
2. **Debate** — Agents challenge each other's reasoning across multiple rounds.
3. **Verify** — When debate stalls, the system compiles the disagreement into a boolean formula and solves it with a WASM-sandboxed SAT solver.
4. **Resolve** — The proven result is injected back, forcing agents to build on settled facts.

This is the **Circuit Breaker architecture**: instead of guessing, R.A.I.N. Lab proves.

---

## Who Is This For?

- **Academic Researchers** — Run automated, adversarial peer review on your thesis against a local library of papers before human review.
- **Math & Physics R&D** — Use the plugin system to let AI run formal verification with Lean, Coq, or custom Rust physics engines.
- **Privacy-Conscious Teams** — Analyze sensitive datasets without sending a single byte to an external API.

---

## Quick Start

```bash
git clone https://github.com/topherchris420/james_library.git
cd james_library
python bootstrap_local.py
python rain_lab.py
```

See the [full installation guide](../README.md#install-in-3-steps) for platform-specific instructions.

---

## Architecture

R.A.I.N. Lab ships as one product built from two layers:

| Layer | Role | Language |
|---|---|---|
| **James Library** | Research workflows, lab meetings, synthesis | Python |
| **ZeroClaw** | Agent runtime, orchestration, security, tools | Rust (optional) |

Python research workflows work without Rust. The Rust runtime adds speed, channels, and tool execution for advanced users.

---

## Key Features

- **3.1 MB core binary** — runs on laptops, desktops, and low-powered devices
- **Full local encryption** — all conversations and files stored locally
- **Hot-loadable plugins** — add custom solvers and physics engines without restart
- **Multi-model support** — LM Studio, OpenRouter, OpenAI, and more
- **3D visualization** — optional Godot-based avatar interface

---

## Documentation

- [Commands Reference](commands-reference.md)
- [Configuration Reference](config-reference.md)
- [Providers Reference](providers-reference.md)
- [Channels Reference](channels-reference.md)
- [Troubleshooting](troubleshooting.md)
- [Operations Runbook](operations-runbook.md)

## License

MIT OR Apache-2.0
