"""Unified launcher for R.A.I.N. Lab meeting modes.

Usage examples:
  python rain_lab.py --mode first-run
  python rain_lab.py --mode rlm --topic "Guarino paper"
  python rain_lab.py --mode chat --topic "Guarino paper" -- --recursive-depth 2
  python rain_lab.py --mode godot --topic "Guarino paper"
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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
ASCII_ART_LINES = [
    "\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557\u2588\u2588\u2588\u2557   \u2588\u2588\u2557    \u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557 ",
    "\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551    \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557",
    "\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2554\u2588\u2588\u2557 \u2588\u2588\u2551    \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d",
    "\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2551\u255a\u2588\u2588\u2557\u2588\u2588\u2551    \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557",
    "\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2551 \u255a\u2588\u2588\u2588\u2588\u2551    \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d",
    "\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u2550\u2550\u255d    \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u255d ",
    "\u2593" * 55,
    ("\u2592" * 18) + " V E R S 3 D Y N A M I C S " + ("\u2592" * 12),
]

VALID_UI_MODES = {"auto", "on", "off"}
ZEROCLAW_LAUNCHER_MODES = {"zeroclaw", "status", "providers", "models", "gateway", "daemon", "onboard"}
NON_TOPIC_LAUNCHER_MODES = {"hello-os", "compile", "preflight", "health", "validate", "doctor", "backup", "first-run", "james-chat"} | ZEROCLAW_LAUNCHER_MODES
QUIET_BANNER_MODES = {"health", "validate"}


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _print_banner() -> None:
    if (getattr(sys.stdout, "encoding", "") or "").lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    supports_overlay = bool(getattr(sys.stdout, "isatty", lambda: False)())

    art_colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_BLUE, ANSI_CYAN, ANSI_GREEN, ANSI_BLUE, ANSI_YELLOW]
    for line, color in zip(ASCII_ART_LINES, art_colors):
        safe_line = _console_safe(line)
        if supports_overlay:
            print(f"{ANSI_DIM} {safe_line}{ANSI_RESET}\r{color}{safe_line} {ANSI_RESET}", flush=True)
        else:
            print(f"{color}{safe_line}{ANSI_RESET}", flush=True)
    print("", flush=True)

    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_YELLOW]
    for line, color in zip(BANNER_LINES, colors):
        safe_line = _console_safe(line)
        if supports_overlay:
            print(f"{ANSI_DIM} {safe_line}{ANSI_RESET}\r{color}{safe_line} {ANSI_RESET}", flush=True)
        else:
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
    default_ui_mode = os.environ.get("RAIN_UI_MODE", "off").strip().lower()
    if default_ui_mode not in VALID_UI_MODES:
        default_ui_mode = "off"
    default_restart_sidecars = _env_bool("RAIN_RESTART_SIDECARS", True)

    parser = argparse.ArgumentParser(
        description="Unified launcher for rain_lab_meeting modes"
    )
    parser.add_argument(
        "--mode",
        choices=[
            "rlm",
            "chat",
            "james-chat",
            "godot",
            "hello-os",
            "compile",
            "preflight",
            "health",
            "validate",
            "doctor",
            "backup",
            "first-run",
            "status",
            "providers",
            "models",
            "gateway",
            "daemon",
            "onboard",
            "zeroclaw",
        ],
        default="chat",
        help="Which engine to run: Python meeting modes, validation/health flows, or embedded ZeroClaw Rust modes such as status, providers, models, gateway, daemon, onboard, and zeroclaw passthrough.",
    )
    parser.add_argument("--topic", type=str, default=None, help="Meeting topic")
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Chat/Godot modes: resume from a JSON checkpoint or markdown meeting log",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=str,
        default=os.environ.get("RAIN_SESSION_CHECKPOINT", "meeting_archives/latest_session_checkpoint.json"),
        help="Chat/Godot modes: structured JSON checkpoint path",
    )
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
        default=float(os.environ.get("RAIN_LM_TIMEOUT", "180")),
        help="Chat mode only: LM request timeout in seconds (default: 180; maps to --timeout)",
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
        help="Reserved for runtime integrations; ignored by meeting chat mode.",
    )
    parser.add_argument(
        "--zeroclaw-bin",
        type=str,
        default=os.environ.get("RAIN_ZEROCLAW_BIN", ""),
        help="Path or executable name for ZeroClaw Rust modes (defaults to RAIN_ZEROCLAW_BIN, then local target builds, then PATH).",
    )
    parser.add_argument(
        "--ui",
        choices=sorted(VALID_UI_MODES),
        default=default_ui_mode,
        help="Chat/Godot UI behavior: auto launches avatars when available, on requires UI stack, off (default) forces CLI-only.",
    )
    parser.add_argument(
        "--godot-client-bin",
        type=str,
        default=os.environ.get("RAIN_GODOT_BIN", ""),
        help="UI mode: Godot executable name/path (defaults to RAIN_GODOT_BIN, then godot4/godot).",
    )
    parser.add_argument(
        "--godot-project-dir",
        type=str,
        default=os.environ.get("RAIN_GODOT_PROJECT_DIR", "godot_client"),
        help="UI mode: Godot project directory (must contain project.godot).",
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
        "--bridge",
        action="store_true",
        default=os.environ.get("RAIN_BRIDGE", "0") == "1",
        help="Launch the Rust↔Python bridge server as a sidecar (rain_bridge_server.py).",
    )
    parser.add_argument(
        "--bridge-host",
        type=str,
        default=os.environ.get("RAIN_BRIDGE_HOST", "127.0.0.1"),
        help="Bridge server bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=int(os.environ.get("RAIN_BRIDGE_PORT", "7420")),
        help="Bridge server port (default: 7420).",
    )
    parser.add_argument(
        "--no-godot-bridge",
        action="store_true",
        help="Godot mode: do not auto-launch godot_event_bridge.py.",
    )
    parser.add_argument(
        "--no-godot-client",
        action="store_true",
        help="Godot/chat UI mode: do not auto-launch the Godot client.",
    )
    parser.add_argument(
        "--launcher-log",
        type=str,
        default=os.environ.get("RAIN_LAUNCHER_LOG", "meeting_archives/launcher_events.jsonl"),
        help="Write launcher lifecycle events to JSONL (relative to --library or repo root).",
    )
    parser.add_argument(
        "--no-launcher-log",
        action="store_true",
        help="Disable JSONL launcher event logging.",
    )
    parser.add_argument(
        "--restart-sidecars",
        action="store_true",
        dest="restart_sidecars",
        default=default_restart_sidecars,
        help="Auto-restart Godot sidecars (bridge/client) if they exit while session is running.",
    )
    parser.add_argument(
        "--no-restart-sidecars",
        action="store_false",
        dest="restart_sidecars",
        help="Disable sidecar auto-restart supervision.",
    )
    parser.add_argument(
        "--max-sidecar-restarts",
        type=int,
        default=_env_int("RAIN_MAX_SIDECAR_RESTARTS", 2, 0),
        help="Maximum restart attempts per sidecar process.",
    )
    parser.add_argument(
        "--sidecar-restart-backoff",
        type=float,
        default=_env_float("RAIN_SIDECAR_RESTART_BACKOFF", 0.5, 0.0),
        help="Delay in seconds before restarting a failed sidecar.",
    )
    parser.add_argument(
        "--sidecar-poll-interval",
        type=float,
        default=_env_float("RAIN_SIDECAR_POLL_INTERVAL", 0.25, 0.05),
        help="Supervisor poll interval in seconds while session is running.",
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

    if args.mode == "health":
        target = repo_root / "rain_health_check.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough)
        return cmd

    if args.mode == "validate":
        target = repo_root / "rain_validate.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough)
        return cmd

    if args.mode == "doctor":
        target = repo_root / "rain_doctor.py"
        cmd = [sys.executable, str(target)]
        if args.timeout is not None:
            cmd.extend(["--timeout", str(args.timeout)])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "backup":
        target = repo_root / "rain_lab_backup.py"
        cmd = [sys.executable, str(target)]
        if args.library:
            cmd.extend(["--library", args.library])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "status":
        return _build_zeroclaw_command(args, repo_root, ["status"], passthrough)

    if args.mode == "providers":
        return _build_zeroclaw_command(args, repo_root, ["providers"], passthrough)

    if args.mode == "models":
        model_args = passthrough if passthrough else ["status"]
        return _build_zeroclaw_command(args, repo_root, ["models"], model_args)

    if args.mode == "gateway":
        return _build_zeroclaw_command(args, repo_root, ["gateway"], passthrough)

    if args.mode == "daemon":
        return _build_zeroclaw_command(args, repo_root, ["daemon"], passthrough)

    if args.mode == "onboard":
        return _build_zeroclaw_command(args, repo_root, ["onboard"], passthrough)

    if args.mode == "zeroclaw":
        zeroclaw_passthrough = passthrough if passthrough else ["--help"]
        return _build_zeroclaw_command(args, repo_root, [], zeroclaw_passthrough)

    if args.mode == "hello-os":
        target = repo_root / "hello_os_executable.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough if passthrough else ["inspect"])
        return cmd

    if args.mode == "james-chat":
        target = repo_root / "chat_with_james.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough)
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

    if args.mode in {"chat", "godot"}:
        target = repo_root / "rain_lab_meeting_chat_version.py"
        if not target.exists():
            raise FileNotFoundError("Chat/Godot mode requires rain_lab_meeting_chat_version.py")
        cmd = [sys.executable, str(target)]
        if args.mode == "godot":
            cmd.extend(
                [
                    "--emit-visual-events",
                    "--visual-events-log",
                    args.godot_events_log,
                    "--tts-audio-dir",
                    args.godot_tts_audio_dir,
                ]
            )
        if args.topic:
            cmd.extend(["--topic", args.topic])
        if args.library:
            cmd.extend(["--library", args.library])
        if args.resume:
            cmd.extend(["--resume", args.resume])
        if args.checkpoint_path:
            cmd.extend(["--checkpoint-path", args.checkpoint_path])
        if args.turns is not None:
            cmd.extend(["--max-turns", str(args.turns)])
        if args.timeout is not None:
            cmd.extend(["--timeout", str(args.timeout)])
        if args.no_recursive_intellect or args.recursive_depth is None:
            cmd.append("--no-recursive-intellect")
        elif args.recursive_depth is not None:
            cmd.extend(["--recursive-depth", str(args.recursive_depth)])
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


def _resolve_executable(candidate: str) -> str | None:
    text = (candidate or "").strip()
    if not text:
        return None

    path_candidate = Path(text).expanduser()
    if path_candidate.is_absolute() or any(sep in text for sep in ("/", "\\")):
        if path_candidate.exists():
            return str(path_candidate)
        return None

    return shutil.which(text)


def _zeroclaw_binary_name() -> str:
    return "zeroclaw.exe" if os.name == "nt" else "zeroclaw"


def probe_embedded_zeroclaw(repo_root: Path, zeroclaw_bin: str | None = None) -> dict[str, object]:
    binary_name = _zeroclaw_binary_name()
    candidate_bins = [
        ((zeroclaw_bin or "").strip(), "override"),
        (str(repo_root / "target" / "release" / binary_name), "release"),
        (str(repo_root / "target" / "release-fast" / binary_name), "release-fast"),
        (str(repo_root / "target" / "debug" / binary_name), "debug"),
        (binary_name, "path"),
        (str(Path.home() / ".cargo" / "bin" / binary_name), "cargo-home"),
    ]
    seen: set[str] = set()
    for candidate, source in candidate_bins:
        key = candidate.lower() if os.name == "nt" else candidate
        if not candidate or key in seen:
            continue
        seen.add(key)
        resolved = _resolve_executable(candidate)
        if resolved:
            return {
                "available": True,
                "source": source,
                "resolved": resolved,
                "command": [resolved],
                "error": None,
            }

    cargo_bin = _resolve_executable("cargo")
    if cargo_bin:
        return {
            "available": True,
            "source": "cargo",
            "resolved": cargo_bin,
            "command": [
                cargo_bin,
                "run",
                "--release",
                "--manifest-path",
                str(repo_root / "Cargo.toml"),
                "--",
            ],
            "error": None,
        }

    return {
        "available": False,
        "source": "missing",
        "resolved": None,
        "command": [],
        "error": (
            "ZeroClaw binary not found, and cargo is unavailable for an automatic fallback build. "
            "Build it with 'cargo build --release', install it with 'cargo install --path . --locked', "
            "or point rain_lab.py to it with --zeroclaw-bin."
        ),
    }


def resolve_embedded_zeroclaw_command(repo_root: Path, zeroclaw_bin: str | None = None) -> list[str]:
    probe = probe_embedded_zeroclaw(repo_root, zeroclaw_bin=zeroclaw_bin)
    if probe.get("available"):
        return list(probe.get("command", []))
    raise FileNotFoundError(str(probe.get("error") or "ZeroClaw runtime unavailable."))


def _resolve_zeroclaw_command(args: argparse.Namespace, repo_root: Path) -> list[str]:
    return resolve_embedded_zeroclaw_command(repo_root, zeroclaw_bin=(args.zeroclaw_bin or "").strip())


def _build_zeroclaw_command(
    args: argparse.Namespace,
    repo_root: Path,
    zeroclaw_args: list[str],
    passthrough: list[str] | None = None,
) -> list[str]:
    cmd = _resolve_zeroclaw_command(args, repo_root)
    cmd.extend(zeroclaw_args)
    if passthrough:
        cmd.extend(passthrough)
    return cmd


def build_godot_client_command(args: argparse.Namespace, repo_root: Path) -> list[str] | None:
    if args.no_godot_client:
        return None

    project_dir = Path(args.godot_project_dir).expanduser()
    if not project_dir.is_absolute():
        project_dir = (repo_root / project_dir).resolve()
    project_file = project_dir / "project.godot"
    if not project_file.exists():
        return None

    candidate_bins: list[str] = []
    if args.godot_client_bin:
        candidate_bins.append(args.godot_client_bin)

    # Auto-discover binary downloaded by godot_setup.py
    godot_runtime_dir = repo_root / ".godot_runtime"
    if godot_runtime_dir.is_dir():
        for child in sorted(godot_runtime_dir.iterdir(), reverse=True):
            if child.name.startswith("godot_v") and child.is_file():
                candidate_bins.append(str(child))
                break
        # macOS app bundle
        macos_bin = godot_runtime_dir / "Godot.app" / "Contents" / "MacOS" / "Godot"
        if macos_bin.exists():
            candidate_bins.append(str(macos_bin))

    candidate_bins.extend(["godot4", "godot"])

    for candidate in candidate_bins:
        resolved = _resolve_executable(candidate)
        if resolved:
            return [resolved, "--path", str(project_dir)]

    return None


@dataclass(frozen=True)
class LaunchPlan:
    effective_mode: str
    launch_bridge: bool = False
    launch_godot_client: bool = False
    godot_client_cmd: list[str] | None = None


@dataclass
class SidecarSpec:
    name: str
    command: list[str]
    critical: bool = False


@dataclass
class SidecarState:
    spec: SidecarSpec
    process: subprocess.Popen[bytes]
    restart_count: int = 0
    active: bool = True


def _resolve_launcher_log_path(args: argparse.Namespace, repo_root: Path) -> Path | None:
    if args.no_launcher_log:
        return None

    raw = (args.launcher_log or "").strip()
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate

    if args.library:
        base_dir = Path(args.library).expanduser()
        if not base_dir.is_absolute():
            base_dir = (Path.cwd() / base_dir).resolve()
    else:
        base_dir = repo_root

    return (base_dir / candidate).resolve()


def _append_launcher_event(log_path: Path | None, event: str, **payload: object) -> None:
    if log_path is None:
        return

    record = {"ts": _utc_now_iso(), "event": event, **payload}
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Logging must never block the launcher.
        return


def _launch_sidecar(
    spec: SidecarSpec,
    child_env: dict[str, str] | None,
    log_path: Path | None,
) -> SidecarState:
    _spinner(f"Starting {spec.name}")
    print(f"{ANSI_CYAN}Launching {spec.name}: {' '.join(spec.command)}{ANSI_RESET}", flush=True)
    process = subprocess.Popen(spec.command, env=child_env)
    _append_launcher_event(
        log_path,
        "sidecar_started",
        sidecar=spec.name,
        pid=process.pid,
        command=spec.command,
        critical=spec.critical,
        restart_count=0,
    )
    return SidecarState(spec=spec, process=process)


def _supervise_sidecars(
    sidecars: list[SidecarState],
    child_env: dict[str, str] | None,
    args: argparse.Namespace,
    log_path: Path | None,
) -> str | None:
    for sidecar in sidecars:
        if not sidecar.active:
            continue

        exit_code = sidecar.process.poll()
        if exit_code is None:
            continue

        _append_launcher_event(
            log_path,
            "sidecar_exited",
            sidecar=sidecar.spec.name,
            exit_code=exit_code,
            pid=sidecar.process.pid,
            restart_count=sidecar.restart_count,
            critical=sidecar.spec.critical,
        )
        print(
            f"{ANSI_YELLOW}Warning: {sidecar.spec.name} exited with code {exit_code}.{ANSI_RESET}",
            flush=True,
        )

        should_restart = (
            args.restart_sidecars
            and sidecar.restart_count < max(0, int(args.max_sidecar_restarts))
        )
        if should_restart:
            sidecar.restart_count += 1
            backoff = max(0.0, float(args.sidecar_restart_backoff))
            if backoff > 0.0:
                time.sleep(backoff)

            try:
                sidecar.process = subprocess.Popen(sidecar.spec.command, env=child_env)
            except Exception as exc:
                sidecar.active = False
                _append_launcher_event(
                    log_path,
                    "sidecar_restart_failed",
                    sidecar=sidecar.spec.name,
                    restart_count=sidecar.restart_count,
                    error=str(exc),
                    critical=sidecar.spec.critical,
                )
                if sidecar.spec.critical:
                    return f"{sidecar.spec.name} failed to restart ({exc})"
                continue

            _append_launcher_event(
                log_path,
                "sidecar_restarted",
                sidecar=sidecar.spec.name,
                pid=sidecar.process.pid,
                restart_count=sidecar.restart_count,
                max_restarts=args.max_sidecar_restarts,
            )
            print(
                f"{ANSI_GREEN}Recovered: restarted {sidecar.spec.name} "
                f"({sidecar.restart_count}/{args.max_sidecar_restarts}).{ANSI_RESET}",
                flush=True,
            )
            continue

        sidecar.active = False
        if sidecar.spec.critical:
            return (
                f"{sidecar.spec.name} stopped (exit {exit_code}) and restart budget is exhausted."
            )

    return None


def resolve_launch_plan(args: argparse.Namespace, repo_root: Path) -> LaunchPlan:
    visual_runtime_exists = (repo_root / "rain_lab_meeting_chat_version.py").exists()
    bridge_exists = (repo_root / "godot_event_bridge.py").exists()
    godot_client_cmd = build_godot_client_command(args, repo_root)

    wants_bridge = not args.no_godot_bridge
    wants_client = not args.no_godot_client

    if args.mode == "chat":
        if args.ui == "off":
            return LaunchPlan(effective_mode="chat")

        if args.ui == "on":
            missing: list[str] = []
            if not visual_runtime_exists:
                missing.append("rain_lab_meeting_chat_version.py")
            if wants_bridge and not bridge_exists:
                missing.append("godot_event_bridge.py")
            if wants_client and godot_client_cmd is None:
                missing.append("Godot executable + godot_client/project.godot")
            if missing:
                missing_str = ", ".join(missing)
                raise RuntimeError(f"UI mode 'on' requires: {missing_str}")
            return LaunchPlan(
                effective_mode="godot",
                launch_bridge=wants_bridge,
                launch_godot_client=wants_client and godot_client_cmd is not None,
                godot_client_cmd=godot_client_cmd,
            )

        # ui=auto: prefer avatars only when the full stack is available.
        if not visual_runtime_exists:
            return LaunchPlan(effective_mode="chat")
        if wants_bridge and not bridge_exists:
            return LaunchPlan(effective_mode="chat")
        if wants_client and godot_client_cmd is None:
            return LaunchPlan(effective_mode="chat")
        return LaunchPlan(
            effective_mode="godot",
            launch_bridge=wants_bridge,
            launch_godot_client=wants_client and godot_client_cmd is not None,
            godot_client_cmd=godot_client_cmd,
        )

    if args.mode == "godot":
        if not visual_runtime_exists:
            raise FileNotFoundError("Godot mode requires rain_lab_meeting_chat_version.py")
        if wants_bridge and not bridge_exists:
            raise FileNotFoundError("Godot mode bridge requires godot_event_bridge.py")

        launch_client = args.ui != "off" and wants_client and godot_client_cmd is not None
        return LaunchPlan(
            effective_mode="godot",
            launch_bridge=wants_bridge,
            launch_godot_client=launch_client,
            godot_client_cmd=godot_client_cmd if launch_client else None,
        )

    return LaunchPlan(effective_mode=args.mode)


def _build_sidecar_specs(
    args: argparse.Namespace,
    launch_plan: LaunchPlan,
    bridge_cmd: list[str] | None,
    repo_root: Path | None = None,
) -> list[SidecarSpec]:
    strict_ui = args.ui == "on"
    specs: list[SidecarSpec] = []

    if bridge_cmd is not None:
        specs.append(SidecarSpec(name="Godot event bridge", command=bridge_cmd, critical=strict_ui))

    if launch_plan.launch_godot_client and launch_plan.godot_client_cmd is not None:
        specs.append(
            SidecarSpec(
                name="Godot avatar client",
                command=launch_plan.godot_client_cmd,
                critical=strict_ui,
            )
        )

    # Rust↔Python bridge server
    if getattr(args, "bridge", False) and repo_root is not None:
        bridge_script = repo_root / "rain_bridge_server.py"
        if bridge_script.exists():
            specs.append(
                SidecarSpec(
                    name="Rust↔Python bridge",
                    command=[
                        sys.executable, str(bridge_script),
                        "--host", getattr(args, "bridge_host", "127.0.0.1"),
                        "--port", str(getattr(args, "bridge_port", 7420)),
                    ],
                    critical=False,
                )
            )

    return specs


def _copy_args_with_mode(args: argparse.Namespace, mode: str) -> argparse.Namespace:
    payload = vars(args).copy()
    payload["mode"] = mode
    return argparse.Namespace(**payload)


def _terminate_process(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()


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

    if args.mode not in QUIET_BANNER_MODES:
        _print_banner()

    # Show quick mode overview on first interaction
    if args.mode not in NON_TOPIC_LAUNCHER_MODES and not args.topic and "-h" not in passthrough and "--help" not in passthrough:
        print(f"{ANSI_DIM}  Modes:  --mode chat        Multi-agent research meeting (default){ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode james-chat   1:1 conversation with James via RLM{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode godot        Chat + Godot visual avatars{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode preflight    Environment health checks{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode health       One-screen system snapshot{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode validate     Full readiness validation{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode doctor       LM Studio diagnostics and repair hints{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode first-run    Guided onboarding{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode status       ZeroClaw runtime status{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode providers    ZeroClaw provider catalog{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode models       ZeroClaw model catalog/status{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode gateway      ZeroClaw web gateway{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode onboard      ZeroClaw setup wizard{ANSI_RESET}")
        print(f"{ANSI_DIM}          --mode zeroclaw     Direct passthrough to embedded Rust CLI{ANSI_RESET}")
        print(f"{ANSI_DIM}          Run with --help for all options{ANSI_RESET}")

    # Interactive prompt if topic is missing (and not asking for help)
    if args.mode not in NON_TOPIC_LAUNCHER_MODES and not args.topic and "-h" not in passthrough and "--help" not in passthrough:
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

    launch_plan = resolve_launch_plan(args, repo_root)
    if args.mode == "chat" and args.ui == "auto":
        if launch_plan.effective_mode == "godot":
            print(f"{ANSI_GREEN}UI auto: Godot avatars available; launching visual mode.{ANSI_RESET}")
        else:
            print(f"{ANSI_DIM}UI auto: Godot UI unavailable; running CLI chat mode.{ANSI_RESET}")
            print(f"{ANSI_DIM}  Tip: run 'python godot_setup.py' to download the Godot runtime for visual avatars.{ANSI_RESET}")

    log_path = _resolve_launcher_log_path(args, repo_root)
    _append_launcher_event(
        log_path,
        "launcher_started",
        requested_mode=args.mode,
        ui=args.ui,
        restart_sidecars=bool(args.restart_sidecars),
        max_sidecar_restarts=max(0, int(args.max_sidecar_restarts)),
        sidecar_restart_backoff=max(0.0, float(args.sidecar_restart_backoff)),
        sidecar_poll_interval=max(0.05, float(args.sidecar_poll_interval)),
        passthrough=passthrough,
    )

    effective_args = _copy_args_with_mode(args, launch_plan.effective_mode)
    cmd = build_command(effective_args, passthrough, repo_root)

    bridge_cmd: list[str] | None = None
    if launch_plan.launch_bridge:
        bridge_cmd = build_godot_bridge_command(effective_args, repo_root)
    sidecar_specs = _build_sidecar_specs(args, launch_plan, bridge_cmd, repo_root=repo_root)

    child_env = None
    if args.library:
        child_env = dict(os.environ)
        child_env["JAMES_LIBRARY_PATH"] = args.library

    sidecars: list[SidecarState] = []
    main_proc: subprocess.Popen[bytes] | None = None
    exit_code = 1

    auto_chat_visual = args.mode == "chat" and args.ui == "auto" and launch_plan.effective_mode == "godot"
    try:
        for spec in sidecar_specs:
            sidecars.append(_launch_sidecar(spec, child_env, log_path))
            time.sleep(0.25)
    except Exception as exc:
        for sidecar in sidecars:
            _terminate_process(sidecar.process)
        sidecars = []

        if auto_chat_visual:
            print(
                f"{ANSI_YELLOW}UI auto: visual startup failed ({exc}); falling back to CLI chat mode.{ANSI_RESET}",
                flush=True,
            )
            _append_launcher_event(
                log_path,
                "ui_auto_fallback",
                reason=str(exc),
                from_mode=launch_plan.effective_mode,
                to_mode="chat",
            )
            effective_args = _copy_args_with_mode(args, "chat")
            cmd = build_command(effective_args, passthrough, repo_root)
            sidecar_specs = []
        else:
            _append_launcher_event(log_path, "launcher_failed", phase="sidecar_launch", error=str(exc))
            raise

    if effective_args.mode not in QUIET_BANNER_MODES:
        _spinner("Booting VERS3DYNAMICS R.A.I.N. Lab launcher")
        print(f"{ANSI_CYAN}Launching mode={effective_args.mode}...{ANSI_RESET}", flush=True)
    _append_launcher_event(
        log_path,
        "session_launch",
        mode=effective_args.mode,
        command=cmd,
        sidecars=[sidecar.spec.name for sidecar in sidecars],
    )
    try:
        main_proc = subprocess.Popen(cmd, env=child_env)
        _append_launcher_event(
            log_path,
            "session_started",
            mode=effective_args.mode,
            pid=main_proc.pid,
        )

        poll_interval = max(0.05, float(args.sidecar_poll_interval))
        while True:
            result_code = main_proc.poll()
            if result_code is not None:
                exit_code = int(result_code)
                break

            fatal = _supervise_sidecars(sidecars, child_env, args, log_path)
            if fatal:
                print(f"{ANSI_RED}Critical sidecar failure: {fatal}{ANSI_RESET}", flush=True)
                _append_launcher_event(log_path, "sidecar_fatal", reason=fatal)
                _terminate_process(main_proc)
                exit_code = 1
                break

            time.sleep(poll_interval)

        return exit_code
    finally:
        _terminate_process(main_proc)
        for sidecar in sidecars:
            _terminate_process(sidecar.process)
        _append_launcher_event(
            log_path,
            "launcher_finished",
            exit_code=exit_code,
            mode=effective_args.mode,
        )


if __name__ == "__main__":
    raise SystemExit(main())
