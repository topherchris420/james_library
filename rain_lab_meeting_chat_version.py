"""
R.A.I.N. LAB — backward-compatible shim.

All logic now lives in the ``rain_lab_chat`` package.
This file re-exports every public symbol so that existing imports
(``from rain_lab_meeting_chat_version import Config``) continue to work.
"""

# Re-export everything from the package
from rain_lab_chat import *  # noqa: F401,F403

# Symbols that __all__ doesn't cover but tests import directly
from rain_lab_chat._sanitize import (  # noqa: F401
    sanitize_text,
    RE_QUOTE_DOUBLE,
    RE_QUOTE_SINGLE,
    RE_CORRUPTION_CAPS,
    RE_WEB_SEARCH_COMMAND,
    RE_CORRUPTION_PATTERNS,
)
from rain_lab_chat.config import (  # noqa: F401
    Config,
    DEFAULT_LIBRARY_PATH,
    DEFAULT_MODEL_NAME,
    DEFAULT_RECURSIVE_LIBRARY_SCAN,
    DEFAULT_LIBRARY_EXCLUDE_DIRS,
    _parse_env_csv,
)
from rain_lab_chat.web_search import DDG_AVAILABLE, DDG_PACKAGE  # noqa: F401
from rain_lab_chat.cli import main, parse_args  # noqa: F401

if __name__ == "__main__":
    main()
