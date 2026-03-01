# Tests for R.A.I.N. repo — smoke-test that every top-level script
# can at least be *parsed and imported* without raising SyntaxError
# or crashing at module level on a headless Linux CI box.

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _compile_check(script: Path) -> None:
    """Compile the file to bytecode — catches SyntaxError early."""
    source = script.read_text(encoding="utf-8", errors="replace")
    compile(source, str(script), "exec")


# ------------------------------------------------------------------
# 1. Syntax / compile checks for every .py at the repo root
# ------------------------------------------------------------------
class TestSyntax:
    """Every top-level .py file must be valid Python."""

    def test_rain_preflight_check_compiles(self):
        _compile_check(REPO_ROOT / "rain_preflight_check.py")

    def test_rain_lab_meeting_compiles(self):
        _compile_check(REPO_ROOT / "rain_lab_meeting.py")

    def test_rain_lab_meeting_chat_version_compiles(self):
        _compile_check(REPO_ROOT / "rain_lab_meeting_chat_version.py")

    def test_rain_lab_compiles(self):
        _compile_check(REPO_ROOT / "rain_lab.py")

    def test_chat_with_james_compiles(self):
        _compile_check(REPO_ROOT / "chat_with_james.py")

    def test_hello_os_executable_compiles(self):
        _compile_check(REPO_ROOT / "hello_os_executable.py")

    def test_hello_os_compiles(self):
        # hello_os.py is a Colab export with !pip shell magic lines;
        # it is valid for Colab/IPython but not plain CPython.
        pytest.skip("hello_os.py is a Colab notebook export with shell magic")


# ------------------------------------------------------------------
# 2. Importability — scripts that guard heavy deps behind
#    `--help` / try-except should survive a subprocess import.
# ------------------------------------------------------------------
class TestImport:
    """Verify scripts don't crash on import in a subprocess."""

    @staticmethod
    def _import_in_subprocess(script_name: str) -> None:
        """Import *script_name* (stem) in a fresh subprocess.

        We set JAMES_LIBRARY_PATH to the repo root so path probing
        succeeds on Linux CI.
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys, os; "
                    f"sys.path.insert(0, {str(REPO_ROOT)!r}); "
                    "os.environ.setdefault('JAMES_LIBRARY_PATH', "
                    f"{str(REPO_ROOT)!r}); "
                    f"compile(open({str(REPO_ROOT / (script_name + '.py'))!r}, "
                    "encoding='utf-8', errors='replace').read(), "
                    f"'{script_name}.py', 'exec')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Script {script_name}.py failed to compile:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_rain_lab_imports(self):
        self._import_in_subprocess("rain_lab")

    def test_hello_os_executable_imports(self):
        self._import_in_subprocess("hello_os_executable")


# ------------------------------------------------------------------
# 3. Preflight path parameterisation — the critical CI-blocker fix
# ------------------------------------------------------------------
class TestPreflightPath:
    """rain_preflight_check.py must NOT contain a hardcoded Windows path."""

    def test_no_hardcoded_windows_path(self):
        source = (REPO_ROOT / "rain_preflight_check.py").read_text(
            encoding="utf-8"
        )
        assert r"C:\Users" not in source, (
            "rain_preflight_check.py still contains a hardcoded "
            "Windows path — parameterise via JAMES_LIBRARY_PATH"
        )

    def test_uses_env_var(self):
        source = (REPO_ROOT / "rain_preflight_check.py").read_text(
            encoding="utf-8"
        )
        assert "JAMES_LIBRARY_PATH" in source, (
            "rain_preflight_check.py should read JAMES_LIBRARY_PATH "
            "from the environment"
        )
