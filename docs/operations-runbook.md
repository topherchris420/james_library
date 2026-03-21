# Operations Runbook

## Baseline checks

```bash
python rain_lab.py --mode validate
python rain_lab.py --mode status
python rain_health_check.py
```

## Recovery checks

- Backup status: `python rain_lab.py --mode backup -- --json`
- Troubleshooting guide: [`troubleshooting.md`](troubleshooting.md)
- Production gates: [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md)
