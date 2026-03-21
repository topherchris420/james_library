# Production Readiness Gates

Use this as a pass/fail checklist before calling R.A.I.N. Lab "production-ready."

## Gate Matrix

| Gate | Pass Criteria | Verification |
|---|---|---|
| Runtime health | Chat and RLM launch successfully with non-empty output. | `python rain_lab.py --mode chat --topic "test"` and `python rain_lab.py --mode rlm --topic "test"` |
| UI behavior | `--ui auto` launches avatars when available and cleanly falls back to CLI when unavailable. | `python rain_lab.py --mode chat --ui auto --topic "test"` |
| Sidecar resilience | Bridge/client sidecars auto-restart after unexpected exit within restart budget. | Run with `--max-sidecar-restarts 2`, terminate sidecar process once, verify restart message/log. |
| Observability | JSONL launcher events are written with startup, sidecar, and exit lifecycle entries. | Check `meeting_archives/launcher_events.jsonl` after a run. |
| Health snapshot | One-screen health command reports LM Studio/API/model/UI/log status. | `python rain_health_check.py` or `RAIN_Lab_Health_Check.cmd` |
| Config safety | Runtime config errors are explicit and non-local endpoints require API key. | `python rain_lab.py --mode chat --config bad.toml --topic "test"` |
| Backup/restore | Backup command returns success and files can be restored. | `python rain_lab.py --mode backup -- --json` and validate restore path. |
| CI quality gate | Test and lint pipelines are green for main branch. | Verify GitHub Actions checks: tests/lint/security workflows. |
| Release hygiene | Changelog and docs match current commands and options. | Review `CHANGELOG.md`, `README.md`, `docs/TROUBLESHOOTING.md`. |

## Recommended Launch Defaults

Use these defaults for production-like local deployment:

```bash
python rain_lab.py \
  --mode chat \
  --ui auto \
  --restart-sidecars \
  --max-sidecar-restarts 2 \
  --launcher-log meeting_archives/launcher_events.jsonl \
  --topic "your topic"
```

## Hard Fail Conditions

Do not promote to production if any condition below is true:

- Unhandled runtime crashes in normal chat flow.
- UI mode `on` cannot keep sidecars alive within restart budget.
- Missing or unreadable launcher logs for production runs.
- CI red on main branch.
- Backup flow fails or restore instructions are unverified.
