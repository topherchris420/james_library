"""HTTP bridge server that lets the Rust ZeroClaw gateway control Python meetings.

Endpoints
---------
POST /meeting/start   {"topic": "...", "library": "...", ...}
POST /meeting/stop    {}
GET  /meeting/status  → current meeting state
GET  /meeting/events  → SSE stream of meeting events

The server is intentionally small (stdlib only — no Flask/FastAPI) so it
adds zero new dependencies.  It runs on a configurable port (default 7420)
and is designed to be started as a sidecar by ``rain_lab.py``.

Environment
-----------
RAIN_BRIDGE_HOST  – bind address (default 127.0.0.1)
RAIN_BRIDGE_PORT  – bind port    (default 7420)
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rain_bridge_protocol as proto

# ═══════════════════════════════════════════════════════════════════
# Meeting runner — runs the orchestrator in a background thread
# ═══════════════════════════════════════════════════════════════════

class MeetingRunner:
    """Manages one meeting at a time in a background thread."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._state: str = "idle"  # idle | running | stopping
        self._meeting_id: Optional[str] = None
        self._topic: Optional[str] = None
        self._turn: int = 0
        self._agents: List[str] = []
        self._event_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=2048)
        self._lock = threading.Lock()

    # ── public state queries ──────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    def status(self) -> Dict[str, Any]:
        return proto.meeting_status(
            state=self._state,
            meeting_id=self._meeting_id,
            topic=self._topic,
            turn=self._turn,
            agents=self._agents,
        )

    def drain_events(self) -> List[Dict[str, Any]]:
        """Non-blocking drain of all queued events."""
        events: List[Dict[str, Any]] = []
        while True:
            try:
                events.append(self._event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    # ── public controls ───────────────────────────────────────────

    def start(self, topic: str, **config_overrides: Any) -> Dict[str, Any]:
        with self._lock:
            if self._state != "idle":
                return {"error": f"Meeting already {self._state}"}

            self._meeting_id = uuid.uuid4().hex[:12]
            self._topic = topic
            self._turn = 0
            self._state = "running"
            self._stop_flag.clear()

        self._thread = threading.Thread(
            target=self._run,
            args=(topic, config_overrides),
            daemon=True,
        )
        self._thread.start()
        return {"meeting_id": self._meeting_id, "topic": topic}

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if self._state != "running":
                return {"error": "No meeting running"}
            self._state = "stopping"
        self._stop_flag.set()
        return {"status": "stopping", "meeting_id": self._meeting_id}

    # ── internal ──────────────────────────────────────────────────

    def _emit(self, event: Dict[str, Any]) -> None:
        try:
            self._event_queue.put_nowait(event)
        except queue.Full:
            pass  # drop oldest-style: caller can poll faster

    def _run(self, topic: str, config_overrides: Dict[str, Any]) -> None:
        """Background thread: import orchestrator, run meeting, emit events."""
        meeting_id = self._meeting_id or ""
        try:
            from rain_lab_chat.config import Config
            from rain_lab_chat.orchestrator import RainLabOrchestrator

            library = config_overrides.get("library", os.environ.get("RAIN_LIBRARY_PATH", "."))
            base_url = config_overrides.get(
                "base_url",
                os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
            )

            config = Config(
                library_path=library,
                base_url=base_url,
                temperature=float(config_overrides.get("temperature", 0.4)),
                max_turns=int(config_overrides.get("max_turns", 25)),
                max_tokens=int(config_overrides.get("max_tokens", 120)),
                verbose=bool(config_overrides.get("verbose", False)),
                emit_visual_events=True,
            )

            orchestrator = RainLabOrchestrator(config)
            self._agents = [a.name for a in orchestrator.team]

            self._emit(proto.meeting_started(
                topic=topic,
                agents=self._agents,
                paper_count=0,  # updated after context load
                meeting_id=meeting_id,
            ))

            # Patch the orchestrator to emit bridge events
            original_run = orchestrator.run_meeting

            runner_self = self  # capture for closure

            def patched_run_meeting(topic: str) -> None:
                """Wraps run_meeting to inject bridge event emission."""
                # We can't easily intercept each turn without modifying the
                # orchestrator class.  Instead, we monkey-patch
                # _emit_visual_event so every visual event also becomes a
                # bridge event.
                original_emit = orchestrator._emit_visual_event

                def bridge_emit(payload: Dict[str, Any]) -> None:
                    original_emit(payload)  # keep Godot events working
                    # Forward to bridge event queue
                    bridge_event = dict(payload)
                    bridge_event.setdefault("meeting_id", meeting_id)
                    bridge_event.setdefault("timestamp", proto._ts())
                    runner_self._emit(bridge_event)

                    # Track turn count
                    if payload.get("type") == "agent_utterance":
                        runner_self._turn += 1

                orchestrator._emit_visual_event = bridge_emit

                # Check stop flag periodically by patching the spinner
                original_spinner = orchestrator._animate_spinner

                def interruptible_spinner(label: str, duration: float = 0.9, color: str = "\033[96m") -> None:
                    if runner_self._stop_flag.is_set():
                        raise KeyboardInterrupt("Bridge stop requested")
                    original_spinner(label, duration, color)

                orchestrator._animate_spinner = interruptible_spinner

                original_run(topic)

            try:
                patched_run_meeting(topic)
            except KeyboardInterrupt:
                pass  # graceful stop

            self._emit(proto.meeting_ended(
                meeting_id=meeting_id,
                topic=topic,
                turn_count=self._turn,
            ))

        except Exception as exc:
            self._emit(proto.meeting_error(meeting_id=meeting_id, message=str(exc)))

        finally:
            with self._lock:
                self._state = "idle"
                self._meeting_id = None
                self._topic = None
                self._turn = 0
                self._agents = []


# ═══════════════════════════════════════════════════════════════════
# HTTP request handler
# ═══════════════════════════════════════════════════════════════════

_runner = MeetingRunner()


class BridgeHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for the bridge API."""

    # Suppress default stderr logging
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    # ── routing ───────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/meeting/status":
            self._json_response(200, _runner.status())
        elif self.path == "/meeting/events":
            self._sse_stream()
        elif self.path == "/health":
            self._json_response(200, {"status": "ok"})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        body = self._read_body()
        if self.path == "/meeting/start":
            topic = body.get("topic", "").strip()
            if not topic:
                self._json_response(400, {"error": "topic is required"})
                return
            config_overrides = {k: v for k, v in body.items() if k != "topic"}
            result = _runner.start(topic, **config_overrides)
            code = 200 if "meeting_id" in result else 409
            self._json_response(code, result)
        elif self.path == "/meeting/stop":
            result = _runner.stop()
            code = 200 if "status" in result else 409
            self._json_response(code, result)
        else:
            self._json_response(404, {"error": "not found"})

    # ── helpers ───────────────────────────────────────────────────

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}

    def _json_response(self, code: int, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _sse_stream(self) -> None:
        """Server-Sent Events stream: long-lived connection that pushes meeting events."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            while True:
                events = _runner.drain_events()
                for ev in events:
                    line = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()

                if not events:
                    # Send keepalive comment every 15s
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()

                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # client disconnected


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="R.A.I.N. Lab bridge server (Rust↔Python)")
    parser.add_argument(
        "--host",
        default=os.environ.get("RAIN_BRIDGE_HOST", "127.0.0.1"),
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("RAIN_BRIDGE_PORT", "7420")),
        help="Bind port (default: 7420)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    server = HTTPServer((args.host, args.port), BridgeHandler)
    print(f"[rain-bridge] http://{args.host}:{args.port}")
    print(f"[rain-bridge] POST /meeting/start  {{\"topic\": \"...\"}}")
    print(f"[rain-bridge] POST /meeting/stop")
    print(f"[rain-bridge] GET  /meeting/status")
    print(f"[rain-bridge] GET  /meeting/events  (SSE)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[rain-bridge] stopped")
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
