# R.A.I.N. Operations Runbook

This runbook is for operators who maintain availability, security posture, and incident response.

Last verified: **February 18, 2026**.

## Scope

Use this document for day-2 operations:

- starting and supervising runtime
- health checks and diagnostics
- safe rollout and rollback
- incident triage and recovery

For first-time installation, start from [one-click-bootstrap.md](../setup-guides/one-click-bootstrap.md).

## Runtime Modes

| Mode | Command | When to use |
|---|---|---|
| Foreground runtime | `R.A.I.N. daemon` | local debugging, short-lived sessions |
| Foreground gateway only | `R.A.I.N. gateway` | webhook endpoint testing |
| User service | `R.A.I.N. service install && R.A.I.N. service start` | persistent operator-managed runtime |
| Docker / Podman | `docker compose up -d` | containerized deployment |

## Docker / Podman Runtime

If you installed via `./install.sh --docker`, the container exits after onboarding. To run
R.A.I.N. as a long-lived container, use the repository `docker-compose.yml` or start a
container manually against the persisted data directory.

### Recommended: docker-compose

```bash
# Start (detached, auto-restarts on reboot)
docker compose up -d

# Stop
docker compose down

# Restart
docker compose up -d
```

Replace `docker` with `podman` if using Podman.

### Manual container lifecycle

```bash
# Start a new container from the bootstrap image
docker run -d --name R.A.I.N. \
  --restart unless-stopped \
  -v "$PWD/.R.A.I.N.-docker/.R.A.I.N.:/R.A.I.N.-data/.R.A.I.N." \
  -v "$PWD/.R.A.I.N.-docker/workspace:/R.A.I.N.-data/workspace" \
  -e HOME=/R.A.I.N.-data \
  -e R.A.I.N._WORKSPACE=/R.A.I.N.-data/workspace \
  -p 42617:42617 \
  R.A.I.N.-bootstrap:local \
  gateway

# Stop (preserves config and workspace)
docker stop R.A.I.N.

# Restart a stopped container
docker start R.A.I.N.

# View logs
docker logs -f R.A.I.N.

# Health check
docker exec R.A.I.N. R.A.I.N. status
```

For Podman, add `--userns keep-id --user "$(id -u):$(id -g)"` and append `:Z` to volume mounts.

### Key detail: do not re-run install.sh to restart

Re-running `install.sh --docker` rebuilds the image and re-runs onboarding. To simply
restart, use `docker start`, `docker compose up -d`, or `podman start`.

For full setup instructions, see [one-click-bootstrap.md](../setup-guides/one-click-bootstrap.md#stopping-and-restarting-a-dockerpodman-container).

## Baseline Operator Checklist

1. Validate configuration:

```bash
R.A.I.N. status
```

2. Verify diagnostics:

```bash
R.A.I.N. doctor
R.A.I.N. channel doctor
```

3. Start runtime:

```bash
R.A.I.N. daemon
```

4. For persistent user session service:

```bash
R.A.I.N. service install
R.A.I.N. service start
R.A.I.N. service status
```

## Health and State Signals

| Signal | Command / File | Expected |
|---|---|---|
| Config validity | `R.A.I.N. doctor` | no critical errors |
| Channel connectivity | `R.A.I.N. channel doctor` | configured channels healthy |
| Runtime summary | `R.A.I.N. status` | expected provider/model/channels |
| Daemon heartbeat/state | `~/.R.A.I.N./daemon_state.json` | file updates periodically |

## Logs and Diagnostics

### macOS / Windows (service wrapper logs)

- `~/.R.A.I.N./logs/daemon.stdout.log`
- `~/.R.A.I.N./logs/daemon.stderr.log`

### Linux (systemd user service)

```bash
journalctl --user -u R.A.I.N..service -f
```

## Incident Triage Flow (Fast Path)

1. Snapshot system state:

```bash
R.A.I.N. status
R.A.I.N. doctor
R.A.I.N. channel doctor
```

2. Check service state:

```bash
R.A.I.N. service status
```

3. If service is unhealthy, restart cleanly:

```bash
R.A.I.N. service stop
R.A.I.N. service start
```

4. If channels still fail, verify allowlists and credentials in `~/.R.A.I.N./config.toml`.

5. If gateway is involved, verify bind/auth settings (`[gateway]`) and local reachability.

## Safe Change Procedure

Before applying config changes:

1. backup `~/.R.A.I.N./config.toml`
2. apply one logical change at a time
3. run `R.A.I.N. doctor`
4. restart daemon/service
5. verify with `status` + `channel doctor`

## Rollback Procedure

If a rollout regresses behavior:

1. restore previous `config.toml`
2. restart runtime (`daemon` or `service`)
3. confirm recovery via `doctor` and channel health checks
4. document incident root cause and mitigation

## Related Docs

- [one-click-bootstrap.md](../setup-guides/one-click-bootstrap.md)
- [troubleshooting.md](./troubleshooting.md)
- [config-reference.md](../reference/api/config-reference.md)
- [commands-reference.md](../reference/cli/commands-reference.md)
