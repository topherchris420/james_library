"""OpenClaw service wrapper and heartbeat monitor for james_library."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_PATTERNS = [
    r"traceback",
    r"fatal",
    r"segmentation fault",
    r"unhandled exception",
    r"out of memory",
    r"crash",
]


class OpenClawHeartbeat(threading.Thread):
    """Background monitor that requests service restarts for self-healing."""

    def __init__(
        self,
        restart_event: threading.Event,
        stop_event: threading.Event,
        interval_s: int = 60,
        tasks_file: Path | None = None,
        logs_dir: Path | None = None,
        patterns: list[str] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="openclaw-heartbeat")
        self.restart_event = restart_event
        self.stop_event = stop_event
        self.interval_s = interval_s
        self.tasks_file = tasks_file or Path("tasks.json")
        self.logs_dir = logs_dir or Path("logs")
        self.patterns = [re.compile(p, re.IGNORECASE) for p in (patterns or DEFAULT_PATTERNS)]
        self._offsets: dict[Path, int] = {}

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self._has_restart_task() or self._logs_show_crash_pattern():
                    self.restart_event.set()
            except Exception as exc:  # pragma: no cover - defensive service loop
                print(f"[OpenClaw] heartbeat warning: {exc}", flush=True)
            self.stop_event.wait(self.interval_s)

    def _has_restart_task(self) -> bool:
        if not self.tasks_file.exists():
            return False

        with self.tasks_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        should_restart = False
        if isinstance(payload, dict):
            command = str(payload.get("command", "")).lower().strip()
            if command in {"restart", "self-heal", "heal"}:
                should_restart = True
                payload["command"] = ""

            commands = payload.get("commands")
            if isinstance(commands, list):
                for entry in commands:
                    if isinstance(entry, dict) and str(entry.get("action", "")).lower() == "restart":
                        should_restart = True
                        entry["processed"] = True

        if should_restart:
            with self.tasks_file.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            print("[OpenClaw] restart task found in tasks.json", flush=True)

        return should_restart

    def _logs_show_crash_pattern(self) -> bool:
        if not self.logs_dir.exists() or not self.logs_dir.is_dir():
            return False

        for log_file in sorted(self.logs_dir.glob("*.log")):
            text = self._read_new_content(log_file)
            if not text:
                continue
            for pattern in self.patterns:
                if pattern.search(text):
                    print(
                        f"[OpenClaw] crash pattern '{pattern.pattern}' found in {log_file}; requesting restart",
                        flush=True,
                    )
                    return True
        return False

    def _read_new_content(self, file_path: Path) -> str:
        previous = self._offsets.get(file_path, 0)
        current_size = file_path.stat().st_size
        if current_size < previous:
            previous = 0
        with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(previous)
            data = handle.read()
            self._offsets[file_path] = handle.tell()
        return data


def pick_headless_python() -> str:
    """Prefer a non-console Python executable when available."""
    if sys.platform.startswith("win"):
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    if sys.platform == "darwin":
        candidate = Path(sys.executable).with_name("pythonw")
        if candidate.exists():
            return str(candidate)
    return sys.executable


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw background supervisor for james_library")
    parser.add_argument("--service-name", default="james-library")
    parser.add_argument("--target", default="rain_lab.py", help="Python entrypoint to supervise")
    parser.add_argument("--interval", type=int, default=60, help="Heartbeat interval in seconds")
    parser.add_argument("target_args", nargs=argparse.REMAINDER, help="Arguments passed to target")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent
    target_script = (repo_root / args.target).resolve()

    if not target_script.exists():
        raise FileNotFoundError(f"Target script not found: {target_script}")

    restart_event = threading.Event()
    stop_event = threading.Event()

    def _handle_shutdown(signum: int, _frame: object) -> None:
        print(f"[OpenClaw] received signal {signum}; shutting down", flush=True)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    heartbeat = OpenClawHeartbeat(
        restart_event=restart_event,
        stop_event=stop_event,
        interval_s=args.interval,
        tasks_file=repo_root / "tasks.json",
        logs_dir=repo_root / "logs",
    )
    heartbeat.start()

    child: subprocess.Popen[str] | None = None
    headless_python = pick_headless_python()
    target_args = list(args.target_args)
    if target_args and target_args[0] == "--":
        target_args = target_args[1:]

    while not stop_event.is_set():
        cmd = [headless_python, str(target_script), *target_args]
        print(f"[OpenClaw] launching: {' '.join(cmd)}", flush=True)
        child = subprocess.Popen(cmd, cwd=str(repo_root), env=os.environ.copy())

        while child.poll() is None and not stop_event.is_set():
            if restart_event.is_set():
                print("[OpenClaw] self-heal restart requested", flush=True)
                restart_event.clear()
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                break
            stop_event.wait(1)

        if stop_event.is_set():
            if child and child.poll() is None:
                child.terminate()
            break

        code = child.returncode if child else 1
        print(f"[OpenClaw] child exited with code {code}; restarting in 3s", flush=True)
        time.sleep(3)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
