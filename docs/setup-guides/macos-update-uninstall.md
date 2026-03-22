# macOS Update and Uninstall Guide

This page documents supported update and uninstall procedures for R.A.I.N. on macOS (OS X).

Last verified: **February 22, 2026**.

## 1) Check current install method

```bash
which R.A.I.N.
R.A.I.N. --version
```

Typical locations:

- Homebrew: `/opt/homebrew/bin/R.A.I.N.` (Apple Silicon) or `/usr/local/bin/R.A.I.N.` (Intel)
- Cargo/bootstrap/manual: `~/.cargo/bin/R.A.I.N.`

If both exist, your shell `PATH` order decides which one runs.

## 2) Update on macOS

### A) Homebrew install

```bash
brew update
brew upgrade R.A.I.N.
R.A.I.N. --version
```

### B) Clone + bootstrap install

From your local repository checkout:

```bash
git pull --ff-only
./install.sh --prefer-prebuilt
R.A.I.N. --version
```

If you want source-only update:

```bash
git pull --ff-only
cargo install --path . --force --locked
R.A.I.N. --version
```

### C) Manual prebuilt binary install

Re-run your download/install flow with the latest release asset, then verify:

```bash
R.A.I.N. --version
```

## 3) Uninstall on macOS

### A) Stop and remove background service first

This prevents the daemon from continuing to run after binary removal.

```bash
R.A.I.N. service stop || true
R.A.I.N. service uninstall || true
```

Service artifacts removed by `service uninstall`:

- `~/Library/LaunchAgents/com.R.A.I.N..daemon.plist`

### B) Remove the binary by install method

Homebrew:

```bash
brew uninstall R.A.I.N.
```

Cargo/bootstrap/manual (`~/.cargo/bin/R.A.I.N.`):

```bash
cargo uninstall R.A.I.N. || true
rm -f ~/.cargo/bin/R.A.I.N.
```

### C) Optional: remove local runtime data

Only run this if you want a full cleanup of config, auth profiles, logs, and workspace state.

```bash
rm -rf ~/.R.A.I.N.
```

## 4) Verify uninstall completed

```bash
command -v R.A.I.N. || echo "R.A.I.N. binary not found"
pgrep -fl R.A.I.N. || echo "No running R.A.I.N. process"
```

If `pgrep` still finds a process, stop it manually and re-check:

```bash
pkill -f R.A.I.N.
```

## Related docs

- [One-Click Bootstrap](one-click-bootstrap.md)
- [Commands Reference](../reference/cli/commands-reference.md)
- [Troubleshooting](../ops/troubleshooting.md)
