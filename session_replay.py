"""Backward-compatible wrapper for :mod:`james_library.utilities.session_replay`."""

from james_library.utilities.session_replay import main


if __name__ == "__main__":
    raise SystemExit(main())
