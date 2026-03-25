# Stability Tiers

This document partitions the repository into the supported default product,
opt-in integrations, and experimental lab surfaces so the project scope stays
understandable on a standard clone.

Default expectation:

- `cargo build` and the required Rust CI gates target the stable core
  (`default = ["stable-core"]`).
- Tier 2 functionality is opt-in through explicit Cargo features, config, or
  deployment choices.
- Tier 3 paths are documented research surfaces and are not release-blocking by
  default.

## Tier 1: Stable Core

Changes here should be treated as release-blocking when they regress behavior or compatibility.

- core runtime, config, and operator paths under `src/`, excluding the
  integration-oriented subtrees listed in Tier 2
- `crates/`
- `Cargo.toml`
- `Cargo.lock`
- `tool_descriptions/`
- `tests/`
- `web/`
- `docs/reference/`
- `docs/ops/`
- `docs/troubleshooting.md`
- install and bootstrap entrypoints such as `install.sh`, `INSTALL_RAIN.cmd`, `INSTALL_RAIN.ps1`

Expectations:

- Backward compatibility matters.
- Docs and tests should move with behavior changes.
- These paths define the supported `rain` runtime, config contract, and operator workflow.

## Tier 2: Supported Extensions

These areas are part of the product surface, but they can evolve faster than the core when integrations or platform constraints change.

- `src/providers/`
- `src/channels/`
- `src/tools/`
- `src/hardware/`
- `src/peripherals/`
- `src/integrations/`
- `src/p2p/`
- `src/rag/`
- `src/nodes/`
- `src/hands/`
- `src/skillforge/`
- `src/verifiable_intent/`
- `src/tunnel/`
- `src/plugins/`
- `plugins/`
- `example-plugin/`
- `examples/`
- `deploy/`

Expectations:

- Interfaces should stay coherent with the core runtime.
- Compatibility is important, but narrower blast radius and platform-specific changes are expected.
- Validation should focus on the touched integration path rather than the entire lab surface.

## Build Defaults

- Default stable-core build: `cargo build --locked`
- Supported extension example:
  `cargo build --locked --features channel-matrix,channel-lark,memory-postgres`
- Experimental workflow example:
  `cargo build --locked --features skill-creation`

## Tier 3: Experimental and Research Surfaces

These paths are intentionally non-core. They may be reorganized, renamed, extracted, or archived without the same compatibility guarantees as Tier 1.

- `graph_r1_engine/`
- `godot_client/`
- `firmware/`
- `hello_os/`
- `lab/`
- `papers/`
- `meeting_archives/`
- `python/`
- `james_library/`
- `rlm-main/`
- `benchmark_data/`

Expectations:

- Do not treat these directories as release-critical by default.
- Prefer documenting experiments, prototypes, or extraction plans instead of expanding the stable runtime contract around them.
- If an experimental subsystem becomes user-facing and maintained, promote it explicitly into Tier 1 or Tier 2 in the same change that formalizes support.

## Promotion Rule

Move a path upward only when all of the following are true:

1. It has a clear owner and maintenance path.
1. It has focused validation, not just ad hoc manual usage.
1. It is linked from the supported docs flow as an intentional product surface.
1. Its rollback and compatibility story are understood.

## Scope Rule

When adding a new subsystem, classify it immediately:

- default to Tier 3 if it is exploratory
- use Tier 2 for opt-in integrations or platform-specific extensions
- reserve Tier 1 for the runtime, config, and operator paths that define the supported product
