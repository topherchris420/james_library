"""Background services and external integrations for R.A.I.N. Lab.

Some service modules depend on optional local AI stacks that are not required by
all callers. Resolve service attributes lazily so importing a lightweight
service does not eagerly pull in heavyweight optional dependencies.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_SERVICE_MODULES = [
    "experiment_protocol",
    "external_integrations",
    "kairos_dreamer",
    "openclaw_service",
    "tts_module",
    "voice_activation",
]

__all__ = _SERVICE_MODULES


def __getattr__(name: str) -> ModuleType:
    """Load service modules on demand."""
    if name in _SERVICE_MODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
