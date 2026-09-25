# Config Reference

Canonical configuration schema is defined in:

- [`../src/config/schema/mod.rs`](../src/config/schema/mod.rs)

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

## R.A.I.N. Rig section (`[rig]`, added 2026-09)

Optional and omitted from generated configs while unset; omitting it keeps
pre-Rig behavior. Unknown keys are rejected.

```toml
[rig]
profile = "local"        # local | node | field (built-in, human-readable TOML)
node_name = "rain-local" # shareable name: lowercase letters, digits, '-'; 1-32 chars
privacy = "local"        # local | hybrid | hosted; default: profile's, else hybrid
```

- `privacy = "local"` makes provider construction refuse any inference
  endpoint that is not loopback or private-network, including fallback
  providers, model routes, and delegate agents (typed, non-retryable error;
  no silent hosted fallback). `hybrid` is the default pre-Rig behavior;
  `hosted` is informational and enforces like `hybrid`.
- All built-in profiles default to `local` privacy. Profiles cannot change
  security, autonomy, or bind policy.
- Rig reads these environment variables for reporting only:
  `RAIN_LLM_BASE_URL`, `RAIN_LLM_MODEL`, `LM_STUDIO_BASE_URL`,
  `LM_STUDIO_MODEL`, `RAIN_DECISION_MODE`, `RAIN_LAYA_CHECKPOINT`,
  `RAIN_JUDGMENT_PROVIDER`, `TYPESAFE_API_KEY` (presence only).
- Rig state: `<workspace>/rig/dispositions.jsonl` (action-boundary records;
  payload digests only).

Rollback: delete the `[rig]` table. Details: [`rig/getting-started.md`](rig/getting-started.md).
