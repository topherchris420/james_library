"""Visual event server — streams theme-agnostic events to Godot over WebSocket."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .config import Config


class VisualEventServer:
    """Streams theme-agnostic conversation events to Godot clients over WebSocket.

    Runs a websockets server in a background daemon thread.  The public
    ``emit()`` method is safe to call from any thread.
    """

    def __init__(self, config: Config):
        self.enabled = bool(config.emit_visual_events)
        self._host: str = str(getattr(config, "visual_events_host", "127.0.0.1"))
        self._port: int = int(getattr(config, "visual_events_port", 8765))

        self._log_path: Optional[Path] = None
        if getattr(config, "log_visual_events", False):
            self._log_path = self._resolve_path(config.library_path, config.visual_events_log)
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"\u26a0\ufe0f  Visual event log unavailable: {e}")
                self._log_path = None

        self._loop = None
        self._queue = None
        self._thread: Optional[threading.Thread] = None
        self._clients: set = set()

        if self.enabled:
            self._start_server()

    @staticmethod
    def _resolve_path(library_path: str, configured_path: str) -> Path:
        raw = Path(configured_path).expanduser()
        if raw.is_absolute():
            return raw
        return Path(library_path) / raw

    def emit(self, payload: Dict):
        if not self.enabled:
            return

        event = dict(payload)
        event.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")

        if self._log_path is not None:
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"\u26a0\ufe0f  Visual event log write failed: {e}")

        if self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def shutdown(self):
        """Stop the background server gracefully."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _start_server(self):
        try:
            import asyncio as _asyncio
            import websockets as _ws
        except ImportError:
            print("\u26a0\ufe0f  websockets package not installed \u2014 visual event server disabled")
            self.enabled = False
            return

        ready = threading.Event()

        def _run():
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            self._loop = loop
            self._queue = _asyncio.Queue()

            async def _handler(websocket):
                self._clients.add(websocket)
                try:
                    async for raw in websocket:
                        if isinstance(raw, str):
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(msg, dict) and msg.get("type") == "ping":
                                await websocket.send(json.dumps({"type": "pong"}))
                except Exception:
                    pass
                finally:
                    self._clients.discard(websocket)

            async def _broadcaster():
                while True:
                    event = await self._queue.get()
                    if not self._clients:
                        continue
                    data = json.dumps(event, ensure_ascii=False)
                    stale = []
                    for client in list(self._clients):
                        try:
                            await client.send(data)
                        except Exception:
                            stale.append(client)
                    for client in stale:
                        self._clients.discard(client)

            async def _serve():
                async with _ws.serve(_handler, self._host, self._port):
                    print(f"[visual-events] ws://{self._host}:{self._port}")
                    ready.set()
                    await _broadcaster()

            loop.run_until_complete(_serve())

        self._thread = threading.Thread(target=_run, daemon=True, name="visual-event-server")
        self._thread.start()
        ready.wait(timeout=5)
