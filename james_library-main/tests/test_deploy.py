import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import deploy


def test_run_allow_failure_ignores_called_process_error(monkeypatch):
    def _fail(cmd, check):  # noqa: ARG001
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(deploy.subprocess, "run", _fail)
    deploy._run(["launchctl", "unload", "example.plist"], dry_run=False, allow_failure=True)


def test_run_without_allow_failure_raises(monkeypatch):
    def _fail(cmd, check):  # noqa: ARG001
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(deploy.subprocess, "run", _fail)
    with pytest.raises(subprocess.CalledProcessError):
        deploy._run(["launchctl", "unload", "example.plist"], dry_run=False, allow_failure=False)
