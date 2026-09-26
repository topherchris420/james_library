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
- Addressed transports (LXMF) carry the destination in the proposal. The
  boundary requires a 32-character lowercase hex address for `lxmf` and
  refuses a destination for every other transport. Only a validated address
  appears in the disposition record.

## Available transports

| Transport | State in this build | Send / receive |
| --- | --- | --- |
| `local` | In-process loopback queue; no sockets or listeners | Yes (bounded queue, 64 messages) |
| `reticulum` | Discovery (shared instance, install facts) | Explicit `Unsupported` error: raw packets are not bridged; use `lxmf` |
| `lxmf` | Messaging through the [R.A.I.N. bridge](#reticulumlxmf-bridge) when `[rig.bridge]` is enabled; discovery otherwise | `rain rig send --transport lxmf` / `rain rig receive` |
| `skybridge` | Experimental software baseband ([Skybridge](skybridge.md)) | WAV files, memory, receive-only receiver command; RF only in `rig-rf-transmit` builds |

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
local endpoint, so install facts alone never report LXMF as `running`. Only an
authenticated session with the R.A.I.N. bridge does.

## Reticulum/LXMF bridge

Reticulum is never linked into `rain`. The optional sidecar
[`tools/rig_bridge/bridge.py`](../../tools/rig_bridge/README.md) owns RNS and
LXMF and talks to `rain` over line-delimited JSON:

- It binds `127.0.0.1` only; there is no host setting.
- Both ends authenticate with a mutual HMAC-SHA256 challenge keyed by a random
  token that the bridge rewrites at every start in `<workspace>/rig/bridge.token`
  (mode 0600). The token never crosses the socket. `rain` refuses a token
  file that other users can read, and it refuses a server that cannot prove
  the token (for example, a process squatting the port).
- `rain` treats every reply as untrusted: addresses are re-validated, peer
  names are stripped of control and bidi characters and capped, lines are
  bounded to 16 KiB, and requests time out.
- Outbound: only boundary-authorized plaintext (at most 4096 B), which the
  bridge validates again. Inbound: queued as inert text (256 messages at
  most) until `rain rig receive` passes each one through `inbox::admit`.
- The LXMF address is announced only with `announce = true`. Senders that do
  not know a recipient yet get "path requested, retry".

```toml
[rig.bridge]
enabled = true     # default false
port = 42627       # loopback port
announce = false   # announce this node's LXMF address
```

```bash
pip install -r tools/rig_bridge/requirements.txt   # rns, lxmf (optional)
rain rig up                                        # starts the bridge, then the daemon
rain rig peers                                     # LXMF peers seen via announces
rain rig send --transport lxmf --to <32-hex address> --text "PING"
rain rig receive                                   # PING / IDENTITY? / inert notes
```

`rig up` starts the bridge with the library's `.venv` Python (or `python3`),
passes only argv (no shell), and waits for an authenticated session before
it starts the daemon. When Reticulum/LXMF are missing, `rig up` stops before
starting anything. The bridge stops with `rig up`. If it exits early, `rig up`
logs it and keeps the daemon running without restarting the bridge.

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
reports `DEGRADED`. Third-party software is never installed for you, and
`rnsd` is never started for you:

```bash
pip install -r tools/rig_bridge/requirements.txt   # optional, your choice
rnsd                                               # optional shared instance
```

## Tests

Bridge tests never need Reticulum. The Rust client and adapters run against
an in-process fake bridge that speaks the protocol (handshake, impostor,
world-readable token, untrusted replies). The Python protocol core runs
against a fake backend over a real loopback socket
(`tests/test_rig_bridge.py`).
