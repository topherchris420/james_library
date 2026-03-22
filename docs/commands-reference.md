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
