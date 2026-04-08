from __future__ import annotations

import subprocess
import sys


def test_context_and_cost_utilities_pass_mypy(repo_root) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "james_library/utilities/context_manager.py",
            "james_library/utilities/cost_monitor.py",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        "Expected mypy to pass for the new utility modules.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
