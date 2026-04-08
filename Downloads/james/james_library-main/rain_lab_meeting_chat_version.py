"""
R.A.I.N. LAB - RESEARCH

Thin backward-compatibility facade.  All implementation has moved to the
``rain_lab`` package.  This file re-exports every public symbol so that
existing scripts (``python rain_lab_meeting_chat_version.py``) and tests
that import from this module continue to work unchanged.
"""

# Re-export everything from the package so existing
# ``from rain_lab_meeting_chat_version import X`` works.
from rain_lab import *  # noqa: F401,F403
from rain_lab import main

if __name__ == "__main__":
    main()
