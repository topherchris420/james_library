# Commands Reference

Primary launcher command:

```bash
python rain_lab.py
```

Core modes:

- `--mode first-run`
- `--mode chat --topic "..."`
- `--mode validate`
- `--mode status`
- `--mode models`
- `--mode backup -- --json`

## ZeroClaw runtime bridge commands

For the Rust runtime bridge entrypoint:

```bash
zeroclaw gateway
zeroclaw daemon
```

Notes:

- `zeroclaw gateway` and `zeroclaw daemon` use `gateway.port` from config when `--port` is not provided.
- For a Body-daemon bridge default, set `gateway.port = 4200` in config or `ZEROCLAW_GATEWAY_PORT=4200` in env.
- Startup is blocked if emergency-stop is engaged at `kill-all` or `network-kill` level.

For troubleshooting, see [`troubleshooting.md`](troubleshooting.md).
