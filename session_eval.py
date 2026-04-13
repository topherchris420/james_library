"""Backward-compatible wrapper for :mod:`james_library.utilities.session_eval`."""

from james_library.utilities.session_eval import main


if __name__ == "__main__":
    raise SystemExit(main())
