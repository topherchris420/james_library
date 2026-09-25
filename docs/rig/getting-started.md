# Getting Started with R.A.I.N. Rig

Rig is optional. If you only want the research meeting, run
`python rain_lab.py` and stop here.

## 1. Get the `rain` binary

Rig ships inside the Rust runtime. From a checkout:

```bash
cargo build --release          # binary at target/release/rain
```

Or use an installed `rain` binary. Rig needs no extra Cargo features, packages,
Docker, GPU libraries, or model downloads.

## 2. Diagnose

```bash
rain rig doctor
```

Each check prints `PASS`, `WARN`, `FAIL` or `SKIP`:

- `SKIP`: an optional extension is absent (Reticulum, LXMF, LM Studio, …).
  This is normal.
- `WARN`: something works but deserves attention (for example a hosted
  external service, an unpinned meeting model, or an external bind).
- `FAIL`: the configured node cannot work as configured (for example the
  default llama.cpp server is unreachable, or hosted inference is configured
  under `local` privacy). `rig doctor` exits non-zero.

## 3. Start a local model server (your choice)

Rig never starts these for you. Examples:

```bash
llama-server -m ~/models/your-model.gguf --port 8080     # llama.cpp
ollama serve && ollama pull qwen3:4b                     # Ollama
```

LM Studio: start its local server from the app.

## 4. Configure

```bash
rain rig setup --dry-run                   # show the plan, write nothing
rain rig setup --profile local             # asks before writing config.toml
rain rig setup --profile field --node-name field-kit-1
```

Setup writes a `[rig]` table and, under `local` privacy, offers to switch a
hosted default provider to a running local server. It edits `config.toml`
directly: only the `[rig]` tables and, when switching servers,
`default_provider` / `default_model` / `api_url` change. Comments, formatting
and every other key stay as written (setup verifies this before replacing the
file atomically), values that come only from environment variables are never
persisted, and encrypted secrets are untouched. It never downloads models, installs software, changes services or
firewall rules, or opens listeners. In a non-interactive shell it refuses to
write unless you pass `--yes`.

Resulting config:

```toml
[rig]
profile = "local"        # local | node | field
node_name = "rain-local" # lowercase letters, digits, '-'; 1-32 chars
# privacy = "local"      # local | hybrid | hosted (defaults from the profile)
```

## 5. Check the node

```bash
rain rig status
rain rig status --json   # machine-readable; logs go to stderr
rain rig models
```

`NODE STATUS` is one of:

- `READY`: everything required is usable.
- `DEGRADED`: usable, but something expected is missing, for example the
  default provider is unreachable or no local server runs under `local`
  privacy.
- `BLOCKED`: configuration contradicts policy, for example a hosted provider
  under `local` privacy, or a non-loopback gateway bind that is not allowed.

## 6. Run it

```bash
rain rig up --dry-run    # print the plan
rain rig up              # start the R.A.I.N. daemon (Ctrl-C to stop)
```

`rig up` starts only the R.A.I.N. daemon, on `[gateway] host`/`port`
(`127.0.0.1:42617` by default). A BLOCKED node starts nothing.

## Profiles

| Profile | Intent | Privacy default | Expects |
| --- | --- | --- | --- |
| `local` | Laptop/desktop running local inference | `local` | research library |
| `node` | Always-on mini PC or home server | `local` | research library, gateway |
| `field` | Local inference plus low-bandwidth transports | `local` | research library, Reticulum, LXMF, Skybridge |

Profiles are TOML files in `src/config/schema/rig_profiles/`. They only change
Rig defaults. Their schema rejects unknown keys, so a profile cannot change
security, autonomy, or bind policy.

## Privacy modes

| Mode | Behavior |
| --- | --- |
| `local` | Every inference provider the runtime builds (default, fallbacks, model routes, delegates) must use a loopback or private-network endpoint. Anything else fails with `privacy mode 'local' refuses inference provider …`. No silent hosted fallback. |
| `hybrid` | Local-first, hosted providers allowed when configured. Pre-Rig behavior and the default when `[rig]` is absent. |
| `hosted` | Hosted inference expected. Enforcement matches `hybrid`. |

CLI wrappers such as `claude-code` and `gemini-cli` count as hosted. So do
Ollama `:cloud` models. IP literals and `localhost` are classified directly.
Any other hostname (including `*.local`) is resolved, and counts as local only
when every address it resolves to is loopback or private. A lookup failure
counts as remote.

## Rollback

Delete the `[rig]` table from `config.toml`.
