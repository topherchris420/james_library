"""Minimal local fallback for python-dotenv.

This keeps rlm importable in environments where python-dotenv is absent.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(dotenv_path: str | os.PathLike[str] | None = None, override: bool = False) -> bool:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Returns True when a dotenv file was found and parsed, otherwise False.
    """

    path = Path(dotenv_path) if dotenv_path is not None else Path.cwd() / ".env"
    if not path.exists() or not path.is_file():
        return False

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if not key:
            continue
        if key in os.environ and not override:
            continue
        os.environ[key] = value

    return True
