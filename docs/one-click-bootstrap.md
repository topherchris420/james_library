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

Use the fetch-first source checkout flow:

```bash
uv python install 3.12
uv venv .venv --python 3.12
uv pip compile requirements-pinned.txt -o uv.lock
uv pip sync --python .venv/bin/python uv.lock
uv run --python .venv/bin/python bootstrap_local.py
uv run --python .venv/bin/python rain_lab.py
```

`bootstrap_local.py` fetches the latest compatible prebuilt Rust engine, copies `config.toml` from `config.example.toml` when needed, prompts for an API key when `.env` is missing, and runs preflight checks unless you skip them.

## After Install

The main product entrypoint is:

```bash
python rain_lab.py
```

Use `python rain_lab.py --mode first-run` when you want guided model/provider setup, and `python rain_lab.py --mode validate` when you want a readiness check.

## Legacy Compatibility Scripts

The repository still contains `scripts/bootstrap.sh` and `scripts/install.sh` for older/source-build flows.
They are compatibility paths, not the primary onboarding recommendation for new users.
