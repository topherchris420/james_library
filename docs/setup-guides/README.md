# Setup Guides

Use this section when you already know you are doing setup or platform-specific maintenance.
If you are new to the product, start with [../../README.md](../../README.md) and [../../START_HERE.md](../../START_HERE.md).

## Start Path

1. Main overview and install routes: [../../README.md](../../README.md)
2. Plain-English product orientation: [../../START_HERE.md](../../START_HERE.md)
3. Current bootstrap/install flow: [one-click-bootstrap.md](one-click-bootstrap.md)
4. Update or uninstall on macOS: [macos-update-uninstall.md](macos-update-uninstall.md)
5. Find commands by task: [../reference/cli/commands-reference.md](../reference/cli/commands-reference.md)

## Choose Your Path

| Scenario | Recommended path |
|----------|------------------|
| I want the fastest Windows install | Run `.\INSTALL_RAIN.cmd` from the repo root |
| I am on macOS/Linux | Use the `uv` + `bootstrap_local.py` flow in [one-click-bootstrap.md](one-click-bootstrap.md) |
| I want guided model/provider setup | `python rain_lab.py --mode first-run` |
| I want the fastest preview with no model | `python rain_lab.py` and press Enter for the instant demo |
| I just want a readiness check | `python rain_lab.py --mode validate` |

## Onboarding and Validation

- Main product entrypoint: `python rain_lab.py`
- Guided setup: `python rain_lab.py --mode first-run`
- Instant preview: `python rain_lab.py --mode demo --preset startup-debate`
- Validate environment: `python rain_lab.py --mode validate`
- Existing config protection still applies when setup rewrites `.env` or `config.toml`

## Next

- Runtime operations: [../ops/README.md](../ops/README.md)
- Reference catalogs: [../reference/README.md](../reference/README.md)
- macOS lifecycle tasks: [macos-update-uninstall.md](macos-update-uninstall.md)
