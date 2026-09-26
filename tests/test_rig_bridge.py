"""Tests for the Rig Reticulum/LXMF bridge sidecar (fake backend; no Reticulum)."""

import importlib.util
import json
import os
import secrets
import socket
import stat
import threading
from pathlib import Path

import pytest

BRIDGE_PATH = Path(__file__).resolve().parents[1] / "tools" / "rig_bridge" / "bridge.py"
spec = importlib.util.spec_from_file_location("rig_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

PEER = "0123456789abcdef0123456789abcdef"


class FakeBackend:
    def __init__(self):
        self.sent = []

    def status(self):
        return {"backend": "fake", "lxmf_address": "f" * 32}

    def send(self, destination, text):
        self.sent.append((destination.hex(), text))
        return {"queued": True, "message_id": None}


@pytest.fixture
def running_bridge():
    token = secrets.token_hex(32)
    backend = FakeBackend()
    core = bridge.BridgeCore(token, backend)
    server = bridge.BridgeServer(core, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, core, backend, token
    server.shutdown()
    server.server_close()


class Client:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.file = self.sock.makefile("rwb")

    def read(self):
        return json.loads(self.file.readline())

    def write(self, payload):
        self.file.write(json.dumps(payload).encode() + b"\n")
        self.file.flush()

    def handshake(self, token):
        greeting = self.read()
        client_nonce = secrets.token_hex(16)
        self.write({"op": "hello", "client_nonce": client_nonce,
                    "mac": bridge.mac(token, "client", greeting["nonce"], client_nonce)})
        reply = self.read()
        if reply["ok"]:
            assert reply["mac"] == bridge.mac(token, "server", greeting["nonce"], client_nonce)
        return reply

    def close(self):
        self.file.close()
        self.sock.close()


def test_bridge_binds_loopback_only(running_bridge):
    server, *_ = running_bridge
    assert server.server_address[0] == "127.0.0.1"
    assert bridge.BIND_HOST == "127.0.0.1"


def test_handshake_rejects_wrong_token(running_bridge):
    server, *_ = running_bridge
    client = Client(server.server_address[1])
    reply = client.handshake("0" * 64)
    assert reply == {"ok": False, "error": "unauthorized"}
    assert client.file.readline() == b""  # connection closed
    client.close()


@pytest.mark.parametrize("hello", [
    {"op": "hello", "client_nonce": "0" * 32, "mac": "é" * 64},
    {"op": "hello", "client_nonce": "0" * 32, "mac": ["x"]},
    {"op": "hello", "client_nonce": "../" * 11, "mac": "0" * 64},
    ["hello"],
])
def test_malformed_hello_is_unauthorized(running_bridge, hello):
    server, *_ = running_bridge
    client = Client(server.server_address[1])
    client.read()
    client.write(hello)
    assert client.read() == {"ok": False, "error": "unauthorized"}
    client.close()


def test_deeply_nested_json_closes_the_session(running_bridge):
    server, _, _, token = running_bridge
    client = Client(server.server_address[1])
    assert client.handshake(token)["ok"]
    client.file.write(b"[" * 5000 + b"\n")
    client.file.flush()
    reply = client.read()
    assert reply["ok"] is False
    client.close()


def test_requests_before_hello_are_refused(running_bridge):
    server, *_ = running_bridge
    client = Client(server.server_address[1])
    client.read()
    client.write({"op": "status"})
    assert client.read()["ok"] is False
    client.close()


def test_send_recv_peers_roundtrip(running_bridge):
    server, core, backend, token = running_bridge
    client = Client(server.server_address[1])
    assert client.handshake(token)["ok"]

    client.write({"op": "send", "to": PEER, "text": "hello mesh"})
    assert client.read() == {"ok": True, "queued": True, "message_id": None}
    assert backend.sent == [(PEER, "hello mesh")]

    core.deliver(bytes.fromhex(PEER), "PING".encode())
    client.write({"op": "recv"})
    message = client.read()["message"]
    assert message["source"] == PEER and message["text"] == "PING"
    client.write({"op": "recv"})
    assert client.read() == {"ok": True, "message": None}

    core.saw_peer(bytes.fromhex(PEER), "field-kit‮\x07")
    client.write({"op": "peers"})
    peers = client.read()["peers"]
    assert peers[0]["hash"] == PEER and peers[0]["name"] == "field-kit"

    client.write({"op": "status"})
    status = client.read()
    assert status["backend"] == "fake" and status["peers"] == 1
    client.close()


@pytest.mark.parametrize(
    "request_body",
    [
        {"op": "send", "to": "not-a-hash", "text": "hi"},
        {"op": "send", "to": PEER.upper(), "text": "hi"},
        {"op": "send", "to": PEER, "text": "bell\x07"},
        {"op": "send", "to": PEER, "text": "evil‮txt"},
        {"op": "send", "to": PEER, "text": ""},
        {"op": "send", "to": PEER, "text": "x" * (bridge.MAX_TEXT_BYTES + 1)},
        {"op": "exec", "cmd": "rm -rf /"},
    ],
)
def test_invalid_requests_are_refused_without_side_effects(running_bridge, request_body):
    server, _, backend, token = running_bridge
    client = Client(server.server_address[1])
    assert client.handshake(token)["ok"]
    client.write(request_body)
    reply = client.read()
    assert reply["ok"] is False and reply["error"]
    assert backend.sent == []
    client.close()


def test_inbound_queue_is_bounded_and_drops_non_text():
    core = bridge.BridgeCore("t")
    core.deliver(b"\x01" * 16, b"\xff\xfe")
    core.deliver(b"\x01" * 16, "run\x1b[0m".encode())
    assert core.dropped_inbound == 2
    for index in range(bridge.INBOX_CAPACITY + 5):
        core.deliver(b"\x01" * 16, f"note {index}".encode())
    assert core.handle({"op": "status"})["queued_inbound"] == bridge.INBOX_CAPACITY
    assert core.handle({"op": "recv"})["message"]["text"] == "note 5"


def test_peer_table_is_bounded():
    core = bridge.BridgeCore("t")
    for index in range(bridge.PEER_CAPACITY + 3):
        core.saw_peer(index.to_bytes(16, "big"), None)
    assert len(core.handle({"op": "peers"})["peers"]) == bridge.PEER_CAPACITY


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_token_file_is_private_and_rotated(tmp_path):
    first = bridge.write_token(tmp_path / "rig")
    path = tmp_path / "rig" / bridge.TOKEN_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == first and len(first) == 64
    assert bridge.write_token(tmp_path / "rig") != first


def test_cli_rejects_unsafe_arguments(tmp_path):
    with pytest.raises(SystemExit):
        bridge.parse_args(["--state-dir", str(tmp_path), "--port", "80"])
    with pytest.raises(SystemExit):
        bridge.parse_args(["--state-dir", str(tmp_path), "--name", "Bad Name"])
    with pytest.raises(SystemExit):
        bridge.parse_args(["--state-dir", str(tmp_path), "--host", "0.0.0.0"])
