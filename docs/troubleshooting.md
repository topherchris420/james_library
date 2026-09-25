# R.A.I.N. Lab Troubleshooting

This lowercase path is the canonical runtime-contract entry for troubleshooting.

Last verified: **February 20, 2026**.

## Installation / Bootstrap

### `curl` or `uv` setup fails

Symptom:

- `install.sh` cannot download or locate `uv`

Fix:

```bash
curl --version
./install.sh
```

If `curl` is missing, install it with your platform package manager first.
If you already have `uv`, make sure it is in `PATH` or at `~/.local/bin/uv`.

### Reset the local Python environment

Symptom:

- `.venv` is broken or dependencies look out of sync

Fix:

```bash
./install.sh --recreate-venv
```

### Prebuilt runtime fetch fails

Symptoms:

- `bootstrap_local.py` fails while calling the GitHub Releases API
- installer completes Python setup but cannot fetch the Rust runtime

Fixes:

```bash
python bootstrap_local.py --release-tag latest
python rain_lab.py --mode validate
```

If the network is restricted, retry later or download the matching release asset manually into `bin/`.

## Runtime / Gateway

### Gateway unreachable

Checks:

```bash
R.A.I.N. status
R.A.I.N. doctor
```

Verify `~/.R.A.I.N./config.toml`:

- `[gateway].host` (default `127.0.0.1`)
- `[gateway].port` (default `42617`)
- `allow_public_bind` only when intentionally exposing LAN/public interfaces

### Pairing / auth failures on webhook

Checks:

1. Ensure pairing completed (`/pair` flow)
1. Ensure bearer token is current
1. Re-run diagnostics:

```bash
R.A.I.N. doctor
```

## Channel Issues

### Telegram conflict: `terminated by other getUpdates request`

Cause:

- multiple pollers using same bot token

Fix:

- keep only one active runtime for that token
- stop extra `R.A.I.N. daemon` / `R.A.I.N. channel start` processes

### Channel unhealthy in `channel doctor`

Checks:

```bash
R.A.I.N. channel doctor
```

Then verify channel-specific credentials + allowlist fields in config.

## Service Mode

### Service installed but not running

Checks:

```bash
R.A.I.N. service status
```

Recovery:

```bash
R.A.I.N. service stop
R.A.I.N. service start
```

Linux logs:

```bash
journalctl --user -u R.A.I.N..service -f
```

## Installer URL

```bash
./install.sh
```

For Windows, use `.\INSTALL_RAIN.cmd`.

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

## R.A.I.N. Rig

### `rain rig doctor` reports `FAIL default provider … not reachable`

The configured local server is not running. Start it yourself (Rig never
starts third-party servers), for example `llama-server -m model.gguf --port 8080`
or `ollama serve`, then rerun `rain rig doctor`.

### `privacy mode 'local' refuses inference provider '…'`

`[rig]` privacy is `local` (explicitly or via a profile) and a hosted provider
is configured as default, fallback, model route, or delegate. Point it at a
local server (`rain rig setup` proposes this when one is running) or set
`[rig] privacy = "hybrid"` to allow hosted inference explicitly.

### Node status is `BLOCKED` with `EXTERNAL BIND`

`[gateway] host` is not loopback and no `allow_public_bind` or tunnel allows
it. Set `host = "127.0.0.1"` unless remote access is intended.

### `research library not found`

Run `rain rig` from the James Library checkout or pass `--library <path>`.

### `meeting inference` warns about a hosted model

The Python meeting's model is an Ollama `:cloud` model or is unpinned. Set
`RAIN_LLM_MODEL` to a model listed by `rain rig models`. The runtime's
`local` privacy enforcement does not govern the separate Python meeting process.

### `--json` output mixed with log lines

Rig logs go to stderr; redirect with `2>/dev/null` or set `RUST_LOG=error`.
