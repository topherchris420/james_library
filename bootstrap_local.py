"""Fetch-first local bootstrap for R.A.I.N. Lab."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

from agents import PEER_REVIEW_PROTOCOL, STAGE_PROTOCOL

DEFAULT_RELEASE_REPO = "topherchris420/james_library"
GITHUB_API_ROOT = "https://api.github.com/repos"
GITHUB_TIMEOUT_SECS = 30
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "rain-lab-bootstrap/1.0",
}


class BootstrapError(RuntimeError):
    """Raised when the fetch-first bootstrap cannot complete."""


@dataclass(frozen=True)
class PlatformSpec:
    os_name: str
    arch_name: str
    target: str
    archive_ext: str
    binary_name: str


@dataclass(frozen=True)
class ReleaseAsset:
    tag_name: str
    asset_name: str
    download_url: str


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


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"[bootstrap] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a fetch-first local R.A.I.N. Lab environment.")
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip preflight validation after bootstrap.",
    )
    parser.add_argument(
        "--skip-binary-fetch",
        action="store_true",
        help="Skip fetching the precompiled Rust engine binary.",
    )
    parser.add_argument(
        "--skip-config-init",
        action="store_true",
        help="Do not auto-create config.toml from config.example.toml.",
    )
    parser.add_argument(
        "--skip-env-setup",
        action="store_true",
        help="Do not auto-create the workspace .env file.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt for an API key; default to local-model configuration.",
    )
    parser.add_argument(
        "--release-repo",
        default=os.environ.get("RAIN_RELEASE_REPO", "").strip(),
        help="GitHub repository slug for release binaries (owner/repo). Defaults to the current origin remote.",
    )
    parser.add_argument(
        "--release-tag",
        default="latest",
        help="Release tag to fetch. Defaults to latest.",
    )
    parser.add_argument(
        "--bin-dir",
        default="bin",
        help="Directory where the fetched Rust engine binary should be installed.",
    )
    parser.add_argument(
        "--register-rust-agents",
        action="store_true",
        help="Register James/Jasmine/Luca/Elena with the local Rust daemon registry.",
    )
    parser.add_argument(
        "--rust-api-url",
        default=os.environ.get("RAIN_RUST_DAEMON_API_URL", "http://127.0.0.1:4200"),
        help="Rust daemon API base URL used for agent registration.",
    )
    parser.add_argument(
        "--registry-output",
        default="meeting_archives/rust_agent_registry.json",
        help="Where to write the generated Rust-agent registry snapshot.",
    )
    return parser.parse_args(argv)


def _parse_github_repo_slug(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = raw.strip()
    if re.fullmatch(r"[^/\s]+/[^/\s]+", candidate):
        return candidate.removesuffix(".git")

    match = re.search(r"github\.com[:/](?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?(?:[/?#].*)?$", candidate)
    if match:
        return match.group("slug")
    return None


def _git_origin_url(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _cargo_repository_url(repo_root: Path) -> str | None:
    cargo_toml = repo_root / "Cargo.toml"
    if not cargo_toml.exists():
        return None

    text = cargo_toml.read_text(encoding="utf-8")
    match = re.search(r'^\s*repository\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if match:
        return match.group(1)
    return None


def _detect_release_repo(repo_root: Path, explicit: str | None = None) -> str:
    for candidate in (explicit, _git_origin_url(repo_root), _cargo_repository_url(repo_root), DEFAULT_RELEASE_REPO):
        slug = _parse_github_repo_slug(candidate)
        if slug:
            return slug
    return DEFAULT_RELEASE_REPO


def detect_platform_spec(system_name: str | None = None, machine_name: str | None = None) -> PlatformSpec:
    system_value = (system_name or platform.system()).strip().lower()
    machine_value = (machine_name or platform.machine()).strip().lower()

    if system_value == "windows":
        if machine_value in {"amd64", "x86_64"}:
            return PlatformSpec("windows", "intel", "x86_64-pc-windows-msvc", "zip", "rain.exe")
        if machine_value in {"arm64", "aarch64"}:
            return PlatformSpec("windows", "arm64", "aarch64-pc-windows-msvc", "zip", "rain.exe")
    elif system_value == "darwin":
        if machine_value in {"arm64", "aarch64"}:
            return PlatformSpec("macos", "apple-silicon", "aarch64-apple-darwin", "tar.gz", "rain")
        if machine_value in {"amd64", "x86_64"}:
            return PlatformSpec("macos", "intel", "x86_64-apple-darwin", "tar.gz", "rain")
    elif system_value == "linux":
        if machine_value in {"amd64", "x86_64"}:
            return PlatformSpec("linux", "intel", "x86_64-unknown-linux-gnu", "tar.gz", "rain")
        if machine_value in {"arm64", "aarch64"}:
            return PlatformSpec("linux", "arm64", "aarch64-unknown-linux-gnu", "tar.gz", "rain")
        if machine_value == "armv7l":
            return PlatformSpec("linux", "armv7", "armv7-unknown-linux-gnueabihf", "tar.gz", "rain")
        if machine_value == "armv6l":
            return PlatformSpec("linux", "armv6", "arm-unknown-linux-gnueabihf", "tar.gz", "rain")

    raise BootstrapError(
        f"Unsupported platform for prebuilt engine fetch: system={system_value!r}, arch={machine_value!r}"
    )


def _release_asset_candidates(spec: PlatformSpec) -> list[str]:
    return [
        f"R.A.I.N.-{spec.target}.{spec.archive_ext}",
        f"rain-{spec.target}.{spec.archive_ext}",
        f"james_library-{spec.target}.{spec.archive_ext}",
    ]


def _read_json(url: str) -> object:
    req = request.Request(url, headers=GITHUB_HEADERS)
    with request.urlopen(req, timeout=GITHUB_TIMEOUT_SECS) as response:
        return json.load(response)


def _download_file(url: str, destination: Path) -> None:
    req = request.Request(url, headers=GITHUB_HEADERS)
    with request.urlopen(req, timeout=GITHUB_TIMEOUT_SECS) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _fetch_release_feed(repo_slug: str, release_tag: str) -> list[dict]:
    try:
        if release_tag and release_tag != "latest":
            payload = _read_json(f"{GITHUB_API_ROOT}/{repo_slug}/releases/tags/{release_tag}")
            return [payload] if isinstance(payload, dict) else []

        payload = _read_json(f"{GITHUB_API_ROOT}/{repo_slug}/releases?per_page=10")
    except error.HTTPError as exc:
        raise BootstrapError(f"GitHub Releases API request failed: {exc.code} {exc.reason}") from exc
    except error.URLError as exc:
        raise BootstrapError(f"GitHub Releases API unreachable: {exc.reason}") from exc

    if isinstance(payload, list):
        return [release for release in payload if isinstance(release, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def select_release_asset(releases: list[dict], spec: PlatformSpec) -> ReleaseAsset:
    candidates = _release_asset_candidates(spec)

    for release in releases:
        if release.get("draft"):
            continue
        assets = release.get("assets") or []
        for candidate in candidates:
            for asset in assets:
                if asset.get("name") == candidate and asset.get("browser_download_url"):
                    return ReleaseAsset(
                        tag_name=release.get("tag_name", "latest"),
                        asset_name=asset["name"],
                        download_url=asset["browser_download_url"],
                    )

    for release in releases:
        if release.get("draft"):
            continue
        assets = release.get("assets") or []
        for asset in assets:
            name = str(asset.get("name") or "")
            if spec.target in name and name.endswith(spec.archive_ext) and asset.get("browser_download_url"):
                return ReleaseAsset(
                    tag_name=release.get("tag_name", "latest"),
                    asset_name=name,
                    download_url=asset["browser_download_url"],
                )

    raise BootstrapError(
        f"No release asset found for target {spec.target}. Expected one of: {', '.join(candidates)}"
    )


def _candidate_binary_names(spec: PlatformSpec) -> list[str]:
    names = [spec.binary_name]
    if spec.binary_name != "rain":
        names.append("rain")
    if spec.binary_name != "rain.exe":
        names.append("rain.exe")
    names.extend(["R.A.I.N.", "R.A.I.N..exe"])
    lowered = []
    for name in names:
        if name.lower() not in lowered:
            lowered.append(name.lower())
    return lowered


def _find_extracted_binary(root: Path, spec: PlatformSpec) -> Path:
    candidate_names = _candidate_binary_names(spec)
    matches: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.lower() in candidate_names:
            matches.append(path)

    if not matches:
        raise BootstrapError(f"Downloaded archive did not contain a {spec.binary_name} executable.")

    matches.sort(key=lambda item: (item.name.lower() != spec.binary_name.lower(), len(item.parts)))
    return matches[0]


def _write_release_metadata(metadata_path: Path, *, repo_slug: str, asset: ReleaseAsset, spec: PlatformSpec) -> None:
    payload = {
        "repo": repo_slug,
        "tag": asset.tag_name,
        "asset": asset.asset_name,
        "target": spec.target,
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _cached_release_matches(metadata_path: Path, *, repo_slug: str, asset: ReleaseAsset, spec: PlatformSpec) -> bool:
    if not metadata_path.exists():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    return (
        payload.get("repo") == repo_slug
        and payload.get("tag") == asset.tag_name
        and payload.get("asset") == asset.asset_name
        and payload.get("target") == spec.target
    )


def fetch_engine_binary(
    *,
    repo_root: Path,
    repo_slug: str,
    spec: PlatformSpec,
    bin_dir: Path,
    release_tag: str,
) -> Path:
    releases = _fetch_release_feed(repo_slug, release_tag)
    asset = select_release_asset(releases, spec)

    bin_dir.mkdir(parents=True, exist_ok=True)
    engine_path = bin_dir / spec.binary_name
    metadata_path = bin_dir / "rain-engine-release.json"

    if engine_path.exists() and _cached_release_matches(metadata_path, repo_slug=repo_slug, asset=asset, spec=spec):
        print(f"[bootstrap] reusing engine binary: {engine_path}")
        return engine_path

    with tempfile.TemporaryDirectory(prefix="rain-bootstrap-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        archive_path = tmp_dir / asset.asset_name
        extract_dir = tmp_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        print(f"[bootstrap] downloading {asset.asset_name} from {repo_slug}@{asset.tag_name}")
        _download_file(asset.download_url, archive_path)

        if spec.archive_ext == "zip":
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_dir)
        else:
            with tarfile.open(archive_path, "r:gz") as archive:
                archive.extractall(extract_dir)

        extracted_binary = _find_extracted_binary(extract_dir, spec)
        shutil.copy2(extracted_binary, engine_path)
        if os.name != "nt":
            current_mode = engine_path.stat().st_mode
            engine_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    _write_release_metadata(metadata_path, repo_slug=repo_slug, asset=asset, spec=spec)
    print(f"[bootstrap] installed engine binary: {engine_path}")
    return engine_path


def ensure_config_file(repo_root: Path) -> Path:
    config_path = repo_root / "config.toml"
    if config_path.exists():
        return config_path

    example_path = repo_root / "config.example.toml"
    if not example_path.exists():
        raise BootstrapError(f"Missing config template: {example_path}")

    shutil.copyfile(example_path, config_path)
    print(f"[bootstrap] created config from template: {config_path}")
    return config_path


def _replace_env_assignment(text: str, key: str, value: str) -> str:
    replacement = f"{key}={value}"
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)

    stripped = text.rstrip()
    if stripped:
        return f"{stripped}\n{replacement}\n"
    return f"{replacement}\n"


def _clear_terminal() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _prompt_for_primary_api_key() -> str:
    print("Welcome to R.A.I.N. Lab.")
    print("Paste your primary Intelligence API Key to enable hosted models.")
    print("Press Enter to stay local with Ollama and skip remote credentials.")
    print()
    return getpass.getpass("Primary Intelligence API Key: ").strip()


def _secure_env_file(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)


def ensure_env_file(repo_root: Path, *, interactive: bool) -> Path:
    env_path = repo_root / ".env"
    if env_path.exists():
        return env_path

    example_path = repo_root / ".env.example"
    template = example_path.read_text(encoding="utf-8") if example_path.exists() else ""

    _clear_terminal()
    api_key = _prompt_for_primary_api_key() if interactive else ""
    provider = "openrouter" if api_key else "ollama"

    content = template
    content = _replace_env_assignment(content, "PROVIDER", provider)
    content = _replace_env_assignment(content, "API_KEY", api_key)
    content = (
        "# Generated by bootstrap_local.py\n"
        "# Edit this file later if you want to switch providers or rotate keys.\n\n"
        f"{content.lstrip()}"
    )

    env_path.write_text(content, encoding="utf-8")
    _secure_env_file(env_path)
    print(f"[bootstrap] created environment file: {env_path}")
    return env_path


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
            "role": "Field Topographer / Theorist",
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
    interactive = not args.non_interactive and sys.stdin.isatty() and sys.stdout.isatty()

    config_path: Path | None = None
    env_path: Path | None = None
    engine_path: Path | None = None

    try:
        if not args.skip_config_init:
            config_path = ensure_config_file(repo_root)

        if not args.skip_env_setup:
            env_path = ensure_env_file(repo_root, interactive=interactive)

        if not args.skip_binary_fetch:
            release_repo = _detect_release_repo(repo_root, args.release_repo)
            platform_spec = detect_platform_spec()
            bin_dir = Path(args.bin_dir)
            if not bin_dir.is_absolute():
                bin_dir = repo_root / bin_dir
            engine_path = fetch_engine_binary(
                repo_root=repo_root,
                repo_slug=release_repo,
                spec=platform_spec,
                bin_dir=bin_dir.resolve(),
                release_tag=args.release_tag,
            )

        if not args.skip_preflight:
            _run([sys.executable, "rain_lab.py", "--mode", "preflight"], cwd=repo_root)

        if args.register_rust_agents:
            _register_rust_agents(
                repo_root=repo_root,
                rust_api_url=args.rust_api_url,
                output_path=(repo_root / args.registry_output).resolve(),
            )
    except (BootstrapError, subprocess.CalledProcessError) as exc:
        print(f"[bootstrap] error: {exc}")
        return 1

    print("\n[bootstrap] fetch-first setup complete")
    if config_path is not None:
        print(f"[bootstrap] config: {config_path}")
    if env_path is not None:
        print(f"[bootstrap] env: {env_path}")
    if engine_path is not None:
        print(f"[bootstrap] engine: {engine_path}")
    print('[bootstrap] next: uv run chat_with_james.py --greet')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
