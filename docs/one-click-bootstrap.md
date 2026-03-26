# One-click Bootstrap

R.A.I.N. Lab now has one product story and two setup routes.

## Recommended Routes

### Windows

Use the one-click installer from the repository root:

```powershell
.\INSTALL_RAIN.cmd
```

That path:

- installs `uv`
- creates the Python environment
- syncs dependencies
- fetches the prebuilt Rust runtime into `bin/`
- creates `config.toml` and `.env` when needed
- hands off to James with `chat_with_james.py --greet`

### macOS / Linux

Use the one-click repo installer:

```bash
./install.sh
```

Under the hood, `install.sh` requires `uv` to be pre-installed (see <https://docs.astral.sh/uv/getting-started/installation/>), creates `.venv`, compiles and syncs the pinned requirements, runs `bootstrap_local.py`, and then hands off to James unless you pass `--no-greet`.

## After Install

The main product entrypoint is:

```bash
python rain_lab.py
```

Use `python rain_lab.py --mode first-run` when you want guided model/provider setup, and `python rain_lab.py --mode validate` when you want a readiness check.

## Legacy Compatibility Scripts

The repository still contains `scripts/bootstrap.sh` and `scripts/install.sh` for older/source-build flows.
They are compatibility paths, not the primary onboarding recommendation for new users.
