"""Reproducible local bootstrap for R.A.I.N. Lab."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _choose_runtime_requirements(repo_root: Path) -> Path:
    pinned = repo_root / "requirements-pinned.txt"
    if pinned.exists():
        return pinned
    return repo_root / "requirements.txt"


def _choose_dev_requirements(repo_root: Path) -> Path | None:
    pinned = repo_root / "requirements-dev-pinned.txt"
    if pinned.exists():
        return pinned
    fallback = repo_root / "requirements-dev.txt"
    if fallback.exists():
        return fallback
    return None


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"[bootstrap] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a reproducible local R.A.I.N. Lab environment.")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to create the virtual environment.",
    )
    parser.add_argument(
        "--venv",
        default=".venv",
        help="Virtual environment path (default: .venv).",
    )
    parser.add_argument(
        "--no-dev",
        action="store_true",
        help="Skip development dependencies.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip preflight check after install.",
    )
    parser.add_argument(
        "--recreate-venv",
        action="store_true",
        help="Delete and recreate virtual environment if it already exists.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent
    venv_dir = (repo_root / args.venv).resolve()

    if args.recreate_venv and venv_dir.exists():
        print(f"[bootstrap] removing existing venv: {venv_dir}")
        shutil.rmtree(venv_dir)

    if not venv_dir.exists():
        _run([args.python, "-m", "venv", str(venv_dir)], cwd=repo_root)

    venv_python = _venv_python(venv_dir)
    if not venv_python.exists():
        print(f"[bootstrap] error: venv python not found at {venv_python}")
        return 1

    runtime_req = _choose_runtime_requirements(repo_root)
    dev_req = _choose_dev_requirements(repo_root)

    _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=repo_root)
    _run([str(venv_python), "-m", "pip", "install", "-r", str(runtime_req)], cwd=repo_root)

    if not args.no_dev and dev_req is not None:
        _run([str(venv_python), "-m", "pip", "install", "-r", str(dev_req)], cwd=repo_root)

    if not args.skip_preflight:
        _run([str(venv_python), "rain_lab.py", "--mode", "preflight"], cwd=repo_root)

    print("\n[bootstrap] done")
    print(f"[bootstrap] activate env: {venv_dir}")
    print("[bootstrap] run chat: python rain_lab.py --mode chat --topic \"your topic\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
