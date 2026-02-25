"""Unified launcher for R.A.I.N. Lab meeting modes.

Usage examples:
  python rain_lab.py --mode first-run
  python rain_lab.py --mode rlm --topic "Guarino paper"
  python rain_lab.py --mode chat --topic "Guarino paper" -- --recursive-depth 2
  python rain_lab.py --mode godot --topic "Guarino paper"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ANSI_RESET = "\033[0m"
ANSI_CYAN = "\033[96m"
ANSI_BLUE = "\033[94m"
ANSI_MAGENTA = "\033[95m"
ANSI_GREEN = "\033[92m"
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_DIM = "\033[90m"

BANNER_LINES = [
    "==============================================================",
    "  R.A.I.N. LAB - Recursive Architecture of Intelligent Nexus  ",
    "==============================================================",
    "                 V E R S 3 D Y N A M I C S                   ",
]


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _print_banner() -> None:
    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_YELLOW]
    for line, color in zip(BANNER_LINES, colors):
        safe_line = _console_safe(line)
        print(f"{ANSI_DIM} {safe_line}{ANSI_RESET}", flush=True)
        print(f"{color}{safe_line}{ANSI_RESET}", flush=True)


def _spinner(message: str, duration_s: float = 1.25) -> None:
    safe_message = _console_safe(message)
    if not sys.stdout.isatty():
        print(f"{ANSI_CYAN}{safe_message}...{ANSI_RESET}", flush=True)
        return

    frames = ["[   ]", "[=  ]", "[== ]", "[===]", "[ ==]", "[  =]"]
    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_GREEN, ANSI_YELLOW]
    end_time = time.time() + max(0.2, duration_s)
    i = 0
    while time.time() < end_time:
        frame = frames[i % len(frames)]
        color = colors[i % len(colors)]
        pulse = "." * ((i % 3) + 1)
        print(f"\r{color}{frame} {safe_message} {pulse}{ANSI_RESET}   ", end="", flush=True)
        i += 1
        time.sleep(0.09)
    print(f"\r{ANSI_GREEN}OK {safe_message}{ANSI_RESET}   ")


def _split_passthrough_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1 :]
    return argv, []


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    known, passthrough = _split_passthrough_args(argv)
    parser = argparse.ArgumentParser(
        description="Unified launcher for rain_lab_meeting modes"
    )
    parser.add_argument(
        "--mode",
        choices=["rlm", "chat", "godot", "hello-os", "compile", "preflight", "backup", "first-run"],
        default="chat",
        help="Which engine to run: rlm (tool-exec), chat (runtime), godot (chat runtime + visual events), hello-os (single executable), compile (build knowledge artifacts), preflight (environment checks), backup (local snapshot), or first-run (guided onboarding)",
    )
    parser.add_argument("--topic", type=str, default=None, help="Meeting topic")
    parser.add_argument(
        "--library",
        type=str,
        default=None,
        help="Library path (used directly by chat mode; exported as JAMES_LIBRARY_PATH for rlm mode)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Turn limit alias: maps to --turns (rlm) or --max-turns (chat)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Chat mode only: LM request timeout in seconds (maps to --timeout)",
    )
    parser.add_argument(
        "--recursive-depth",
        type=int,
        default=None,
        help="Chat mode only: internal self-reflection passes (maps to --recursive-depth)",
    )
    parser.add_argument(
        "--no-recursive-intellect",
        action="store_true",
        help="Chat mode only: disable recursive self-reflection",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Chat mode only: path to runtime TOML config (maps to --config).",
    )
    parser.add_argument(
        "--godot-events-log",
        type=str,
        default=os.environ.get("RAIN_VISUAL_EVENTS_LOG", "meeting_archives/godot_events.jsonl"),
        help="Godot mode: JSONL events file used by the bridge and emitter.",
    )
    parser.add_argument(
        "--godot-tts-audio-dir",
        type=str,
        default=os.environ.get("RAIN_TTS_AUDIO_DIR", "meeting_archives/tts_audio"),
        help="Godot mode: per-turn TTS export directory.",
    )
    parser.add_argument(
        "--godot-ws-host",
        type=str,
        default="127.0.0.1",
        help="Godot mode: bridge WebSocket host.",
    )
    parser.add_argument(
        "--godot-ws-port",
        type=int,
        default=8765,
        help="Godot mode: bridge WebSocket port.",
    )
    parser.add_argument(
        "--godot-bridge-poll-interval",
        type=float,
        default=0.1,
        help="Godot mode: JSONL tail polling interval in seconds.",
    )
    parser.add_argument(
        "--godot-replay-existing",
        action="store_true",
        help="Godot mode: bridge replays existing event log contents on startup.",
    )
    parser.add_argument(
        "--no-godot-bridge",
        action="store_true",
        help="Godot mode: do not auto-launch godot_event_bridge.py.",
    )
    args = parser.parse_args(known)
    return args, passthrough


def build_command(args: argparse.Namespace, passthrough: list[str], repo_root: Path) -> list[str]:

    if args.mode == "first-run":
        target = repo_root / "rain_first_run.py"
        cmd = [sys.executable, str(target)]
        if args.topic:
            cmd.extend(["--topic", args.topic])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "compile":
        target = repo_root / "library_compiler.py"
        cmd = [sys.executable, str(target)]
        lib_path = args.library or str(repo_root)
        cmd.extend(["--library", lib_path])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "preflight":
        target = repo_root / "rain_preflight_check.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough)
        return cmd

    if args.mode == "backup":
        target = repo_root / "rain_lab_backup.py"
        cmd = [sys.executable, str(target)]
        if args.library:
            cmd.extend(["--library", args.library])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "hello-os":
        target = repo_root / "hello_os_executable.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough if passthrough else ["inspect"])
        return cmd

    if args.mode == "rlm":
        target = repo_root / "rain_lab_meeting.py"
        cmd = [sys.executable, str(target)]
        if args.topic:
            cmd.extend(["--topic", args.topic])
        if args.turns is not None:
            cmd.extend(["--turns", str(args.turns)])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "godot":
        target = repo_root / "rain_lab_meeting_chat_version.py"
        if not target.exists():
            raise FileNotFoundError("Godot mode requires rain_lab_meeting_chat_version.py")
        cmd = [
            sys.executable,
            str(target),
            "--emit-visual-events",
            "--visual-events-log",
            args.godot_events_log,
            "--tts-audio-dir",
            args.godot_tts_audio_dir,
        ]
        if args.topic:
            cmd.extend(["--topic", args.topic])
        if args.library:
            cmd.extend(["--library", args.library])
        if args.turns is not None:
            cmd.extend(["--max-turns", str(args.turns)])
        if args.timeout is not None:
            cmd.extend(["--timeout", str(args.timeout)])
        if args.no_recursive_intellect:
            cmd.append("--no-recursive-intellect")
        elif args.recursive_depth is not None:
            cmd.extend(["--recursive-depth", str(args.recursive_depth)])
        cmd.extend(passthrough)
        return cmd

    target = repo_root / "rain_lab_runtime.py"
    if not target.exists():
        raise FileNotFoundError("Chat mode requires rain_lab_runtime.py")
    cmd = [sys.executable, str(target)]
    if args.topic:
        cmd.extend(["--topic", args.topic])
    cmd.extend(["--mode", args.mode])
    if args.library:
        cmd.extend(["--library", args.library])
    if args.turns is not None:
        cmd.extend(["--max-turns", str(args.turns)])
    if args.timeout is not None:
        cmd.extend(["--timeout", str(args.timeout)])
    if args.no_recursive_intellect:
        cmd.append("--no-recursive-intellect")
    elif args.recursive_depth is not None:
        cmd.extend(["--recursive-depth", str(args.recursive_depth)])
    if args.config:
        cmd.extend(["--config", args.config])
    cmd.extend(passthrough)
    return cmd


def build_godot_bridge_command(args: argparse.Namespace, repo_root: Path) -> list[str]:
    target = repo_root / "godot_event_bridge.py"
    if not target.exists():
        raise FileNotFoundError("Godot mode bridge requires godot_event_bridge.py")
    cmd = [
        sys.executable,
        str(target),
        "--events-file",
        args.godot_events_log,
        "--host",
        args.godot_ws_host,
        "--port",
        str(args.godot_ws_port),
        "--poll-interval",
        str(args.godot_bridge_poll_interval),
    ]
    if args.godot_replay_existing:
        cmd.append("--replay-existing")
    return cmd


async def run_rain_lab(
    query: str,
    mode: str = "chat",
    agent: str | None = None,
    recursive_depth: int = 1,
) -> str:
    """Async integration entrypoint used by non-CLI gateways (e.g., Telegram).

    This launcher keeps backward compatibility with the existing CLI while
    providing an importable symbol for adapters.

    By default it tries to import a richer runtime implementation from
    ``rain_lab_runtime.py``. If that module is absent, an explicit error is
    raised so integrators know where to wire their project-specific logic.
    """
    try:
        from rain_lab_runtime import run_rain_lab as runtime_run_rain_lab
    except ImportError as exc:
        raise RuntimeError(
            "run_rain_lab is not wired yet. Add rain_lab_runtime.py with an "
            "async run_rain_lab(...) implementation, or replace rain_lab.run_rain_lab "
            "with your project's existing async entrypoint."
        ) from exc

    return await runtime_run_rain_lab(
        query=query,
        mode=mode,
        agent=agent,
        recursive_depth=recursive_depth,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    args, passthrough = parse_args(argv)
    repo_root = Path(__file__).resolve().parent

    _print_banner()

    # Interactive prompt if topic is missing (and not asking for help)
    if args.mode not in {"hello-os", "compile", "preflight", "backup", "first-run"} and not args.topic and "-h" not in passthrough and "--help" not in passthrough:
        print(f"\n{ANSI_YELLOW}Research Topic needed.{ANSI_RESET}")
        print(f"{ANSI_DIM}Example: 'Guarino paper', 'Quantum Resonance', 'The nature of time'{ANSI_RESET}")
        try:
            # Show cursor and prompt
            topic_input = input(f"{ANSI_GREEN}Enter topic: {ANSI_RESET}").strip()
            if topic_input:
                args.topic = topic_input
            else:
                args.topic = "Open research discussion"
        except KeyboardInterrupt:
            print(f"\n{ANSI_RED}Aborted.{ANSI_RESET}")
            return 1

    cmd = build_command(args, passthrough, repo_root)
    bridge_cmd: list[str] | None = None
    if args.mode == "godot" and not args.no_godot_bridge:
        bridge_cmd = build_godot_bridge_command(args, repo_root)

    child_env = None
    if args.library:
        child_env = dict(os.environ)
        child_env["JAMES_LIBRARY_PATH"] = args.library

    bridge_proc: subprocess.Popen[bytes] | None = None
    if bridge_cmd is not None:
        _spinner("Starting Godot event bridge")
        print(f"{ANSI_CYAN}Launching bridge: {' '.join(bridge_cmd)}{ANSI_RESET}", flush=True)
        bridge_proc = subprocess.Popen(bridge_cmd, env=child_env)
        time.sleep(0.25)

    _spinner("Booting VERS3DYNAMICS R.A.I.N. Lab launcher")
    print(f"{ANSI_CYAN}Launching mode={args.mode}: {' '.join(cmd)}{ANSI_RESET}", flush=True)
    try:
        result = subprocess.run(cmd, env=child_env)
        return int(result.returncode)
    finally:
        if bridge_proc is not None and bridge_proc.poll() is None:
            bridge_proc.terminate()
            try:
                bridge_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                bridge_proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
