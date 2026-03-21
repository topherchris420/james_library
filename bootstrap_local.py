"""Reproducible local bootstrap for R.A.I.N. Lab."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agents import PEER_REVIEW_PROTOCOL, STAGE_PROTOCOL


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
    parser.add_argument(
        "--register-rust-agents",
        action="store_true",
        help="Register James/Jasmine/Luca/Elena with local Rust daemon registry.",
    )
    parser.add_argument(
        "--rust-api-url",
        default=os.environ.get("RAIN_RUST_DAEMON_API_URL", "http://127.0.0.1:4200"),
        help="Rust daemon API base URL used for agent registration.",
    )
    parser.add_argument(
        "--registry-output",
        default="meeting_archives/rust_agent_registry.json",
        help="Where to write the generated Rust-agent registry JSON snapshot.",
    )
    return parser.parse_args(argv)


def _build_rust_agent_registry() -> dict:
    stage_prompt = STAGE_PROTOCOL.strip()
    peer_review_prompt = PEER_REVIEW_PROTOCOL.strip()

    base_prompt = (
        f"{stage_prompt}\n\n"
        f"{peer_review_prompt}\n\n"
        "You must preserve epistemic hygiene, avoid unsupported claims, "
        "and clearly mark speculation when evidence is incomplete."
    )

    agents = [
        {
            "id": "james",
            "name": "James",
            "role": "Lead Scientist/Technician",
            "system_prompt": (
                f"{base_prompt}\n\nPrimary objective: coordinate hypotheses, simulation framing, and synthesis quality."
            ),
            "skills": ["web-search"],
        },
        {
            "id": "jasmine",
            "name": "Jasmine",
            "role": "Hardware Architect",
            "system_prompt": (
                f"{base_prompt}\n\n"
                "Primary objective: enforce hardware feasibility and realistic implementation constraints."
            ),
            "skills": ["web-search"],
        },
        {
            "id": "luca",
            "name": "Luca",
            "role": "Field Tomographer / Theorist",
            "system_prompt": (
                f"{base_prompt}\n\n"
                "Primary objective: challenge topology/field assumptions and maintain rigorous math checks."
            ),
            "skills": ["web-search", "docker"],
        },
        {
            "id": "elena",
            "name": "Elena",
            "role": "Quantum Information Theorist",
            "system_prompt": (
                f"{base_prompt}\n\n"
                "Primary objective: audit computational bounds, coherence limits, and information-theoretic validity."
            ),
            "skills": ["web-search", "docker"],
        },
    ]

    return {
        "registry_version": "v1",
        "agents": agents,
    }


def _register_rust_agents(repo_root: Path, rust_api_url: str, output_path: Path) -> None:
    payload = _build_rust_agent_registry()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[bootstrap] wrote registry snapshot: {output_path}")

    try:
        import httpx

        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = client.post(
                f"{rust_api_url.rstrip('/')}/v1/registry/agents/bulk",
                json=payload,
            )
            response.raise_for_status()
            print("[bootstrap] rust agent registration: success")
    except Exception as exc:
        print(f"[bootstrap] rust agent registration skipped/failed: {exc}")
        print("[bootstrap] You can import the generated snapshot manually into the Rust daemon registry.")


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

    if args.register_rust_agents:
        _register_rust_agents(
            repo_root=repo_root,
            rust_api_url=args.rust_api_url,
            output_path=(repo_root / args.registry_output).resolve(),
        )

    print("\n[bootstrap] done")
    print(f"[bootstrap] activate env: {venv_dir}")
    print('[bootstrap] run chat: python rain_lab.py --mode chat --topic "your topic"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
