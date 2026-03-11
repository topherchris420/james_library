# Troubleshooting

## Quick triage

1. Run `python rain_lab.py --mode validate` (or `RAIN_Lab_Validate.cmd` on Windows).
2. Run `python rain_lab.py --mode health` for the one-screen snapshot.
3. Run `python rain_lab.py --mode preflight` if you want the detailed legacy diagnostic output.
4. If you plan to use Rust-side operations, run `python rain_lab.py --mode status`.
5. Confirm your Python is supported (`3.10+`).

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

### 6) `status` or `models` says the embedded ZeroClaw runtime is unavailable

Behavior:
- `rain_lab.py` looks for a built `zeroclaw` binary in local `target` folders, `PATH`, and `~/.cargo/bin`.
- If Cargo is available, the launcher can fall back to `cargo run`, which may compile the Rust runtime on first use.

Fix:
- Re-run bootstrap so it can prepare the runtime:
  - `python bootstrap_local.py --skip-preflight`
- Or build directly:
  - `cargo build --release --locked --bin zeroclaw`
- Or point the launcher at a prebuilt binary:
  - `python rain_lab.py --mode status --zeroclaw-bin path/to/zeroclaw`
- If you only need Python research flows, continue using:
  - `python rain_lab.py --mode chat ...`
  - `python rain_lab.py --mode rlm ...`

### 7) One-click installer or shortcut does nothing

Fix:
- Right-click `INSTALL_RAIN.cmd` and choose "Run as administrator" once.
- If PowerShell execution policy blocks scripts, run:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\INSTALL_RAIN.ps1`
- Recreate shortcuts only:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\INSTALL_RAIN.ps1 -SkipPreflight`
- If needed, run launcher directly:
  - `RAIN_Lab_Start.cmd`
  - `RAIN_Lab_Chat.cmd`

### 8) Health snapshot reports launcher log not found

Behavior:
- `python rain_lab.py --mode health` reads launcher events from `meeting_archives/launcher_events.jsonl`.
- The file is created after you run `rain_lab.py` at least once.

Fix:
- Run one session: `python rain_lab.py --mode chat --topic "health-check seed"`
- Then re-run the health snapshot:
  - `R.A.I.N. Lab Health Snapshot`
  - or `python rain_lab.py --mode health`

## Verification commands

- Preflight: `python rain_lab.py --mode preflight`
- Full validation: `python rain_lab.py --mode validate`
- One-screen health snapshot: `python rain_lab.py --mode health`
- Embedded runtime: `python rain_lab.py --mode status`
- Model status: `python rain_lab.py --mode models`
- Backup: `python rain_lab.py --mode backup -- --json`
- Runtime healthcheck:
  - `python -c "from rain_lab_runtime import runtime_healthcheck; import json; print(json.dumps(runtime_healthcheck(), indent=2))"`
