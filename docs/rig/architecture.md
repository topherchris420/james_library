# R.A.I.N. Rig Architecture

Rig is a thin layer inside the Rust runtime (`src/rig/`). It observes and
coordinates. It does not replace the research meeting, and it keeps provider-,
radio- and hardware-specific logic out of it.

```text
R.A.I.N. Lab  (python rain_lab.py — James · Jasmine · Luca · Elena)
      │   unchanged; Rig only reads its files and documented env contract
      ▼
Decision / authorization boundary
  Laya → Jev → deterministic validation   (Python judgment layer, existing)
  Rig action boundary: proposal → policy → validation → human → token
      │
      ▼
Rig capability bus   (src/rig/capability.rs + status/doctor)
      │                     │                        │
      ▼                     ▼                        ▼
inference providers    research registry      transports / hardware
(src/providers/*)      (papers, personas)     loopback · Reticulum · LXMF
llama.cpp · Ollama                             Skybridge (experimental)
LM Studio · others                             RF transmit: disabled
```

## Module map

| Module | Responsibility |
| --- | --- |
| `config/schema/rig.rs` + `rig_profiles/*.toml` | `[rig]` settings, built-in profiles, privacy resolution |
| `providers/locality.rs` | Endpoint locality (loopback / LAN / remote), default local URLs, local-only enforcement |
| `rig/capability.rs` | Static capability registry and observed status types |
| `rig/context.rs` | Discovery inputs: config, environment snapshot, library root, probe endpoints |
| `rig/probe.rs` | Bounded HTTP/TCP probes restricted to local endpoints |
| `rig/inference.rs` | llama.cpp, Ollama, LM Studio and configured-provider discovery |
| `rig/research.rs` | Personas, papers corpus, meeting endpoint, Laya/Jev state |
| `rig/system.rs` | Hardware, storage, gateway, LAN peering, listeners, privacy assessment |
| `rig/identity.rs` | Privacy-safe node identity descriptor |
| `rig/status.rs`, `rig/doctor.rs`, `rig/render.rs` | Snapshot, readiness, checks, human output |
| `rig/action.rs` | Action boundary and disposition log |
| `rig/inbox.rs` | Restricted inbound message layer |
| `rig/transport/` | `RigTransport` trait, loopback, Reticulum/LXMF adapters, discovery |
| `rig/skybridge/` | Experimental frame codec, modem, WAV, disabled RF backend |
| `rig/setup.rs`, `rig/up.rs`, `rig/cli.rs` | `rain rig` commands |

## Capability states

A capability's descriptor (id, category, optional, experimental) is separate
from its observed state:

| State | Meaning |
| --- | --- |
| `running` | A live probe of a service succeeded just now |
| `available` | Present and usable without a separate service (compiled-in component, persona file, corpus) |
| `configured` | Selected in configuration but not active or reachable now |
| `degraded` | Active but failing a health check (auth rejected, model loading, bad response) |
| `disabled` | Turned off by configuration or policy |
| `unavailable` | Missing or not reachable |

Discovery never infers `running` from an installed binary. LXMF can never
report `running`, because `lxmd` exposes no local endpoint to probe.

## Discovery safety

- Probes run only against loopback or private-network URLs. Remote endpoints
  are reported as "not probed" and never contacted.
- The probe client bypasses proxies (local traffic must not leave the box),
  follows no redirects, uses 0.8 s connect / 2.5 s request timeouts, and caps
  response bodies at 1 MiB.
- Discovery reads config and files. It never writes, starts, installs, or
  reconfigures anything. `rig doctor` checks writability with a temporary file
  and creates no directories. Like every `rain` command, the first run creates
  a default `config.toml` if none exists.

## Privacy enforcement

`[rig] privacy` resolves as: explicit setting, then the profile default, then
`hybrid`. When the result is `local`, `ProviderRuntimeOptions::local_inference_only`
is set everywhere the runtime builds providers from config: agent, gateway,
channels, delegate/swarm tools, and the model-routing probe. The factory
refuses non-local targets with a typed `LocalInferenceViolation`. Fallback
providers and model routes propagate that error instead of skipping the
entry, so there is no silent hosted fallback. The violation is non-retryable.

`status` and `doctor` also assess the Python meeting's endpoint and model
(`RAIN_LLM_BASE_URL`, `RAIN_LLM_MODEL`) and Jev. Those are advisory: the
meeting is a separate process with its own configuration.

## Action boundary

```text
model / operator / system proposes
        ↓
policy checks        RF transmit → always rejected
                     model-originated config write → rejected
                     transport must be able to send in this build
        ↓
deterministic        payload size, UTF-8 plaintext (no control or
validation           bidirectional-override characters), proposal id
        ↓
human authorization  required when a model or host code proposes an
                     external action; approval is bound to the proposal id
        ↓
disposition record   JSONL (payload digest + length, never the payload);
                     if it cannot be written, the action is rejected
        ↓
AuthorizedAction     sealed token; only the boundary can construct it
        ↓
transport adapter    send() requires the token for that transport
```

Model assessments are recorded but never read by a check, so model judgment
cannot override a failed deterministic check. A human approval is only
consulted after every check passes.

## Inbound messages

Transports return raw messages. `inbox::admit` can only produce `Ping`,
`IdentityQuery`, or `Note { text }`, and a note is inert data. There is no
variant for shell commands, tool calls, agent prompts or configuration, and
the module depends on nothing that could execute them. Oversized, binary,
control-character and bidi-override payloads are rejected.

## Node identity

```json
{ "node": "rain-local", "version": 1, "capabilities": ["research", "local-inference"] }
```

Tags come from a fixed enum (`research`, `local-inference`, `reticulum`,
`skybridge`). Node names are restricted to a DNS-label alphabet. The
descriptor cannot carry prompts, papers, credentials, endpoints, model names,
paths or serial numbers.

## Network safety

Rig opens no listeners. The only R.A.I.N. listener it reports is the gateway
(`127.0.0.1` by default). A non-loopback bind appears as `EXTERNAL BIND` in
status and doctor. It BLOCKS the node unless `[gateway] allow_public_bind` or
a tunnel explicitly allows it, and the gateway itself still enforces that rule.
