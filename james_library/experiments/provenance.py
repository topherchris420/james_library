"""Run provenance capture and secret redaction.

Captured: git commit/branch/dirty state, Python and OS identity, declared
dependency versions, and SHA-256 of the files under test. Deliberately not
captured: environment variables, hostname, user name, absolute home paths.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REDACTED = "[REDACTED]"

_CREDENTIAL_FIELD = re.compile(
    r"(secret|token|passw|api[_-]?key|apikey|authorization|cookie|credential|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
_CREDENTIAL_FORMATS = {
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "github_token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    "bearer_token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}


def credential_formats_in(text: str) -> bool:
    """True when ``text`` contains something shaped like a known credential format."""
    return any(pattern.search(text) for pattern in _CREDENTIAL_FORMATS.values())


def redact(value: Any, _key: str | None = None) -> Any:
    """Return a copy with secret-looking strings masked.

    A string under a secret-like key (``api_key``, ``authorization`` ...) is
    masked entirely. Numbers are kept, so ``max_tokens: 512`` survives.
    Any string matching a known credential format is masked in place.
    """
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, _key) for v in value]
    if isinstance(value, str):
        if _key is not None and _CREDENTIAL_FIELD.search(_key) and value:
            return REDACTED
        for pattern in _CREDENTIAL_FORMATS.values():
            value = pattern.sub(REDACTED, value)
        return value
    return value


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_state(excluded: list[Path] | None = None) -> dict[str, Any]:
    """Commit, branch and dirty state of the code checkout.

    Registry data (``excluded``) is ignored for the dirty check: recording a
    run must not make the next run look like it came from modified code.
    """
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return {"commit": None, "branch": None, "dirty": None, "changed_paths": None,
                "note": "git metadata unavailable; source revision unknown"}
    pathspec = ["."]
    for path in excluded or []:
        try:
            pathspec.append(f":(exclude){path.resolve().relative_to(REPO_ROOT).as_posix()}")
        except ValueError:
            continue
    status = _git("status", "--porcelain", "--untracked-files=normal", "--", *pathspec)
    changed = [line for line in (status or "").splitlines() if line.strip()]
    return {
        "commit": commit,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(changed) if status is not None else None,
        "changed_paths": len(changed) if status is not None else None,
        "note": None,
    }


def environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def dependency_versions(names: list[str]) -> dict[str, str]:
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def hash_repo_files(paths: list[str]) -> list[dict[str, Any]]:
    """SHA-256 of repository files under test; survives squash merges that drop commit SHAs."""
    rows = []
    root = REPO_ROOT.resolve()
    for rel in paths:
        target = (REPO_ROOT / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            rows.append({"path": rel, "sha256": None, "note": "outside repository; not read"})
            continue
        if not target.is_file():
            rows.append({"path": rel, "sha256": None, "note": "missing"})
            continue
        rows.append({"path": rel, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "note": None})
    return rows


def repo_relative(path: str | Path | None) -> str | None:
    """Repository-relative form of a path; never leaks an absolute home directory."""
    if path is None:
        return None
    try:
        return Path(path).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name
