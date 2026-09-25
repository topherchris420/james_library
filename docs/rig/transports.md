# Rig Transports

Transports move short plaintext payloads between Rig nodes. All of them are
optional. R.A.I.N. behaves normally when none are installed, and no transport
can turn an incoming message into a command.

## Contract

```rust
#[async_trait]
pub trait RigTransport: Send + Sync {
    fn id(&self) -> &'static str;
    fn capabilities(&self) -> TransportDetail;       // payload limit, send support, rf_transmit
    async fn status(&self) -> CapabilityStatus;       // observe only
    async fn send(&self, action: &AuthorizedAction) -> Result<SendReceipt, TransportError>;
    async fn receive(&self) -> Result<Option<InboundMessage>, TransportError>;
}
```

- `send` requires an `AuthorizedAction` issued by the
  [action boundary](architecture.md#action-boundary) *for that transport*.
  A token for another transport returns `WrongTarget`.
- `receive` returns raw bytes. Callers pass them through `inbox::admit`, which
  can only produce `Ping`, `IdentityQuery`, or an inert `Note`.

## Available transports

| Transport | State in this build | Send / receive |
| --- | --- | --- |
| `local` | In-process loopback queue; no sockets or listeners | Yes (bounded queue, 64 messages) |
| `reticulum` | Discovery only | Explicit `Unsupported` error |
| `lxmf` | Discovery only | Explicit `Unsupported` error |
| `skybridge` | Experimental software baseband ([Skybridge](skybridge.md)) | To/from WAV files or memory; never RF |

### Reticulum discovery

Read-only checks:

- `rnsd` on `PATH`
- a config file at `/etc/reticulum/config`, `~/.config/reticulum/config` or
  `~/.reticulum/config`
- a shared instance accepting local connections on `127.0.0.1:37428` or, on
  Linux, the abstract socket `@rns/default` (connect and close, no data sent)
- with `rig doctor`, whether the Python module `RNS` is installed (via
  `importlib.util.find_spec`, without importing it)

Only a reachable shared instance reports `running`. A config without a running
instance is `configured`.

### LXMF discovery

`lxmd` on `PATH`, a config file (`/etc/lxmd/config`, `~/.config/lxmd/config`,
`~/.lxmd/config`), and in `rig doctor` the Python module `LXMF`. `lxmd` has no
local endpoint, so Rig never reports it as running.

## Inbound handling

| Payload | Result |
| --- | --- |
| `PING` | `Ping`; host code may *propose* a `PONG` reply through the boundary |
| `IDENTITY?` | `IdentityQuery`; the reply can only be the privacy-safe identity |
| Any other plaintext (for example `!shell rm -rf /`) | `Note { text }`, kept as data and never executed |
| Empty, over 4096 bytes, not UTF-8, control or bidi-override characters, unsafe source label | Rejected |

## Profiles

The `field` profile expects Reticulum, LXMF and Skybridge. When they are
missing, `rig doctor` reports `WARN` instead of `SKIP` and `rig status`
reports `DEGRADED`. Transports are never installed or started for you:

```bash
pip install rns lxmf     # optional, your choice
rnsd                     # start the shared instance yourself
```

## Next steps for Reticulum/LXMF

The adapter boundary is where a future bridge plugs in:

1. A Python sidecar owned by R.A.I.N. that links against `RNS`/`LXMF` and
   exposes a loopback-only, authenticated local socket. It must never listen
   on `0.0.0.0`.
2. `ReticulumTransport::send` forwards an `AuthorizedAction` payload to that
   socket. `receive` reads raw frames from it into `inbox::admit`.
3. LXMF destinations and identities stay in the sidecar. Only the Rig node
   identity descriptor is exchanged.
4. Mocked-socket tests in the style of `transport/loopback.rs`. No real RNS
   in CI.
