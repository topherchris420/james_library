# Troubleshooting

## Quick triage

1. Run `python rain_health_check.py` (or `RAIN_Lab_Health_Check.cmd` on Windows).
2. Run `python rain_lab.py --mode preflight`.
3. Confirm your Python is supported (`3.10+`).

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

### 6) One-click installer or shortcut does nothing

Fix:
- Right-click `INSTALL_RAIN.cmd` and choose "Run as administrator" once.
- If PowerShell execution policy blocks scripts, run:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\INSTALL_RAIN.ps1`
- Recreate shortcuts only:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\INSTALL_RAIN.ps1 -SkipPreflight`
- If needed, run launcher directly:
  - `RAIN_Lab_Chat.cmd`

### 7) Health check reports launcher log not found

Behavior:
- `rain_health_check.py` reads launcher events from `meeting_archives/launcher_events.jsonl`.
- The file is created after you run `rain_lab.py` at least once.

Fix:
- Run one session: `python rain_lab.py --mode chat --topic "health-check seed"`
- Then re-run health check:
  - `RAIN_Lab_Health_Check.cmd`
  - or `python rain_health_check.py`

## Verification commands

- Preflight: `python rain_lab.py --mode preflight`
- Backup: `python rain_lab.py --mode backup -- --json`
- One-screen health check: `python rain_health_check.py`
- Runtime healthcheck:
  - `python -c "from rain_lab_runtime import runtime_healthcheck; import json; print(json.dumps(runtime_healthcheck(), indent=2))"`
