# Commands Reference

Primary launcher command:

```bash
python rain_lab.py
```

Core modes:

- `--mode first-run`
- `--mode chat --topic "..."`
- `--mode chat --topic "..." --temp 0.85 --max-tokens 320` for more exploratory experiment output
- `--mode validate`
- `--mode status`
- `--mode models`
- `--mode backup -- --json`

In chat meetings, persistent repetition triggers an evidence check, then a
falsifiable alternative, then an earlier wrap-up if needed. Each attempt allows
a full panel round; closing turns never restart the debate or exceed the total
turn limit. Recovery actions are saved in the session artifact. See
[adaptive meeting recovery](meeting-recovery.md) for details and limitations.

## R.A.I.N. runtime bridge commands

For the Rust runtime bridge entrypoint:

```bash
R.A.I.N. gateway
R.A.I.N. daemon
```

Notes:

- `R.A.I.N. gateway` and `R.A.I.N. daemon` use `gateway.port` from config when `--port` is not provided.
- For a Body-daemon bridge default, set `gateway.port = 4200` in config or `R.A.I.N._GATEWAY_PORT=4200` in env.
- Startup is blocked if emergency-stop is engaged at `kill-all` or `network-kill` level.

For troubleshooting, see [`troubleshooting.md`](troubleshooting.md).

## Typed judgment

Run the strict five-stage promotion boundary against a curated evidence packet:

```bash
python rain_lab.py judge --evidence cycle.json
python rain_lab.py judge --replay meeting_archives/session_artifacts/session_<id>.json
```

This command is separate from conversational chat. Remote evaluation is off by
default. Recorded replay never contacts a provider. See
[`typed-judgment.md`](typed-judgment.md) for the packet schema and policy.

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

## R.A.I.N. Rig (optional)

Rig is an opt-in node layer in the Rust runtime; `python rain_lab.py` does not
depend on it. See [`rig/README.md`](rig/README.md).

```bash
rain rig status [--json]          # node snapshot and readiness (READY/DEGRADED/BLOCKED)
rain rig doctor [--json]          # PASS/WARN/FAIL/SKIP; exits non-zero on FAIL
rain rig models [--json]          # models on llama.cpp / Ollama / LM Studio / meeting endpoint
rain rig capabilities [--json]    # capability registry with current states
rain rig peers [--json]           # shareable identity, peer transports, LXMF peers via the bridge
rain rig setup [--profile local|node|field] [--node-name NAME] [--privacy local|hybrid|hosted] [--yes] [--dry-run]
rain rig up [--dry-run]           # start the daemon (and the bridge when [rig.bridge] is enabled)
rain rig send --transport lxmf --to ADDR --text TEXT   # LXMF message via the bridge
rain rig receive [--max N] [--json]                    # drain bridge messages through the inbox
rain rig radio status|encode|decode|listen   # Skybridge modem, receive-only receiver input
rain rig radio transmit --frequency-hz HZ --power-w W --text TEXT   # rig-rf-transmit builds only
rain rig --library PATH <command> # point discovery at a James Library checkout
```

- Discovery probes only loopback/private-network endpoints and never contacts
  hosted services.
- `setup` asks before writing `config.toml` (non-interactive runs need
  `--yes`) and never installs, downloads, or opens listeners.
- `up` starts only R.A.I.N.-owned services (the daemon, plus the bridge sidecar
  when `[rig.bridge] enabled = true`); a BLOCKED node starts nothing.
- `send`/`receive` require `[rig.bridge] enabled = true` and a running bridge.
  `send` records its disposition before contacting the bridge; `receive`
  classifies messages as `PING`, `IDENTITY?` or inert notes.
- `radio encode` applies Hamming(7,4) FEC unless `--no-fec`; messages over
  200 B are fragmented (up to 1000 B). `radio listen --seconds N` (1–300) runs
  the `[rig.radio] receive` command.
- `radio transmit` is rejected unless the binary was built with
  `--features rig-rf-transmit` and `[rig.radio]` sets `callsign`,
  `max_power_w` and `[rig.radio.transmit]`. It requires typing the callsign at
  an interactive terminal; models can never transmit.
- Rig commands log at WARN to stderr by default so `--json` stays clean.
