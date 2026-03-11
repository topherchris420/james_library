"""Guided first-run workflow for new local users."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from rich_ui import print_panel, supports_ansi
    _RICH = True
    _ANSI = supports_ansi()
except ImportError:
    _RICH = False
    _ANSI = True


def _dim(text: str) -> str:
    if _ANSI:
        return f"\033[90m{text}\033[0m"
    return text


def _green(text: str) -> str:
    if _ANSI:
        return f"\033[92m{text}\033[0m"
    return text


DEFAULT_STARTER_TOPIC = "local-first AI research"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided first-run onboarding for R.A.I.N. Lab.")
    parser.add_argument(
        "--topic",
        type=str,
        default=DEFAULT_STARTER_TOPIC,
        help="Starter topic to include in the suggested first chat command.",
    )
    parser.add_argument(
        "--launch-chat",
        action="store_true",
        help="Launch chat automatically after successful onboarding.",
    )
    return parser.parse_args(argv)


def _run_preflight(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root / "rain_preflight_check.py")],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


def _startup_marker_path(repo_root: Path) -> Path:
    return repo_root / "meeting_archives" / ".first_run_complete"


def _mark_first_run_complete(repo_root: Path) -> None:
    marker = _startup_marker_path(repo_root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("first_run_completed=1\n", encoding="utf-8")


def _launch_chat(repo_root: Path, topic: str) -> int:
    cmd = [sys.executable, str(repo_root / "rain_lab.py"), "--mode", "chat", "--ui", "auto"]
    if topic.strip() and topic != DEFAULT_STARTER_TOPIC:
        cmd.extend(["--topic", topic])
    return subprocess.run(cmd, cwd=str(repo_root)).returncode


def _check_embedded_zeroclaw(repo_root: Path) -> str:
    try:
        from rain_lab import probe_embedded_zeroclaw
    except Exception as exc:
        print(f"[first-run] Embedded ZeroClaw runtime check unavailable: {exc}")
        return "missing"

    probe = probe_embedded_zeroclaw(repo_root)
    source = str(probe.get("source", "missing"))
    resolved = probe.get("resolved")
    if not probe.get("available"):
        print("[first-run] Embedded ZeroClaw runtime is optional and not currently ready.")
        print("  Install Rust or provide --zeroclaw-bin later if you want Rust-side ops like status, models, or gateway.")
        return "missing"

    if source == "cargo":
        print("[first-run] Embedded ZeroClaw runtime available via cargo fallback.")
        print("  The first Rust-side command may compile the runtime before it starts.")
        return source

    print(f"[first-run] Embedded ZeroClaw runtime ready ({source}: {resolved})")
    return source


def _check_godot(repo_root: Path) -> bool:
    """Check if Godot is available and offer to install if not."""
    try:
        from godot_setup import DEFAULT_GODOT_VERSION, check_godot_status, download_godot
    except ImportError:
        return False

    print("\n[first-run] Checking Godot visual UI...")
    status = check_godot_status(verbose=True)
    if status["installed"]:
        return True

    print("\n  The Godot visual UI provides animated agent avatars during meetings.")
    print("  It's optional — CLI chat works without it.\n")
    try:
        answer = input("  Download Godot runtime for visual avatars? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if answer and answer not in ("y", "yes"):
        print("  Skipped. You can run 'python godot_setup.py' later.")
        return False

    try:
        download_godot(DEFAULT_GODOT_VERSION, verbose=True)
        return True
    except Exception as exc:
        print(f"  ⚠ Godot download failed: {exc}")
        print("  You can retry later: python godot_setup.py")
        return False


def _print_next_steps(topic: str, godot_available: bool, zeroclaw_status: str) -> None:
    if godot_available:
        step1 = f"python rain_lab.py --mode chat --ui auto --topic \"{topic}\""
        extra = ""
    else:
        step1 = f"python rain_lab.py --mode chat --topic \"{topic}\""
        extra = "  (optional: run 'python godot_setup.py' first for visual avatars)\n"
    zeroclaw_steps = ""
    if zeroclaw_status != "missing":
        zeroclaw_steps = (
            "  2. python rain_lab.py --mode status\n"
            "  3. python rain_lab.py --mode models\n"
        )
        backup_step = "  4. python rain_lab.py --mode backup\n"
        docs_step = "  5. Review docs/TROUBLESHOOTING.md if you hit runtime issues"
    else:
        backup_step = "  2. python rain_lab.py --mode backup\n"
        docs_step = "  3. Review docs/TROUBLESHOOTING.md if you hit runtime issues"
    steps = (
        f"  1. {step1}\n"
        f"{extra}"
        f"{zeroclaw_steps}"
        f"{backup_step}"
        f"{docs_step}"
    )
    if _RICH:
        print_panel("Next Steps", steps)
    else:
        print("\n[first-run] Next steps")
        print(steps)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent

    if _RICH:
        print_panel("First-Run Onboarding", "Checking your environment...")
    else:
        print("[first-run] Running preflight checks...")
    result = _run_preflight(repo_root)

    if result.returncode == 0:
        print(_green("[first-run] Preflight passed."))
        zeroclaw_status = _check_embedded_zeroclaw(repo_root)
        godot_ok = _check_godot(repo_root)
        _mark_first_run_complete(repo_root)
        if args.launch_chat:
            print(_dim("[first-run] Launching chat..."))
            return _launch_chat(repo_root, args.topic)
        _print_next_steps(args.topic, godot_ok, zeroclaw_status)
        return 0

    if result.returncode == 1:
        print("[first-run] Preflight reported actionable issues.")
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        print("\n[first-run] Fix the checks above, then re-run:")
        print("  python rain_lab.py --mode doctor")
        print("  python rain_lab.py --mode first-run")
        return 1

    print("[first-run] Preflight failed unexpectedly.")
    if result.stderr.strip():
        print(result.stderr.strip())
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
