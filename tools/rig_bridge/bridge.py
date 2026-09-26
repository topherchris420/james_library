"""R.A.I.N. Rig Reticulum/LXMF bridge (optional sidecar).

Connects the ``rain`` runtime to a Reticulum network through LXMF without
linking Reticulum into the Rust binary. The sidecar:

- listens on ``127.0.0.1`` only (there is no option to bind elsewhere);
- authenticates every connection with a mutual HMAC-SHA256 challenge keyed by
  a random token written to ``<state-dir>/bridge.token`` (mode 0600) at
  start-up, so the token itself never crosses the socket;
- sends only plaintext LXMF messages that the ``rain`` action boundary has
  already authorized, and re-validates them;
- queues inbound LXMF messages as inert text (bounded) for ``rain rig
  receive``, which passes them through the restricted inbox;
- never announces this node unless started with ``--announce``.

Protocol (one JSON object per line, UTF-8, at most 16 KiB per line)::

    server: {"bridge": "rain-rig-bridge", "version": 1, "nonce": "<hex>"}
    client: {"op": "hello", "client_nonce": "<hex>", "mac": "<hex>"}
    server: {"ok": true, "mac": "<hex>"}           # or ok=false, then close
    client: {"op": "status" | "peers" | "recv"}
    client: {"op": "send", "to": "<32 hex>", "text": "..."}
    server: {"ok": true, ...} | {"ok": false, "error": "..."}

``mac`` values are ``HMAC-SHA256(token, "rain-rig-bridge/v1/<role>|<nonce>|<client_nonce>")``
with role ``client`` or ``server``.

Requires ``rns`` and ``lxmf`` (``pip install -r tools/rig_bridge/requirements.txt``).
The protocol core has no Reticulum dependency and is unit-tested with a fake
backend.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import socketserver
import sys
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Optional, Protocol

PROTOCOL = "rain-rig-bridge"
VERSION = 1
BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 42627
MAX_LINE_BYTES = 16 * 1024
MAX_TEXT_BYTES = 4096
INBOX_CAPACITY = 256
PEER_CAPACITY = 256
MAX_PEER_NAME = 32
IDLE_TIMEOUT_SECS = 30.0
TOKEN_FILE = "bridge.token"
EXIT_MISSING_DEPENDENCY = 3

_HASH_RE = re.compile(r"^[0-9a-f]{32}$")
_NODE_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


class BridgeError(Exception):
    """A request the bridge refuses; reported to the client, never fatal."""


def mac(token: str, role: str, nonce: str, client_nonce: str) -> str:
    message = f"{PROTOCOL}/v{VERSION}/{role}|{nonce}|{client_nonce}".encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


def validate_text(text: object) -> str:
    """Same plaintext rule as the Rust boundary: UTF-8, no controls but \\n/\\t, no bidi overrides."""
    if not isinstance(text, str) or not text:
        raise BridgeError("text must be a non-empty string")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise BridgeError(f"text exceeds {MAX_TEXT_BYTES} bytes")
    for ch in text:
        code = ord(ch)
        is_control = code < 0x20 and ch not in "\n\t" or 0x7F <= code <= 0x9F
        is_bidi = 0x202A <= code <= 0x202E or 0x2066 <= code <= 0x2069
        if is_control or is_bidi:
            raise BridgeError(f"text contains disallowed character U+{code:04X}")
    return text


def validate_hash(value: object) -> bytes:
    if not isinstance(value, str) or not _HASH_RE.match(value):
        raise BridgeError("destination must be a 32-character lowercase hex LXMF address")
    return bytes.fromhex(value)


def sanitize_name(raw: object) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    cleaned = "".join(ch for ch in raw if ch.isprintable() and not 0x202A <= ord(ch) <= 0x2069).strip()
    return cleaned[:MAX_PEER_NAME] or None


class Backend(Protocol):
    def status(self) -> dict: ...

    def send(self, destination: bytes, text: str) -> dict: ...


class BridgeCore:
    """Transport-independent state: inbound queue, peer table, request handling."""

    def __init__(self, token: str, backend: Optional[Backend] = None) -> None:
        self.token = token
        self.backend = backend
        self._lock = threading.Lock()
        self._inbox: deque = deque(maxlen=INBOX_CAPACITY)
        self._peers: OrderedDict = OrderedDict()
        self.dropped_inbound = 0

    # Called from backend threads.
    def deliver(self, source: bytes, content: bytes) -> None:
        try:
            text = validate_text(content.decode("utf-8"))
        except (UnicodeDecodeError, BridgeError):
            with self._lock:
                self.dropped_inbound += 1
            return
        with self._lock:
            if len(self._inbox) == self._inbox.maxlen:
                self.dropped_inbound += 1
            self._inbox.append({"source": source.hex(), "text": text, "received_at": int(time.time())})

    def saw_peer(self, destination: bytes, name: object) -> None:
        key = destination.hex()
        with self._lock:
            self._peers.pop(key, None)
            self._peers[key] = {"hash": key, "name": sanitize_name(name), "last_seen": int(time.time())}
            while len(self._peers) > PEER_CAPACITY:
                self._peers.popitem(last=False)

    def handle(self, request: object) -> dict:
        if not isinstance(request, dict):
            raise BridgeError("request must be a JSON object")
        op = request.get("op")
        if op == "status":
            status = self.backend.status() if self.backend else {"backend": "none"}
            with self._lock:
                status.update(queued_inbound=len(self._inbox), dropped_inbound=self.dropped_inbound,
                              peers=len(self._peers))
            return status
        if op == "peers":
            with self._lock:
                return {"peers": list(reversed(self._peers.values()))}
        if op == "recv":
            with self._lock:
                return {"message": self._inbox.popleft() if self._inbox else None}
        if op == "send":
            destination = validate_hash(request.get("to"))
            text = validate_text(request.get("text"))
            if self.backend is None:
                raise BridgeError("no backend")
            return self.backend.send(destination, text)
        raise BridgeError(f"unknown op {op!r}")


def _send(wfile, payload: dict) -> None:
    wfile.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
    wfile.flush()


def _read(rfile) -> Optional[object]:
    line = rfile.readline(MAX_LINE_BYTES + 1)
    if not line:
        return None
    if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
        raise BridgeError("line too long")
    return json.loads(line)


class _Handler(socketserver.StreamRequestHandler):
    timeout = IDLE_TIMEOUT_SECS

    def handle(self) -> None:
        core: BridgeCore = self.server.core  # type: ignore[attr-defined]
        nonce = secrets.token_hex(16)
        try:
            _send(self.wfile, {"bridge": PROTOCOL, "version": VERSION, "nonce": nonce})
            hello = _read(self.rfile)
            client_nonce = hello.get("client_nonce") if isinstance(hello, dict) else None
            valid = (
                isinstance(hello, dict)
                and hello.get("op") == "hello"
                and isinstance(client_nonce, str)
                and re.fullmatch(r"[0-9a-f]{32}", client_nonce) is not None
                and isinstance(hello.get("mac"), str)
                and re.fullmatch(r"[0-9a-f]{64}", hello["mac"]) is not None
                and hmac.compare_digest(hello["mac"], mac(core.token, "client", nonce, client_nonce))
            )
            if not valid:
                _send(self.wfile, {"ok": False, "error": "unauthorized"})
                return
            _send(self.wfile, {"ok": True, "mac": mac(core.token, "server", nonce, client_nonce)})
            while True:
                try:
                    request = _read(self.rfile)
                except (BridgeError, ValueError, RecursionError) as exc:
                    _send(self.wfile, {"ok": False, "error": f"malformed request: {exc}"})
                    return
                if request is None:
                    return
                try:
                    _send(self.wfile, {"ok": True, **core.handle(request)})
                except BridgeError as exc:
                    _send(self.wfile, {"ok": False, "error": str(exc)})
        except (OSError, ValueError, RecursionError, BridgeError):
            return


class BridgeServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, core: BridgeCore, port: int) -> None:
        self.core = core
        super().__init__((BIND_HOST, port), _Handler)


def write_token(state_dir: Path) -> str:
    """Write a fresh token with mode 0600 (atomic replace) and return it."""
    state_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    path = state_dir / TOKEN_FILE
    tmp = state_dir / f".{TOKEN_FILE}.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, token.encode())
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return token


class RnsBackend:
    """LXMF over Reticulum. Imported lazily so the core stays dependency-free."""

    def __init__(self, core: BridgeCore, state_dir: Path, name: str, announce: bool,
                 rns_config: Optional[str]) -> None:
        import LXMF
        import RNS

        self.RNS, self.LXMF = RNS, LXMF
        self.reticulum = RNS.Reticulum(configdir=rns_config)
        identity_path = state_dir / "bridge_identity"
        if identity_path.is_file():
            identity = RNS.Identity.from_file(str(identity_path))
        else:
            identity = RNS.Identity()
            identity.to_file(str(identity_path))
            os.chmod(identity_path, 0o600)
        self.router = LXMF.LXMRouter(identity=identity, storagepath=str(state_dir / "lxmf"), autopeer=False)
        self.source = self.router.register_delivery_identity(identity, display_name=name)
        self.router.register_delivery_callback(self._on_message)
        RNS.Transport.register_announce_handler(_AnnounceHandler(core, LXMF))
        self.core = core
        if announce:
            self.router.announce(self.source.hash)

    def _on_message(self, message) -> None:
        content = message.content if isinstance(message.content, bytes) else str(message.content).encode()
        self.core.deliver(message.source_hash, content)

    def status(self) -> dict:
        return {
            "backend": "rns",
            "lxmf_address": self.source.hash.hex(),
            "shared_instance": bool(getattr(self.reticulum, "is_connected_to_shared_instance", False)),
            "interfaces": len(getattr(self.RNS.Transport, "interfaces", [])),
        }

    def send(self, destination: bytes, text: str) -> dict:
        RNS, LXMF = self.RNS, self.LXMF
        identity = RNS.Identity.recall(destination)
        if identity is None:
            RNS.Transport.request_path(destination)
            raise BridgeError("recipient not known yet; path requested. Retry after the peer announces")
        target = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        message = LXMF.LXMessage(target, self.source, text, title="", desired_method=LXMF.LXMessage.DIRECT)
        self.router.handle_outbound(message)
        message_id = getattr(message, "hash", None)
        return {"queued": True, "message_id": message_id.hex() if message_id else None}


class _AnnounceHandler:
    aspect_filter = "lxmf.delivery"

    def __init__(self, core: BridgeCore, lxmf_module) -> None:
        self.core = core
        self.lxmf = lxmf_module

    def received_announce(self, destination_hash, announced_identity, app_data) -> None:
        try:
            name = self.lxmf.display_name_from_app_data(app_data)
        except Exception:
            name = None
        self.core.saw_peer(destination_hash, name)


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="R.A.I.N. Rig Reticulum/LXMF bridge (binds 127.0.0.1 only)")
    parser.add_argument("--state-dir", required=True, type=Path, help="Rig state directory (token, identity)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--name", default="rain-local", help="LXMF display name (node name alphabet)")
    parser.add_argument("--announce", action="store_true", help="announce this node's LXMF address")
    parser.add_argument("--rns-config", default=None, help="Reticulum config directory (default: RNS search order)")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if not _NODE_NAME_RE.match(args.name):
        parser.error("--name must use lowercase letters, digits and inner '-' (1-32 characters)")
    return args


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    try:
        import LXMF  # noqa: F401
        import RNS  # noqa: F401
    except ImportError:
        print("rig bridge: Reticulum/LXMF not installed. Install with:\n"
              "  pip install -r tools/rig_bridge/requirements.txt", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    state_dir = args.state_dir.expanduser().resolve()
    token = write_token(state_dir)
    core = BridgeCore(token)
    core.backend = RnsBackend(core, state_dir, args.name, args.announce, args.rns_config)
    with BridgeServer(core, args.port) as server:
        print(f"rig bridge: listening on {BIND_HOST}:{args.port} · LXMF address "
              f"{core.backend.status()['lxmf_address']}", file=sys.stderr, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
