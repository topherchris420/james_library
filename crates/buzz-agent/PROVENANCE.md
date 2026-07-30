# Provenance

This crate is a vendored port of `crates/buzz-agent` from
[block/buzz](https://github.com/block/buzz).

- **Upstream commit:** `51bb97d2be658854bb8a39983af568e90591d375` (2026-07-29)
- **Upstream license:** Apache-2.0 (retained verbatim in `LICENSE`)

R.A.I.N. as a whole is `MIT OR Apache-2.0`. This crate is **Apache-2.0 only** —
the MIT half of that dual license does not apply to it. `Cargo.toml` declares
`license = "Apache-2.0"` accordingly, and the crate is marked `publish = false`.

## Local modifications

Only two changes were made to upstream sources; the Rust logic is untouched.

1. **`Cargo.toml` — dependency resolution.** Upstream inherits versions from
   block/buzz's `[workspace.dependencies]`. R.A.I.N.'s root manifest has no such
   table, so every dependency is pinned explicitly. Two were aligned *down* to
   R.A.I.N.'s existing versions so cargo unifies a single copy rather than
   compiling two major versions into one dependency graph:

   | Dependency | Upstream | Here | Note |
   | --- | --- | --- | --- |
   | `reqwest` | 0.13 | 0.12 | feature `rustls` is spelled `rustls-tls` in 0.12 |
   | `sha2` | 0.11 | 0.10 | |

   Only `Client`, `RequestBuilder`, `Response`, `StatusCode`, `.form()`, `.json()`
   and `Digest`/`Sha256` are used, all API-stable across those ranges.

   The crate stays on **edition 2021** (the workspace root is edition 2024).
   Editions are per-crate; upstream source targets 2021.

2. **`src/config.rs` — removed a monorepo path escape.** Upstream's
   `effort_table_fixture_matches_rust_implementation` test does
   `include_str!("../../../desktop/src/features/agents/ui/effortTable.fixture.json")`,
   reaching into block/buzz's TypeScript frontend. R.A.I.N. has no such
   frontend, so the fixture is vendored to `tests/fixtures/effortTable.fixture.json`
   and the `include_str!` retargeted. The test keeps its value as a regression
   lock on the Rust effort table.

3. **`src/auth.rs` — OAuth token cache is created 0600.** Upstream writes the
   temp cache with `fs::write`, which applies the process umask to 0666 (mode
   0644 under a typical 022), and `fs::rename` preserves that mode — leaving
   Databricks access *and* refresh tokens readable by every other local account.
   Added `write_private()` (creates the file 0600 up front, so it never exists
   on disk with wider permissions) and `harden_existing()` (best-effort tighten
   of a cache left loose by an older build, on read). Both are Unix-gated with
   no-op fallbacks elsewhere. Reported by automated review on PR #381.

4. **`README.md` — corrected `BUZZ_AGENT_MAX_HISTORY_BYTES` default.** Upstream's
   config table and limits table both documented 1 MiB, but `Config::from_env`
   uses `16 * 1024 * 1024` (`src/config.rs:830`). The runtime is authoritative,
   so the docs now say 16 MiB. Reported by automated review on PR #381.

## Known upstream issue

`tests/fake_llm.rs` is **flaky, and was flaky before this port** — it fails
intermittently on timing-sensitive steer/cancel tests. Measured over 4 runs
against an unmodified block/buzz checkout at the commit above: 1 run failed with
2 failures, 3 runs passed. The ported copy shows the same behavior.

This conflicts with `CLAUDE.md` §3.7 (Determinism + Reproducibility), which
requires deterministic tests. It should be quarantined or fixed before
`cargo test` on this crate is wired into a required CI gate.

The rest of the suite is stable: 299 lib unit tests and 14 `databricks_oauth`
integration tests pass consistently.
