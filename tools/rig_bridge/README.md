# R.A.I.N. Rig Reticulum/LXMF bridge

Optional sidecar that lets `rain rig send`/`rain rig receive` exchange
plaintext LXMF messages over a Reticulum network. Reticulum is never linked
into the `rain` binary; this process owns it.

## Safety properties

- Binds `127.0.0.1` only. There is no host option.
- Every connection is authenticated with a mutual HMAC-SHA256 challenge keyed
  by a random token that the bridge writes to `<workspace>/rig/bridge.token`
  (mode 0600) at every start. The token never crosses the socket, and `rain`
  refuses a token file that other users can read.
- Outbound: only messages already authorized by the `rain` action boundary
  (plaintext, size, destination checks, recorded disposition). The bridge
  validates them again.
- Inbound: queued as inert text (at most 256 messages, 4096 bytes each).
  `rain rig receive` passes each one through the restricted inbox, which can
  only yield `PING`, `IDENTITY?` or a note. Nothing is executed.
- The node's LXMF address is announced only when `announce = true`.
- The LXMF identity is stored in `<workspace>/rig/bridge_identity` (mode 0600).

## Setup

```bash
pip install -r tools/rig_bridge/requirements.txt   # rns, lxmf (optional deps)
```

In `config.toml`:

```toml
[rig.bridge]
enabled = true      # default false
port = 42627        # loopback port, default 42627
announce = false    # default false
```

`rain rig up` starts the bridge with the library's `.venv` Python (or
`python3`), waits for an authenticated session, then starts the daemon.
Stopping `rig up` stops the bridge. If the bridge exits early, `rig up`
reports it and does not restart it in a loop.

The bridge uses the normal Reticulum configuration (`~/.reticulum/config`).
If `rnsd` is running, the bridge connects to that shared instance.
Otherwise it starts its own instance with the interfaces in that
configuration.

## Use

```bash
rain rig status                  # LXMF: running · address <hash> · peers
rain rig peers                   # LXMF peers seen via announces
rain rig send --transport lxmf --to <32-hex address> --text "PING"
rain rig receive                 # drain queued messages through the inbox
```

If the recipient is not yet known, the send fails with "path requested".
Retry once the peer has answered the path request or announced.

## Manual start

```bash
python tools/rig_bridge/bridge.py --state-dir ~/.R.A.I.N./workspace/rig --port 42627
```

`--state-dir` must be the Rig state directory (`<workspace>/rig`) so that
`rain` finds the token.
