# Config Reference

Canonical configuration schema is defined in:

- [`../src/config/schema.rs`](../src/config/schema.rs)

Configuration loading and merging logic:

- [`../src/config/mod.rs`](../src/config/mod.rs)

Treat config keys as public contract and coordinate changes with migration notes.

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
