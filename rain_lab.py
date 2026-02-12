"""Unified launcher for R.A.I.N. Lab meeting modes.

Usage examples:
  python rain_lab.py --mode rlm --topic "Guarino paper"
  python rain_lab.py --mode chat --topic "Guarino paper" -- --recursive-depth 2
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

BANNER_LINES = [
    "██╗   ██╗███████╗██████╗ ███████╗██████╗ ██████╗ ██╗   ██╗███╗   ██╗ █████╗ ███╗   ███╗██╗ ██████╗███████╗",
    "██║   ██║██╔════╝██╔══██╗██╔════╝██╔══██╗██╔══██╗╚██╗ ██╔╝████╗  ██║██╔══██╗████╗ ████║██║██╔════╝██╔════╝",
    "██║   ██║█████╗  ██████╔╝███████╗██████╔╝██║  ██║ ╚████╔╝ ██╔██╗ ██║███████║██╔████╔██║██║██║     ███████╗",
    "╚██╗ ██╔╝██╔══╝  ██╔══██╗╚════██║██╔══██╗██║  ██║  ╚██╔╝  ██║╚██╗██║██╔══██║██║╚██╔╝██║██║██║     ╚════██║",
    " ╚████╔╝ ███████╗██║  ██║███████║██║  ██║██████╔╝   ██║   ██║ ╚████║██║  ██║██║ ╚═╝ ██║██║╚██████╗███████║",
    "  ╚═══╝  ╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝    ╚═╝   ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝ ╚═════╝╚══════╝",
    "▓▓▓ V E R S 3 D Y N A M I C S ▓▓▓          ▓▓▓▓▓▓▓  R.A.I.N. Lab  ▓▓▓▓▓▓▓",
]


def _print_banner() -> None:
    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_BLUE, ANSI_CYAN, ANSI_BLUE, ANSI_GREEN]
    for line, color in zip(BANNER_LINES, colors):
        print(f"{color}{line}{ANSI_RESET}", flush=True)


def _spinner(message: str, duration_s: float = 0.9) -> None:
    if not sys.stdout.isatty():
        print(f"{ANSI_CYAN}{message}...{ANSI_RESET}", flush=True)
        return

    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end_time = time.time() + max(0.1, duration_s)
    i = 0
    while time.time() < end_time:
        frame = frames[i % len(frames)]
        print(f"\r{ANSI_CYAN}{frame} {message}{ANSI_RESET}", end="", flush=True)
        i += 1
        time.sleep(0.08)
    print(f"\r{ANSI_GREEN}✔ {message}{ANSI_RESET}")


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
        choices=["rlm", "chat"],
        default="chat",
        help="Which engine to run: rlm (tool-exec) or chat (openai chat completions)",
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
    args = parser.parse_args(known)
    return args, passthrough


def build_command(args: argparse.Namespace, passthrough: list[str], repo_root: Path) -> list[str]:
    if args.mode == "rlm":
        target = repo_root / "rain_lab_meeting.py"
        cmd = [sys.executable, str(target)]
        if args.topic:
            cmd.extend(["--topic", args.topic])
        if args.turns is not None:
            cmd.extend(["--turns", str(args.turns)])
        cmd.extend(passthrough)
        return cmd

    target = repo_root / "rain_lab_meeting_chat_version.py"
    cmd = [sys.executable, str(target)]
    if args.topic:
        cmd.extend(["--topic", args.topic])
    if args.library:
        cmd.extend(["--library", args.library])
    if args.turns is not None:
        cmd.extend(["--max-turns", str(args.turns)])
    cmd.extend(passthrough)
    return cmd


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    args, passthrough = parse_args(argv)
    repo_root = Path(__file__).resolve().parent
    cmd = build_command(args, passthrough, repo_root)

    child_env = None
    if args.library:
        child_env = dict(os.environ)
        child_env["JAMES_LIBRARY_PATH"] = args.library

    _print_banner()
    _spinner("Booting VERS3DYNAMICS R.A.I.N. Lab launcher")
    print(f"{ANSI_CYAN}Launching mode={args.mode}: {' '.join(cmd)}{ANSI_RESET}", flush=True)
    result = subprocess.run(cmd, env=child_env)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
