"""Guided first-run workflow for new local users."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided first-run onboarding for R.A.I.N. Lab.")
    parser.add_argument(
        "--topic",
        type=str,
        default="local-first AI research",
        help="Starter topic to include in the suggested first chat command.",
    )
    return parser.parse_args(argv)


def _run_preflight(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root / "rain_preflight_check.py")],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


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


def _print_next_steps(topic: str, godot_available: bool) -> None:
    print("\n[first-run] Next steps")
    if godot_available:
        print(f"  1. python rain_lab.py --mode chat --ui auto --topic \"{topic}\"")
    else:
        print(f"  1. python rain_lab.py --mode chat --topic \"{topic}\"")
        print("     (optional: run 'python godot_setup.py' first for visual avatars)")
    print("  2. python rain_lab.py --mode backup")
    print("  3. Review docs/TROUBLESHOOTING.md if you hit runtime issues")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent

    print("[first-run] Running preflight checks...")
    result = _run_preflight(repo_root)

    if result.returncode == 0:
        print("[first-run] Preflight passed.")
        godot_ok = _check_godot(repo_root)
        _print_next_steps(args.topic, godot_ok)
        return 0

    if result.returncode == 1:
        print("[first-run] Preflight reported actionable issues.")
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        print("\n[first-run] Fix the checks above, then re-run:")
        print("  python rain_lab.py --mode first-run")
        return 1

    print("[first-run] Preflight failed unexpectedly.")
    if result.stderr.strip():
        print(result.stderr.strip())
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
