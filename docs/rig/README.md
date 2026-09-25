# R.A.I.N. Rig

**A research lab you can run on a machine you own.**

R.A.I.N. Rig is an optional layer over the existing local-first `rain` runtime.
It turns a machine into a self-contained research node. It discovers local
inference, the research library, the decision layer, transports and listeners.
It reports what it finds truthfully and coordinates only what R.A.I.N. owns.

Rig is opt-in and additive. The default R.A.I.N. Lab is unchanged:

```bash
python rain_lab.py
```

Nothing in Rig is a prerequisite for that path. With no `[rig]` section in
`config.toml`, runtime behavior is exactly as before.

## Names

| Name | What it is |
| --- | --- |
| **R.A.I.N. Lab** | The product experience: the James / Jasmine / Luca / Elena research meeting launched by `python rain_lab.py`. |
| **R.A.I.N. Rig** | This optional node layer (`rain rig …`). It observes and coordinates. It never replaces the meeting. |
| **James Library** | The repository and its Python workflow collection (`james_library/`, papers, personas). |
| **rain runtime** | The Rust `rain` binary (`src/`): providers, channels, tools, security, gateway. Rig lives here as `src/rig/`. |

## Commands

| Command | Purpose |
| --- | --- |
| `rain rig status [--json]` | Node snapshot: inference, research, decision, transports, hardware, network, readiness |
| `rain rig doctor [--json]` | PASS / WARN / FAIL / SKIP checks; exits non-zero when anything FAILs |
| `rain rig models [--json]` | Models discovered on llama.cpp, Ollama, LM Studio and the meeting endpoint |
| `rain rig capabilities [--json]` | Every registered capability and its current state |
| `rain rig peers [--json]` | Shareable node identity and peer transports |
| `rain rig setup` | Write `[rig]` settings after confirmation. Never installs or downloads anything |
| `rain rig up [--dry-run]` | Preflight, then start the R.A.I.N. daemon on its configured (loopback) bind |
| `rain rig radio status\|encode\|decode` | Skybridge software modem (experimental; never transmits RF) |

`rain rig --library <path> …` points discovery at a specific James Library
checkout. By default Rig looks in the current directory, its ancestors, and the
ancestors of the `rain` binary.

## What is implemented

- **Capability registry** with states `running`, `available`, `configured`,
  `degraded`, `disabled`, `unavailable`. A binary on `PATH` never counts as
  "running".
- **Local inference discovery** reuses the existing `llamacpp` / `llama.cpp`,
  `ollama` and `lmstudio` providers. See [llama.cpp on the Rig](llama-cpp.md).
- **Profiles** `local`, `node`, `field` stored as human-readable TOML.
- **Privacy modes** `local`, `hybrid`, `hosted`. `local` is enforced by the
  provider factory and fails closed.
- **Network safety**: Rig adds no listeners. External binds are reported
  prominently.
- **Action boundary**: every Rig action is proposed, then policy-checked,
  deterministically validated, human-authorized when required, and recorded.
- **Transports**: in-process loopback, plus Reticulum and LXMF adapters that
  are discovery-only. See [Transports](transports.md).
- **Skybridge** (experimental): plaintext frame codec, CRC, a software BFSK
  modem and WAV files. RF transmit is disabled. See [Skybridge](skybridge.md).

## What is not implemented

- No Reticulum/LXMF message bridge. Those adapters only report discovery state,
  and `send`/`receive` return an explicit "unsupported" error.
- No live peer discovery. `rig peers` shows your identity and transport states.
- No radio or SDR hardware backend. Nothing can key a transmitter.
- Rig does not start llama.cpp, Ollama, LM Studio or rnsd, and it does not
  download models.
- The Python meeting (`rain_lab.py`) is not governed by the runtime's provider
  enforcement. `rig status` and `rig doctor` report its endpoint and model
  honestly, but enforcement there is advisory in this release.

## Guides

- [Getting started](getting-started.md)
- [Architecture](architecture.md)
- [llama.cpp on the Rig](llama-cpp.md)
- [Transports](transports.md)
- [Skybridge (experimental)](skybridge.md)

## Removing Rig

Delete the `[rig]` table from `config.toml`. Rig commands remain available and
read-only, and runtime behavior returns to the pre-Rig defaults.
