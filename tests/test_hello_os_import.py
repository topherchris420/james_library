"""Tests for the hello_os package decomposition.

Validates that:
- The package imports cleanly
- All expected public symbols are present
- Each module is under 500 lines
- The original flat file's `inspect` still works via hello_os_executable
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HELLO_OS_PKG = REPO_ROOT / "hello_os"
MAX_LINES = 500


# ------------------------------------------------------------------
# 1. Package import
# ------------------------------------------------------------------


def test_hello_os_package_imports():
    """The hello_os package must import without error."""
    import hello_os

    assert hasattr(hello_os, "__version__") or callable(
        getattr(hello_os, "main", None)
    )


def test_hello_os_has_version():
    import hello_os

    assert hello_os.__version__


def test_hello_os_core_symbols():
    """Core public API symbols should be accessible from the top-level package."""
    import hello_os

    for name in (
        "CognitiveState",
        "CSLOperator",
        "Source",
        "Triad",
        "Recursion",
        "Memory",
        "Compression",
        "Loop",
        "Time",
        "Thread",
        "Activation",
        "Synthesis",
        "OperatorRegistry",
        "CSLSentence",
        "CognitiveScroll",
        "demonstrate_csl",
        "normalize",
        "to_numpy",
        "to_gpu",
        "GPU_AVAILABLE",
    ):
        assert hasattr(hello_os, name), f"Missing public symbol: {name}"


# ------------------------------------------------------------------
# 2. Sub-module imports
# ------------------------------------------------------------------


def test_submodule_symbols():
    from hello_os import symbols

    assert hasattr(symbols, "GPU_AVAILABLE")


def test_submodule_utils():
    from hello_os import utils

    assert callable(utils.normalize)


def test_submodule_core():
    from hello_os import core

    assert hasattr(core, "CSLSentence")


def test_submodule_scroll():
    from hello_os import scroll

    assert callable(scroll.demonstrate_csl)
    assert hasattr(scroll, "CognitiveScroll")


def test_submodule_geometry():
    from hello_os import geometry

    assert callable(geometry.generate_quasicrystal)


def test_submodule_resonance():
    from hello_os import resonance

    assert callable(resonance.skin_depth)


# ------------------------------------------------------------------
# 3. Module size constraint — every .py in hello_os/ under 500 lines
# ------------------------------------------------------------------


def test_all_modules_under_500_lines():
    for py_file in HELLO_OS_PKG.glob("*.py"):
        line_count = len(py_file.read_text(encoding="utf-8").splitlines())
        assert line_count <= MAX_LINES, (
            f"{py_file.name} has {line_count} lines (max {MAX_LINES})"
        )


# ------------------------------------------------------------------
# 4. hello_os_executable.py still works with the package directory
# ------------------------------------------------------------------


def test_executable_inspect_with_package():
    """hello_os_executable.py inspect should still work after decomposition."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hello_os_executable.py"), "inspect"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"inspect failed:\n{result.stderr}"
    data = json.loads(result.stdout)
    assert data["lines"] > 0
    assert data["functions"] > 0
