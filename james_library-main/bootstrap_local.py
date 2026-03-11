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


def _probe_embedded_zeroclaw(repo_root: Path) -> dict[str, object]:
    try:
        from rain_lab import probe_embedded_zeroclaw
    except Exception as exc:
        cargo_bin = shutil.which("cargo")
        return {
            "available": bool(cargo_bin),
            "source": "cargo" if cargo_bin else "missing",
            "resolved": cargo_bin,
            "error": None if cargo_bin else str(exc),
        }
    return probe_embedded_zeroclaw(repo_root)


def _ensure_embedded_zeroclaw(repo_root: Path, skip_build: bool) -> dict[str, object]:
    probe = _probe_embedded_zeroclaw(repo_root)
    if probe.get("available") and probe.get("source") != "cargo":
        resolved = probe.get("resolved") or "runtime available"
        print(f"[bootstrap] ZeroClaw runtime ready ({probe.get('source')}: {resolved})")
        return probe

    if skip_build:
        if probe.get("available"):
            print("[bootstrap] ZeroClaw runtime available via cargo fallback. Skipping explicit build.")
        else:
            print("[bootstrap] warning: ZeroClaw runtime unavailable. Rust launcher modes will require manual setup.")
        return probe

    cargo_bin = shutil.which("cargo")
    if cargo_bin is None:
        if not probe.get("available"):
            print("[bootstrap] warning: cargo not found; skipping embedded ZeroClaw build.")
        return probe

    print("[bootstrap] preparing embedded ZeroClaw runtime...")
    try:
        _run([cargo_bin, "build", "--release", "--locked", "--bin", "zeroclaw"], cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        print(f"[bootstrap] warning: failed to build embedded ZeroClaw runtime (exit code {exc.returncode}).")
        print("[bootstrap] warning: Python flows are ready; Rust launcher modes may require manual build.")
        return _probe_embedded_zeroclaw(repo_root)

    probe = _probe_embedded_zeroclaw(repo_root)
    if probe.get("available"):
        resolved = probe.get("resolved") or "runtime available"
        print(f"[bootstrap] ZeroClaw runtime ready ({probe.get('source')}: {resolved})")
    else:
        print("[bootstrap] warning: build completed but ZeroClaw runtime could not be resolved.")
    return probe


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
    parser.add_argument(
        "--skip-zeroclaw-build",
        action="store_true",
        help="Skip preparing the embedded ZeroClaw Rust runtime during bootstrap.",
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

    zeroclaw_probe = _ensure_embedded_zeroclaw(
        repo_root,
        skip_build=bool(args.skip_zeroclaw_build),
    )

    if not args.skip_preflight:
        _run([str(venv_python), "rain_lab.py", "--mode", "preflight"], cwd=repo_root)

    print("\n[bootstrap] done")
    print(f"[bootstrap] activate env: {venv_dir}")
    print("[bootstrap] validate stack: python rain_lab.py --mode validate")
    if zeroclaw_probe.get("available"):
        print("[bootstrap] runtime status: python rain_lab.py --mode status")
        print("[bootstrap] model catalog: python rain_lab.py --mode models")
    else:
        print("[bootstrap] optional: install Rust or point --zeroclaw-bin at a prebuilt runtime to enable Rust-side modes")
    print("[bootstrap] first-run guide: python rain_lab.py --mode first-run")
    print("[bootstrap] run chat: python rain_lab.py --mode chat --ui auto --topic \"your topic\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
