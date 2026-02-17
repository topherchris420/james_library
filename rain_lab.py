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
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_DIM = "\033[90m"

BANNER_LINES = [
    "██████╗  █████╗ ██╗███╗   ██╗    ██╗      █████╗ ██████╗ ",
    "██╔══██╗██╔══██╗██║████╗  ██║    ██║     ██╔══██╗██╔══██╗",
    "██████╔╝███████║██║██╔██╗ ██║    ██║     ███████║██████╔╝",
    "██╔══██╗██╔══██║██║██║╚██╗██║    ██║     ██╔══██║██╔══██╗",
    "██║  ██║██║  ██║██║██║ ╚████║    ███████╗██║  ██║██████╔╝",
    "╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝    ╚══════╝╚═╝  ╚═╝╚═════╝ ",
    "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓",
    "▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ V E R S 3 D Y N A M I C S ▒▒▒▒▒▒▒▒▒▒▒▒",
]


def _print_banner() -> None:
    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_BLUE, ANSI_CYAN, ANSI_GREEN, ANSI_BLUE, ANSI_YELLOW]
    for line, color in zip(BANNER_LINES, colors):
        print(f"{ANSI_DIM} {line}{ANSI_RESET}", flush=True)
        print(f"{color}{line}{ANSI_RESET}", flush=True)


def _spinner(message: str, duration_s: float = 1.25) -> None:
    if not sys.stdout.isatty():
        print(f"{ANSI_CYAN}{message}...{ANSI_RESET}", flush=True)
        return

    frames = ["▱▱▱", "▰▱▱", "▰▰▱", "▰▰▰", "▱▰▰", "▱▱▰"]
    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_GREEN, ANSI_YELLOW]
    end_time = time.time() + max(0.2, duration_s)
    i = 0
    while time.time() < end_time:
        frame = frames[i % len(frames)]
        color = colors[i % len(colors)]
        pulse = "•" * ((i % 3) + 1)
        print(f"\r{color}{frame} {message} {pulse}{ANSI_RESET}   ", end="", flush=True)
        i += 1
        time.sleep(0.09)
    print(f"\r{ANSI_GREEN}✔ {message}{ANSI_RESET}   ")


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
        choices=["rlm", "chat", "hello-os"],
        default="chat",
        help="Which engine to run: rlm (tool-exec), chat (openai chat completions), or hello-os (single executable)",
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
    args = parser.parse_args(known)
    return args, passthrough


def build_command(args: argparse.Namespace, passthrough: list[str], repo_root: Path) -> list[str]:
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

    target = repo_root / "chat_with_james.py"
    if not target.exists():
        raise FileNotFoundError(
            "Chat mode requires chat_with_james.py; rain_lab_meeting_chat_version.py "
            "is no longer used by rain_lab.py"
        )
    cmd = [sys.executable, str(target)]
    if args.topic:
        cmd.extend(["--topic", args.topic])
    if args.library:
        cmd.extend(["--library", args.library])
    if args.turns is not None:
        cmd.extend(["--max-turns", str(args.turns)])
    if args.timeout is not None:
        cmd.extend(["--timeout", str(args.timeout)])
    if args.recursive_depth is not None:
        cmd.extend(["--recursive-depth", str(args.recursive_depth)])
    if args.no_recursive_intellect:
        cmd.append("--no-recursive-intellect")
    cmd.extend(passthrough)
    return cmd


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    args, passthrough = parse_args(argv)
    repo_root = Path(__file__).resolve().parent

    _print_banner()

    # Interactive prompt if topic is missing (and not asking for help)
    if args.mode != "hello-os" and not args.topic and "-h" not in passthrough and "--help" not in passthrough:
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

    child_env = None
    if args.library:
        child_env = dict(os.environ)
        child_env["JAMES_LIBRARY_PATH"] = args.library

    _spinner("Booting VERS3DYNAMICS R.A.I.N. Lab launcher")
    print(f"{ANSI_CYAN}Launching mode={args.mode}: {' '.join(cmd)}{ANSI_RESET}", flush=True)
    result = subprocess.run(cmd, env=child_env)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
