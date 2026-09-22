# Config Reference

Canonical configuration schema is defined in:

- [`../src/config/schema.rs`](../src/config/schema.rs)

Configuration loading and merging logic:

- [`../src/config/mod.rs`](../src/config/mod.rs)

Treat config keys as public contract and coordinate changes with migration notes.

## Typed judgment environment

Typed judgment is opt-in and uses environment variables rather than the Rust
provider configuration because it is an independent Python evaluation boundary:

- `RAIN_JUDGMENT_PROVIDER=off|typesafe` (default: `off`)
- `TYPESAFE_API_KEY` (required only when TypeSafe is enabled)
- `TYPESAFE_MODEL` (default: `jev-latest`)

Provider failure is explicit `UNAVAILABLE`; there is no automatic retry or
fallback. See [`typed-judgment.md`](typed-judgment.md).

## Autonomous runtime sections (added 2026-06)

All default to disabled; omitting them preserves prior behavior.

- `[autonomous_runtime]` — routes background work (starting with the
  heartbeat) through the pulse driver in `src/autonomy/`; includes
  `[autonomous_runtime.vitals]` stagnation/dead-end thresholds used by the
  in-loop vitals monitor. Named to avoid colliding with the security
  `[autonomy]` section.
- `[senses]` — prioritized sensory bus for channel intake (lane capacities,
  starvation credit, ambient buffer sizing, coalesce window).
- `[hooks.builtin].episodic_events` — appends one JSONL line per tool call
  to `episodic_memory/episodic_events.jsonl` (tool name, outcome, duration
  only; never arguments or outputs).

Design: [`autonomous-runtime-design.md`](autonomous-runtime-design.md).

## Optional bounded decision routing

`python rain_lab.py decide --request examples/bounded-decision.json` produces a
proposal only; `decide --replay ARTIFACT` replays it offline.
`RAIN_DECISION_MODE=off|laya|jev|cascade` defaults to `off`.
`RAIN_METACOGNITIVE_CONTROL=false` preserves the existing chat loop.
Local inference requires `RAIN_LAYA_CHECKPOINT`; calibrated proposals require
`RAIN_DECISION_CALIBRATION`. Missing engines or calibration return to R.A.I.N.
Remote evaluation requires explicit request consent; chat also requires
`RAIN_DECISION_REMOTE_ALLOWED=true`. Invalid configuration is reported.
See [bounded decisions](bounded-decisions.md) for all settings, diagnostics, calibration,
privacy, timeouts, and rollback. Existing `judge` promotion policy is unchanged.
