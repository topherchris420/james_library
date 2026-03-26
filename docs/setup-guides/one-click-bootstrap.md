# One-Click Bootstrap

This page covers the current onboarding story for the repository checkout version of R.A.I.N. Lab.

## Recommended Setup Routes

### Windows

Run the root installer:

```powershell
.\INSTALL_RAIN.cmd
```

That path installs `uv`, creates `.venv`, syncs dependencies, fetches the prebuilt runtime into `bin/`, initializes `config.toml` and `.env` when needed, and then opens the first James handoff.

### macOS / Linux

Run the root installer:

```bash
./install.sh
```

That installer requires `uv` to be pre-installed (see <https://docs.astral.sh/uv/getting-started/installation/>), creates `.venv`, syncs the pinned Python requirements, runs `bootstrap_local.py`, and then opens the James handoff unless you pass `--no-greet`.

## After Install

The main product entrypoint is:

```bash
python rain_lab.py
```

Common next steps:

- Guided model/provider setup: `python rain_lab.py --mode first-run`
- Instant preview: `python rain_lab.py` and press Enter
- Readiness check: `python rain_lab.py --mode validate`

## Advanced And Legacy Paths

Legacy source-build scripts such as `scripts/bootstrap.sh` and `scripts/install.sh` still exist for compatibility and advanced environments.
They are not the primary recommendation for new users.

If you intentionally need source-build or container-heavy flows, review those scripts directly before use and treat them as advanced setup paths rather than the default onboarding story.

## Related Docs

- [../../README.md](../../README.md)
- [../../START_HERE.md](../../START_HERE.md)
- [../reference/cli/commands-reference.md](../reference/cli/commands-reference.md)
- [../reference/api/providers-reference.md](../reference/api/providers-reference.md)
- [../reference/api/channels-reference.md](../reference/api/channels-reference.md)
