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
