# 🐙R.A.I.N. Lab: James and AI Research Assistants

<p align="center">
  <img src="assets/rain_lab.png" alt="R.A.I.N. Lab logo" width="900" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078D4?style=flat-square" alt="Platform" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License" />
  <img src="https://img.shields.io/badge/rust-1.87+%20optional-dea584?style=flat-square&logo=rust" alt="Rust optional" />
</p>

<p align="center">
  🌐:
  <a href="README.zh-CN.md">简体中文</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.ru.md">Русский</a> |
  <a href="README.fr.md">Français</a> |
  <a href="README.vi.md">Tiếng Việt</a>
</p>


The R.A.I.N. Lab is a local-first AI research lab for people who want deeper answers to their questions.
It helps you test ideas, compare viewpoints, run structured debates, and generate shareable results without
sending your data off-machine by default.

The core differentiator is the "circuit breaker" workflow: when agents get stuck, R.A.I.N. Lab can turn the
disagreement into a formal logic problem and push it through a sandboxed verification path instead of letting
the conversation loop forever.

## Who It Is For

R.A.I.N. Lab is built for people who need answers they can defend, not just answers that sound good.

| Role | What you can do with R.A.I.N. Lab |
| --- | --- |
| Founders and product leaders | Stress-test strategy decisions with structured debate before committing roadmap or budget |
| Researchers and analysts | Compare competing hypotheses, preserve disagreement, and capture auditable reasoning trails |
| Operators and technical teams | Turn messy discussions into verifiable outputs that can be reviewed, shared, and rerun |

In practice, this means fewer "AI said so" dead ends. You can start from a single question, let multiple agents
challenge assumptions, route unresolved conflicts through verification, and leave with a result you can present to
other people with confidence.

<p align="center">
  <a href="assets/hello.mp4" title="Play the R.A.I.N. Lab demo video">
    <img src="assets/hello-preview.gif" alt="R.A.I.N. Lab demo video preview" width="520" />
  </a>
</p>

## Start Fast

Choose one install route, then use `python rain_lab.py` as the everyday product entrypoint.

### Windows One-Click

```powershell
git clone https://github.com/topherchris420/james_library.git
cd james_library
.\INSTALL_RAIN.cmd
```

The installer uses `uv`, fetches the prebuilt runtime, prepares `.env` and `config.toml`, and hands off to James automatically.

### macOS / Linux One-Click

```bash
git clone https://github.com/topherchris420/james_library.git
cd james_library
./install.sh
```

The installer uses `uv`, fetches the prebuilt runtime, prepares `.env` and `config.toml`, and hands off to James automatically.

Then:

1. Press Enter for the no-setup instant demo.
2. Try beginner mode with one topic.
3. Open `meeting_archives/RAIN_LAB_SHOWCASE.html` to revisit recent sessions.

Beginner and demo runs generate:

- a screenshot-friendly HTML share card
- a matching poster SVG
- a local showcase page with poster previews and follow-up commands

Use `python rain_lab.py --open-browser off` if you want to keep everything local without auto-opening pages.
On Windows, `INSTALL_RAIN.cmd` also creates desktop and Start Menu shortcuts.
On macOS/Linux, `./install.sh` is the equivalent one-click repo installer.

## Why People Use It

- Local-first by default: conversations, archives, and outputs stay on your machine unless you opt into a provider.
- Beginner-friendly front door: `python rain_lab.py` opens the guided launcher, and the instant demo works without a model.
- Structured reasoning: R.A.I.N. Lab can debate, compare, and resolve disagreements instead of just generating plausible text.
- Shareable outputs: beginner and demo sessions end in polished artifacts people can screenshot, revisit, and pass around.

## Pick A Path

| Goal | Run this |
| --- | --- |
| Fastest first experience | `python rain_lab.py` |
| No-setup instant demo | `python rain_lab.py --mode demo --preset startup-debate` |
| One topic, beginner-friendly flow | `python rain_lab.py --mode beginner --topic "your idea"` |
| Guided setup for local models | `python rain_lab.py --mode first-run` |
| Health and readiness check | `python rain_lab.py --mode validate` |
| Standard chat flow | `python rain_lab.py --mode chat --topic "your topic"` |
| Multi-agent lab meeting | `python rain_lab.py --mode rlm --topic "your topic"` |
| Avatar-enabled chat when available | `python rain_lab.py --mode chat --ui auto --topic "your topic"` |

On macOS and Linux, use `python3` instead of `python` if needed.

## Stable Core

The supported baseline is:

- the Python launcher path via `python rain_lab.py`
- the default Rust build for the runtime layer

Channels, providers, storage backends, and platform integrations stay opt-in through explicit feature flags.
That keeps the default product smaller, more reliable, and easier to explain.

Before treating an extension as production-ready, read:

- [Stability Tiers](docs/project/stability-tiers.md)
- [Production Readiness](docs/PRODUCTION_READINESS.md)

## What Makes It Different

Most AI tools follow a simple pattern: prompt, answer, retry.
R.A.I.N. Lab is built for cases where that is not enough.

| Traditional AI workflow | R.A.I.N. Lab workflow |
| --- | --- |
| One model answers | Multiple agents can inspect and challenge the idea |
| Disagreement often gets flattened | Disagreement is preserved long enough to compare views |
| Unclear conflicts stay ambiguous | Formal verification can settle certain disputes |
| Output is usually a chat log | Output can become a session log, share card, poster, and showcase entry |

The product flow is simple:

1. Explore the question from multiple angles.
2. Debate tradeoffs or conflicting interpretations.
3. Break deadlocks through verification when possible.
4. Return a result you can keep, rerun, or share.

## Model Setup

You have three practical options:

1. Use the instant demo first. This needs no model and gives you the fastest preview.
2. Use a local model through LM Studio or Ollama for the recommended local-first path.
3. Add a cloud provider during first-run setup if you want hosted inference.

Recommended local-first flow:

1. Run `python rain_lab.py --mode first-run`
2. Let the launcher detect or configure your model source
3. Return to `python rain_lab.py` for beginner mode, demo presets, or research workflows

## Install And Onboarding

Use the focused docs below depending on what you need:

- [START_HERE.md](START_HERE.md) for the walkthrough
- [Getting Started Docs](docs/getting-started/README.md) for onboarding
- [One-Click Bootstrap](docs/one-click-bootstrap.md) for setup automation
- [Releases Page](https://github.com/topherchris420/james_library/releases) for prebuilt packages
- [Troubleshooting](docs/troubleshooting.md) if something fails

## Product Layers

R.A.I.N. Lab is one platform built from two main layers:

| Layer | Role | Language |
| --- | --- | --- |
| James Library | Research workflows, debate, synthesis, launcher experience | Python |
| ZeroClaw | Orchestration, channels, tools, memory, security | Rust |

You use it as one app.
Python flows work without Rust installed, while the Rust runtime adds speed, orchestration, and integration depth.
ZeroClaw is the runtime lineage behind that layer, but the user-facing product is R.A.I.N. Lab.

## For Developers

<details>
<summary><strong>Developer setup, test commands, and project links</strong></summary>

### Quick Setup

```bash
git clone https://github.com/topherchris420/james_library.git
cd james_library
uv python install 3.12
uv venv .venv --python 3.12
uv pip sync --python .venv/bin/python requirements-dev-pinned.txt
uv run --python .venv/bin/python bootstrap_local.py --skip-preflight
cargo build --release --locked
uv run --python .venv/bin/python rain_lab.py --mode first-run
```

### Tests

```bash
ruff check .
pytest -q
cargo fmt --all
cargo clippy --all-targets -- -D warnings
cargo test --locked
```

### Extension Example

```bash
cargo build --release --locked --features channel-matrix,channel-lark,memory-postgres
```

### Developer References

- [Architecture](ARCHITECTURE.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Project Roadmap](PRODUCT_ROADMAP.md)
- [Testing Guide](docs/contributing/testing.md)
- [Repo Map](docs/maintainers/repo-map.md)
- [Commands Reference](docs/reference/cli/commands-reference.md)
- [Providers Reference](docs/reference/api/providers-reference.md)
- [Channels Reference](docs/reference/api/channels-reference.md)

</details>

## Documentation

<a href="https://deepwiki.com/topherchris420/james_library"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>

- [Product Overview](START_HERE.md)
- [Architecture](ARCHITECTURE.md)
- [Security Policy](SECURITY.md)
- [Stability Tiers](docs/project/stability-tiers.md)
- [Production Readiness](docs/PRODUCTION_READINESS.md)
- [Setup Guides](docs/setup-guides/README.md)
- [Releases Page](https://github.com/topherchris420/james_library/releases)
- [Troubleshooting](docs/troubleshooting.md)

## License

MIT License. See [LICENSE](LICENSE).

## Acknowledgements

R.A.I.N. Lab is a [Vers3Dynamics](https://vers3dynamics.com/) project built on [ZeroClaw](https://github.com/zeroclaw-labs/zeroclaw).

<a href="https://www.star-history.com/?repos=topherchris420%2Fjames_library&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=topherchris420/james_library&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=topherchris420/james_library&type=date&legend=top-left" />
   <img alt="Vers3Dynamics" src="https://api.star-history.com/image?repos=topherchris420/james_library&type=date&legend=top-left" />
 </picture>
</a>
