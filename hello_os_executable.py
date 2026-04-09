"""Backward-compatible wrapper for :mod:`data.hello_os.hello_os_executable`."""

from __future__ import annotations

import sys

from data.hello_os import hello_os_executable as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})


def main(argv: list[str] | None = None) -> int:
    """Delegate command execution to the canonical implementation."""
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
