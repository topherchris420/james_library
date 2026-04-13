"""Reusable Python utility modules for R.A.I.N. Lab.

The utility package exposes a broad set of optional helpers. Importing every
submodule eagerly makes unrelated callers fail when one legacy utility has
extra runtime dependencies, so package attributes are resolved lazily.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_UTILITY_MODULES = [
    "circuit_breaker",
    "context_manager",
    "cost_monitor",
    "graph_bridge",
    "hypothesis_tree",
    "library_compiler",
    "log_manager",
    "memory",
    "prefetch",
    "rain_metrics",
    "rain_unique",
    "rich_ui",
    "session_eval",
    "session_artifact",
    "session_replay",
    "memory_governance",
    "memory_remediation",
    "tools",
    "truth_layer",
]

__all__ = _UTILITY_MODULES


def __getattr__(name: str) -> ModuleType:
    """Load utility modules on demand."""
    if name in _UTILITY_MODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
