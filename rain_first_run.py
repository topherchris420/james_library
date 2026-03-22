"""Guided first-run workflow for new local users."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import rich_ui


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


def _print_next_steps(topic: str) -> None:
    print("\n" + rich_ui.bold(rich_ui.color("✨ Setup Complete! R.A.I.N. Lab is ready.", "bright_green")))
    print(rich_ui.color("═" * 65, "bright_black"))

    print(f"  {rich_ui.bold('1. Start Chat:')} python rain_lab.py --mode chat --topic \"{topic}\"")
    print(f"  {rich_ui.bold('2. Backup:')}     python rain_lab.py --mode backup")
    print(f"  {rich_ui.bold('3. Docs:')}       Review docs/troubleshooting.md")

    print(rich_ui.color("─" * 65, "bright_black"))
    print(f"  {rich_ui.color('🎮 Want the 3D Avatar experience?', 'bright_cyan')}")
    print(f"  Run: {rich_ui.bold(rich_ui.color('python deploy.py --install-godot-client', 'bright_yellow'))}\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent

    print("[first-run] Running preflight checks...")
    result = _run_preflight(repo_root)

    if result.returncode == 0:
        print("[first-run] Preflight passed.")
        _print_next_steps(args.topic)
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
