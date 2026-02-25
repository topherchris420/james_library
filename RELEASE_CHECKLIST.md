# Release Checklist

Use this checklist before tagging a public local-first release.

## 1. Code + Quality

- [ ] `git status` is clean.
- [ ] Run full tests: `pytest -q`.
- [ ] Run lint: `ruff check .`.
- [ ] Run preflight: `python rain_lab.py --mode preflight`.
- [ ] Verify backup flow: `python rain_lab.py --mode backup -- --json`.

## 2. Reproducibility

- [ ] Update `requirements-pinned.txt` if dependency versions changed.
- [ ] Update `requirements-dev-pinned.txt` if tooling versions changed.
- [ ] Re-run bootstrap on a clean venv: `python bootstrap_local.py --recreate-venv`.
- [ ] Confirm CI workflows still pass with pinned files.

## 3. Documentation

- [ ] Update `CHANGELOG.md` with release notes and date.
- [ ] Confirm `README.md` quick-start commands are accurate.
- [ ] Confirm `docs/TROUBLESHOOTING.md` reflects known issues and fixes.
- [ ] Confirm `docs/BACKUP_RESTORE.md` matches current backup behavior.

## 4. Release + Verification

- [ ] Create release commit.
- [ ] Tag release (example): `git tag -a v2026.02.22 -m "R.A.I.N. Lab local-first release"`.
- [ ] Push commits and tag: `git push origin main --tags`.
- [ ] Verify fresh clone bootstrap from scratch.
