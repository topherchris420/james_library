"""WebSocket bridge for neutral Godot conversation events.

This relay tails a JSONL event file and broadcasts each event payload over
WebSocket to connected Godot clients.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

try:
    import websockets
except Exception:
    websockets = None


class JsonlEventTailer:
    def __init__(self, events_file: Path, poll_interval_s: float = 0.1, replay_existing: bool = False):
        self.events_file = events_file
        self.poll_interval_s = max(0.01, float(poll_interval_s))
        self.replay_existing = replay_existing

    async def run(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        self.events_file.touch(exist_ok=True)

        with self.events_file.open("r", encoding="utf-8") as handle:
            if not self.replay_existing:
                handle.seek(0, 2)

            while True:
                line = handle.readline()
                if not line:
                    await asyncio.sleep(self.poll_interval_s)
                    continue

                text = line.strip()
                if not text:
                    continue

                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue

                if isinstance(payload, dict):
                    await queue.put(payload)


class WebSocketHub:
    def __init__(self) -> None:
        self.clients: set[Any] = set()

    async def handler(self, websocket: Any) -> None:
        self.clients.add(websocket)
        try:
            async for raw in websocket:
                if isinstance(raw, str):
                    await self._handle_client_message(websocket, raw)
        except Exception:
            pass
        finally:
            self.clients.discard(websocket)

    async def _handle_client_message(self, websocket: Any, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not isinstance(payload, dict):
            return

        if payload.get("type") == "ping":
            await websocket.send(json.dumps({"type": "pong"}))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self.clients:
            return

        data = json.dumps(payload, ensure_ascii=False)
        stale: list[Any] = []
        for client in list(self.clients):
            try:
                await client.send(data)
            except Exception:
                stale.append(client)

        for client in stale:
            self.clients.discard(client)


async def _broadcast_loop(queue: asyncio.Queue[dict[str, Any]], hub: WebSocketHub) -> None:
    while True:
        payload = await queue.get()
        await hub.broadcast(payload)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tail JSONL conversation events and relay via WebSocket")
    parser.add_argument(
        "--events-file",
        type=str,
        default="meeting_archives/godot_events.jsonl",
        help="JSONL event file emitted by rain_lab_meeting_chat_version.py",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="WebSocket host")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket port")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.1,
        help="Tail polling interval in seconds",
    )
    parser.add_argument(
        "--replay-existing",
        action="store_true",
        help="Replay existing file contents on startup (default tails only new lines)",
    )
    return parser.parse_args(argv)


async def _run_bridge(args: argparse.Namespace) -> None:
    if websockets is None:
        raise RuntimeError("websockets package is required. Install with: pip install websockets")

    events_file = Path(args.events_file).expanduser()
    if not events_file.is_absolute():
        events_file = (Path.cwd() / events_file).resolve()

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    tailer = JsonlEventTailer(
        events_file=events_file,
        poll_interval_s=args.poll_interval,
        replay_existing=bool(args.replay_existing),
    )
    hub = WebSocketHub()

    print(f"[godot-bridge] events file: {events_file}")
    print(f"[godot-bridge] ws://{args.host}:{args.port}")

    async with websockets.serve(hub.handler, args.host, args.port):
        await asyncio.gather(
            tailer.run(queue),
            _broadcast_loop(queue, hub),
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        asyncio.run(_run_bridge(args))
    except KeyboardInterrupt:
        print("\n[godot-bridge] stopped")
        return 0
    except Exception as exc:
        print(f"[godot-bridge] error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
