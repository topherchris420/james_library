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
| `rain rig peers [--json]` | Shareable node identity, peer transports, and LXMF peers seen through the bridge |
| `rain rig setup` | Write `[rig]` settings after confirmation. Never installs or downloads anything |
| `rain rig up [--dry-run]` | Preflight, then start the R.A.I.N. daemon on its configured (loopback) bind and, when enabled, the Reticulum/LXMF bridge |
| `rain rig send --transport lxmf --to <addr> --text …` | Send a plaintext LXMF message through the action boundary and the bridge |
| `rain rig receive [--max N] [--json]` | Drain bridge messages through the restricted inbox |
| `rain rig radio status\|encode\|decode\|listen` | Skybridge software modem and receive-only receiver input (experimental) |
| `rain rig radio transmit …` | RF transmit; only in `rig-rf-transmit` builds, with typed-callsign confirmation |

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
- **Transports**: in-process loopback; LXMF messaging over Reticulum through
  an optional R.A.I.N.-owned bridge sidecar on authenticated loopback
  (`[rig.bridge]`, off by default); Reticulum discovery. See
  [Transports](transports.md).
- **Skybridge** (experimental): plaintext frames with CRC, Hamming(7,4) FEC,
  fragmentation up to 1000 B, a software BFSK modem, WAV files and
  receive-only receiver/SDR input. RF transmit is compiled out by default.
  See [Skybridge](skybridge.md).

## What is not implemented

- Raw Reticulum packets are not bridged. Only LXMF messages are.
- Peers are listed only when they announce over LXMF through the bridge.
  There is no other live peer discovery.
- Default builds cannot key a transmitter. RF transmit needs a build with the
  `rig-rf-transmit` feature, `[rig.radio]` transmit settings, and a typed
  confirmation for every transmission. R.A.I.N. ships no radio drivers; it
  runs the commands you configure.
- Rig does not start llama.cpp, Ollama, LM Studio or rnsd, does not install
  Reticulum/LXMF, and does not download models.

## Guides

- [Getting started](getting-started.md)
- [Architecture](architecture.md)
- [llama.cpp on the Rig](llama-cpp.md)
- [Transports](transports.md)
- [Skybridge (experimental)](skybridge.md)

## Removing Rig

Delete the `[rig]` table from `config.toml`. Rig commands remain available and
read-only, and runtime behavior returns to the pre-Rig defaults.
