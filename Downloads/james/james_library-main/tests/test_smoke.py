"""Smoke tests for top-level wrappers and packaged Python modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

ROOT_SCRIPTS = [
    "rain_lab.py",
    "meeting_workflow.py",
    "swarm_orchestrator.py",
    "rain_preflight_check.py",
    "rain_first_run.py",
    "deploy.py",
    "openclaw_service.py",
    "external_integrations.py",
    "tools.py",
    "truth_layer.py",
    "library_compiler.py",
]

PACKAGE_MODULES = [
    "james_library.launcher.rain_lab",
    "james_library.launcher.meeting_workflow",
    "james_library.launcher.swarm_orchestrator",
    "james_library.bootstrap.rain_preflight_check",
    "james_library.bootstrap.rain_first_run",
    "james_library.bootstrap.deploy",
    "james_library.services.openclaw_service",
    "james_library.services.external_integrations",
    "james_library.utilities.tools",
    "james_library.utilities.truth_layer",
    "james_library.utilities.library_compiler",
]


def _compile_check(path: Path) -> None:
    source = path.read_text(encoding="utf-8", errors="replace")
    compile(source, str(path), "exec")


class TestSyntax:
    @pytest.mark.parametrize("script_name", ROOT_SCRIPTS)
    def test_root_wrapper_compiles(self, script_name: str) -> None:
        _compile_check(REPO_ROOT / script_name)

    @pytest.mark.parametrize("module_name", PACKAGE_MODULES)
    def test_packaged_module_compiles(self, module_name: str) -> None:
        module_path = REPO_ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
        _compile_check(module_path)


class TestImport:
    @staticmethod
    def _import_module(module_name: str) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib, os, sys; "
                    f"sys.path.insert(0, {str(REPO_ROOT)!r}); "
                    "os.environ.setdefault('JAMES_LIBRARY_PATH', "
                    f"{str(REPO_ROOT)!r}); "
                    f"importlib.import_module({module_name!r})"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Module {module_name} failed to import:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    @pytest.mark.parametrize(
        "module_name",
        [
            "james_library.launcher.rain_lab",
            "james_library.utilities.library_compiler",
            "james_library.services.external_integrations",
        ],
    )
    def test_packaged_module_imports(self, module_name: str) -> None:
        self._import_module(module_name)


class TestPreflightPath:
    def test_no_hardcoded_windows_path(self) -> None:
        source = (REPO_ROOT / "james_library" / "bootstrap" / "rain_preflight_check.py").read_text(
            encoding="utf-8"
        )
        assert r"C:\Users" not in source

    def test_uses_env_var(self) -> None:
        source = (REPO_ROOT / "james_library" / "bootstrap" / "rain_preflight_check.py").read_text(
            encoding="utf-8"
        )
        assert "JAMES_LIBRARY_PATH" in source
