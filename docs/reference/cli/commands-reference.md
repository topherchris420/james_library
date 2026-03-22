# R.A.I.N. Commands Reference

This reference is derived from the current CLI surface (`R.A.I.N. --help`).

Last verified: **February 21, 2026**.

## Top-Level Commands

| Command | Purpose |
|---|---|
| `onboard` | Initialize workspace/config quickly or interactively |
| `agent` | Run interactive chat or single-message mode |
| `gateway` | Start webhook and WhatsApp HTTP gateway |
| `daemon` | Start supervised runtime (gateway + channels + optional heartbeat/scheduler) |
| `service` | Manage user-level OS service lifecycle |
| `doctor` | Run diagnostics and freshness checks |
| `status` | Print current configuration and system summary |
| `estop` | Engage/resume emergency stop levels and inspect estop state |
| `cron` | Manage scheduled tasks |
| `models` | Refresh provider model catalogs |
| `providers` | List provider IDs, aliases, and active provider |
| `channel` | Manage channels and channel health checks |
| `integrations` | Inspect integration details |
| `skills` | List/install/remove skills |
| `migrate` | Import from external runtimes (currently OpenClaw) |
| `config` | Export machine-readable config schema |
| `completions` | Generate shell completion scripts to stdout |
| `hardware` | Discover and introspect USB hardware |
| `peripheral` | Configure and flash peripherals |

## Command Groups

### `onboard`

- `R.A.I.N. onboard`
- `R.A.I.N. onboard --channels-only`
- `R.A.I.N. onboard --force`
- `R.A.I.N. onboard --reinit`
- `R.A.I.N. onboard --api-key <KEY> --provider <ID> --memory <sqlite|lucid|markdown|none>`
- `R.A.I.N. onboard --api-key <KEY> --provider <ID> --model <MODEL_ID> --memory <sqlite|lucid|markdown|none>`
- `R.A.I.N. onboard --api-key <KEY> --provider <ID> --model <MODEL_ID> --memory <sqlite|lucid|markdown|none> --force`

`onboard` safety behavior:

- If `config.toml` already exists, onboarding offers two modes:
  - Full onboarding (overwrite `config.toml`)
  - Provider-only update (update provider/model/API key while preserving existing channels, tunnel, memory, hooks, and other settings)
- In non-interactive environments, existing `config.toml` causes a safe refusal unless `--force` is passed.
- Use `R.A.I.N. onboard --channels-only` when you only need to rotate channel tokens/allowlists.
- Use `R.A.I.N. onboard --reinit` to start fresh. This backs up your existing config directory with a timestamp suffix and creates a new configuration from scratch.

### `agent`

- `R.A.I.N. agent`
- `R.A.I.N. agent -m "Hello"`
- `R.A.I.N. agent --provider <ID> --model <MODEL> --temperature <0.0-2.0>`
- `R.A.I.N. agent --peripheral <board:path>`

Tip:

- In interactive chat, you can ask for route changes in natural language (for example “conversation uses kimi, coding uses gpt-5.3-codex”); the assistant can persist this via tool `model_routing_config`.

### `gateway` / `daemon`

- `R.A.I.N. gateway [--host <HOST>] [--port <PORT>]`
- `R.A.I.N. daemon [--host <HOST>] [--port <PORT>]`

### `estop`

- `R.A.I.N. estop` (engage `kill-all`)
- `R.A.I.N. estop --level network-kill`
- `R.A.I.N. estop --level domain-block --domain "*.chase.com" [--domain "*.paypal.com"]`
- `R.A.I.N. estop --level tool-freeze --tool shell [--tool browser]`
- `R.A.I.N. estop status`
- `R.A.I.N. estop resume`
- `R.A.I.N. estop resume --network`
- `R.A.I.N. estop resume --domain "*.chase.com"`
- `R.A.I.N. estop resume --tool shell`
- `R.A.I.N. estop resume --otp <123456>`

Notes:

- `estop` commands require `[security.estop].enabled = true`.
- When `[security.estop].require_otp_to_resume = true`, `resume` requires OTP validation.
- OTP prompt appears automatically if `--otp` is omitted.

### `service`

- `R.A.I.N. service install`
- `R.A.I.N. service start`
- `R.A.I.N. service stop`
- `R.A.I.N. service restart`
- `R.A.I.N. service status`
- `R.A.I.N. service uninstall`

### `cron`

- `R.A.I.N. cron list`
- `R.A.I.N. cron add <expr> [--tz <IANA_TZ>] <command>`
- `R.A.I.N. cron add-at <rfc3339_timestamp> <command>`
- `R.A.I.N. cron add-every <every_ms> <command>`
- `R.A.I.N. cron once <delay> <command>`
- `R.A.I.N. cron remove <id>`
- `R.A.I.N. cron pause <id>`
- `R.A.I.N. cron resume <id>`

Notes:

- Mutating schedule/cron actions require `cron.enabled = true`.
- Shell command payloads for schedule creation (`create` / `add` / `once`) are validated by security command policy before job persistence.

### `models`

- `R.A.I.N. models refresh`
- `R.A.I.N. models refresh --provider <ID>`
- `R.A.I.N. models refresh --force`

`models refresh` currently supports live catalog refresh for provider IDs: `openrouter`, `openai`, `anthropic`, `groq`, `mistral`, `deepseek`, `xai`, `together-ai`, `gemini`, `ollama`, `llamacpp`, `sglang`, `vllm`, `astrai`, `venice`, `fireworks`, `cohere`, `moonshot`, `glm`, `zai`, `qwen`, and `nvidia`.

### `doctor`

- `R.A.I.N. doctor`
- `R.A.I.N. doctor models [--provider <ID>] [--use-cache]`
- `R.A.I.N. doctor traces [--limit <N>] [--event <TYPE>] [--contains <TEXT>]`
- `R.A.I.N. doctor traces --id <TRACE_ID>`

`doctor traces` reads runtime tool/model diagnostics from `observability.runtime_trace_path`.

### `channel`

- `R.A.I.N. channel list`
- `R.A.I.N. channel start`
- `R.A.I.N. channel doctor`
- `R.A.I.N. channel bind-telegram <IDENTITY>`
- `R.A.I.N. channel add <type> <json>`
- `R.A.I.N. channel remove <name>`

Runtime in-chat commands (Telegram/Discord while channel server is running):

- `/models`
- `/models <provider>`
- `/model`
- `/model <model-id>`
- `/new`

Channel runtime also watches `config.toml` and hot-applies updates to:
- `default_provider`
- `default_model`
- `default_temperature`
- `api_key` / `api_url` (for the default provider)
- `reliability.*` provider retry settings

`add/remove` currently route you back to managed setup/manual config paths (not full declarative mutators yet).

### `integrations`

- `R.A.I.N. integrations info <name>`

### `skills`

- `R.A.I.N. skills list`
- `R.A.I.N. skills audit <source_or_name>`
- `R.A.I.N. skills install <source>`
- `R.A.I.N. skills remove <name>`

`<source>` accepts git remotes (`https://...`, `http://...`, `ssh://...`, and `git@host:owner/repo.git`) or a local filesystem path.

`skills install` always runs a built-in static security audit before the skill is accepted. The audit blocks:
- symlinks inside the skill package
- script-like files (`.sh`, `.bash`, `.zsh`, `.ps1`, `.bat`, `.cmd`)
- high-risk command snippets (for example pipe-to-shell payloads)
- markdown links that escape the skill root, point to remote markdown, or target script files

Use `skills audit` to manually validate a candidate skill directory (or an installed skill by name) before sharing it.

Skill manifests (`SKILL.toml`) support `prompts` and `[[tools]]`; both are injected into the agent system prompt at runtime, so the model can follow skill instructions without manually reading skill files.

### `migrate`

- `R.A.I.N. migrate openclaw [--source <path>] [--dry-run]`

### `config`

- `R.A.I.N. config schema`

`config schema` prints a JSON Schema (draft 2020-12) for the full `config.toml` contract to stdout.

### `completions`

- `R.A.I.N. completions bash`
- `R.A.I.N. completions fish`
- `R.A.I.N. completions zsh`
- `R.A.I.N. completions powershell`
- `R.A.I.N. completions elvish`

`completions` is stdout-only by design so scripts can be sourced directly without log/warning contamination.

### `hardware`

- `R.A.I.N. hardware discover`
- `R.A.I.N. hardware introspect <path>`
- `R.A.I.N. hardware info [--chip <chip_name>]`

### `peripheral`

- `R.A.I.N. peripheral list`
- `R.A.I.N. peripheral add <board> <path>`
- `R.A.I.N. peripheral flash [--port <serial_port>]`
- `R.A.I.N. peripheral setup-uno-q [--host <ip_or_host>]`
- `R.A.I.N. peripheral flash-nucleo`

## Validation Tip

To verify docs against your current binary quickly:

```bash
R.A.I.N. --help
R.A.I.N. <command> --help
```
