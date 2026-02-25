# Backup and Restore

This project is local-first. Backups are zip snapshots of your workspace.

## Create a backup

Recommended:

```bash
python rain_lab.py --mode backup
```

JSON output:

```bash
python rain_lab.py --mode backup -- --json
```

Direct script usage:

```bash
python rain_lab_backup.py --library . --json
```

Default output:
- `./backups/rain_lab_backup_YYYYMMDD_HHMMSS.zip`

Safety behavior:
- Backup output is restricted to `./backups` by default.
- To allow an external output path, set:
  - `RAIN_ALLOW_EXTERNAL_BACKUP_PATH=1`

## What is included

- Source files and project docs in your workspace.
- A `backup_manifest.json` file inside the zip.

## What is excluded

- `.git`, virtual envs, cache folders.
- `backups/` folder itself.
- `meeting_archives/runtime_events.jsonl`.
- Vendored folders (`openclaw-main`, `vers3dynamics_lab`, `rlm-main`).

## Restore from backup

1. Create a clean folder:
   - `mkdir rain_restore && cd rain_restore`
2. Unzip the snapshot there.
3. Recreate environment:
   - `python bootstrap_local.py --recreate-venv`
4. Validate:
   - `python rain_lab.py --mode preflight`
5. Resume usage:
   - `python rain_lab.py --mode chat --topic "..."`

## Verify backup integrity

PowerShell:

```powershell
tar -tf .\backups\rain_lab_backup_YYYYMMDD_HHMMSS.zip | Select-Object -First 30
```

Python:

```bash
python -c "import zipfile; z=zipfile.ZipFile('backups/rain_lab_backup_YYYYMMDD_HHMMSS.zip'); print(len(z.namelist()))"
```
