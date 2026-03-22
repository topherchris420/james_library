# Testing Guide

R.A.I.N. uses a five-level testing taxonomy for Rust coverage, and the required quality gate also validates Python and web surfaces from the same entrypoint.

## Canonical Validation Entry Points

Use these commands when you want the same validation categories locally that GitHub Actions runs:

```bash
# Native quality gate used by GitHub Actions
bash scripts/ci/quality_gate.sh all

# Discoverable Docker wrapper for local contributors
./dev/ci.sh all
```

The canonical gate is split into the following categories:

| Category | What it runs |
|---|---|
| `rust` | `cargo fmt --all -- --check`, `cargo clippy --locked --all-targets -- -D warnings`, `cargo nextest run --locked`, `cargo check --all-features --locked`, `cargo build --profile ci --locked` |
| `python` | dependency install, `ruff check . --output-format=full`, `pytest tests -v -ra --tb=long`, and `python/tests` when `python/R.A.I.N._tools` exists |
| `web` | `npm ci --prefix web`, optional `npm run lint --prefix web`, optional `npm run test --prefix web`, `npm run build --prefix web` |
| `governance` | docs parity, architecture-boundary, and markdown quality checks when the changed files require them |

You can run an individual category directly with `bash scripts/ci/quality_gate.sh <category>` or through Docker with `./dev/ci.sh <category>`.

## Rust Testing Taxonomy

| Level | What it tests | External boundaries | Directory |
|-------|--------------|-------------------|-----------|
| **Unit** | Single function/struct | Everything mocked | `#[cfg(test)]` blocks in `src/**/*.rs` or separate `src/**/tests.rs` files |
| **Component** | One subsystem within its own boundary | Subsystem real, everything else mocked | `tests/component/` |
| **Integration** | Multiple internal components wired together | Real internals, external APIs mocked | `tests/integration/` |
| **System** | Full request→response across ALL internal boundaries | Only external APIs mocked | `tests/system/` |
| **Live** | Full stack with real external services | Nothing mocked, `#[ignore]` | `tests/live/` |

## Directory Structure

| Directory | Level | Description | Run command |
|-----------|-------|-------------|-------------|
| `src/**/*.rs` | Unit | Co-located `#[cfg(test)]` blocks or separate `tests.rs` files alongside source | `cargo test --lib` |
| `tests/component/` | Component | One subsystem, real impl, mocked boundaries | `cargo test --test component` |
| `tests/integration/` | Integration | Multiple components wired together | `cargo test --test integration` |
| `tests/system/` | System | Full channel→agent→channel flow | `cargo test --test system` |
| `tests/live/` | Live | Real external services, `#[ignore]` | `cargo test --test live -- --ignored` |
| `tests/manual/` | — | Human-driven test scripts (shell, Python) | Run directly |
| `tests/support/` | — | Shared mock infrastructure (not a test binary) | — |
| `tests/fixtures/` | — | Test data files (JSON traces, media) | — |
| `python/tests/` | Python | Companion package coverage for `R.A.I.N.-tools` when `python/R.A.I.N._tools` is present | `cd python && pytest tests -v -ra --tb=long` |
| `web/` | Web | Front-end build validation | `npm ci --prefix web && npm run build --prefix web` |

## How to Run Checks

```bash
# Run the full GitHub Actions-equivalent gate natively
bash scripts/ci/quality_gate.sh all

# Run the same gate inside the local CI container
./dev/ci.sh all

# Run only the Rust gate used by CI
bash scripts/ci/quality_gate.sh rust

# Run only the Python gate used by CI
bash scripts/ci/quality_gate.sh python

# Run only the web gate used by CI
bash scripts/ci/quality_gate.sh web

# Run only the governance/docs gate used by CI
bash scripts/ci/quality_gate.sh governance

# Run all Rust tests (unit + component + integration + system)
cargo test

# Run only unit tests
cargo test --lib

# Run component tests
cargo test --test component

# Run integration tests
cargo test --test integration

# Run system tests
cargo test --test system

# Run live tests (requires API credentials)
cargo test --test live -- --ignored

# Filter within a level
cargo test --test integration agent
```

## How to Add a New Test

1. **Testing one subsystem in isolation?** → `tests/component/`
2. **Testing multiple components together?** → `tests/integration/`
3. **Testing full message flow?** → `tests/system/`
4. **Requires real API keys?** → `tests/live/` with `#[ignore]`
5. **Testing the Python companion package?** → add sources under `python/R.A.I.N._tools` and cover them in `python/tests/`.
6. **Testing the web UI?** → add or update scripts in `web/package.json` so the `web` quality gate picks them up automatically.

After creating a test file, add it to the appropriate `mod.rs` and use shared infrastructure from `tests/support/`.

## Shared Infrastructure (`tests/support/`)

All test binaries include `mod support;` making shared mocks available via `crate::support::*`.

| Module | Contents |
|--------|----------|
| `mock_provider.rs` | `MockProvider` (FIFO scripted), `RecordingProvider` (captures requests), `TraceLlmProvider` (JSON fixture replay) |
| `mock_tools.rs` | `EchoTool`, `CountingTool`, `FailingTool`, `RecordingTool` |
| `mock_channel.rs` | `TestChannel` (captures sends, records typing events) |
| `helpers.rs` | `make_memory()`, `make_observer()`, `build_agent()`, `text_response()`, `tool_response()`, `StaticMemoryLoader` |
| `trace.rs` | `LlmTrace`, `TraceTurn`, `TraceStep` types + `LlmTrace::from_file()` |
| `assertions.rs` | `verify_expects()` for declarative trace assertion |

### Usage

```rust
use crate::support::{MockProvider, EchoTool, CountingTool};
use crate::support::helpers::{build_agent, text_response, tool_response};
```

## JSON Trace Fixtures

Trace fixtures are canned LLM response scripts stored as JSON files in `tests/fixtures/traces/`. They replace inline mock setup with declarative conversation scripts.

### How it works

1. `TraceLlmProvider` loads a fixture and implements the `Provider` trait
2. Each `provider.chat()` call returns the next step from the fixture in FIFO order
3. Real tools execute normally (e.g., `EchoTool` processes arguments)
4. After all turns, `verify_expects()` checks declarative assertions
5. If the agent calls the provider more times than there are steps, the test fails

### Fixture format

```json
{
  "model_name": "test-name",
  "turns": [
    {
      "user_input": "User message",
      "steps": [
        {
          "response": {
            "type": "text",
            "content": "LLM response",
            "input_tokens": 20,
            "output_tokens": 10
          }
        }
      ]
    }
  ],
  "expects": {
    "response_contains": ["expected text"],
    "tools_used": ["echo"],
    "max_tool_calls": 1
  }
}
```

**Response types**: `"text"` (plain text) or `"tool_calls"` (LLM requests tool execution).

**Expects fields**: `response_contains`, `response_not_contains`, `tools_used`, `tools_not_used`, `max_tool_calls`, `all_tools_succeeded`, `response_matches` (regex).

## Live Test Conventions

- All live tests must be `#[ignore]`
- Use `env::var("R.A.I.N._TEST_*")` for credentials
- Run with `cargo test --test live -- --ignored --nocapture`

## Manual Tests (`tests/manual/`)

Scripts for human-driven testing that can't be automated via `cargo test`:

| Directory/File | What it does |
|---|---|
| `manual/telegram/` | Telegram integration test suite, smoke tests, message generator |
| `manual/test_dockerignore.sh` | Validates `.dockerignore` excludes sensitive paths |

For Telegram-specific testing details, see [testing-telegram.md](./testing-telegram.md).
