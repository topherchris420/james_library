# Troubleshooting

## Quick triage

1. Run `python rain_lab.py --mode preflight`.
2. Confirm your Python is supported (`3.10+`).
3. Confirm LM Studio is reachable at `http://127.0.0.1:1234/v1/models`.

## Common issues

### 1) `runtime error: unable to generate response`

Likely causes:
- LM Studio is not running.
- Model is not loaded.
- Timeout too low for your machine.

Fix:
- Start LM Studio and load your model.
- Increase timeout:
  - PowerShell: `$env:RAIN_RUNTIME_TIMEOUT_S="180"`
  - Bash: `export RAIN_RUNTIME_TIMEOUT_S=180`

### 2) No trace file where expected

Behavior:
- Trace path defaults to `meeting_archives/runtime_events.jsonl` inside the workspace.
- External trace paths are blocked unless explicitly enabled.

Fix:
- Keep trace path inside repo, or set:
  - `RAIN_ALLOW_EXTERNAL_TRACE_PATH=1`

### 3) Unicode/console rendering issues on Windows

Fix:
- Use the current launcher (`rain_lab.py`) which is encoding-safe.
- If needed, run commands with UTF-8:
  - `python -X utf8 rain_lab.py --mode preflight`

### 4) Preflight says LM Studio not reachable

Fix:
- Confirm port and endpoint:
  - `http://127.0.0.1:1234/v1/models`
- Update environment if non-default:
  - `LM_STUDIO_BASE_URL`
  - `LM_STUDIO_MODEL`

### 5) Backup command fails with path safety error

Behavior:
- Backup output is intentionally restricted to `./backups` by default.

Fix:
- Use default output, or explicitly allow external output:
  - `RAIN_ALLOW_EXTERNAL_BACKUP_PATH=1`

## Verification commands

- Preflight: `python rain_lab.py --mode preflight`
- Backup: `python rain_lab.py --mode backup -- --json`
- Runtime healthcheck:
  - `python -c "from rain_lab_runtime import runtime_healthcheck; import json; print(json.dumps(runtime_healthcheck(), indent=2))"`
