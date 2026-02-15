import subprocess
import sys


def test_preflight_does_not_crash(repo_root):
    """Preflight must exit cleanly (0 = pass, 1 = some checks failed) — never crash."""
    result = subprocess.run(
        [sys.executable, str(repo_root / "rain_preflight_check.py")],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            "PATH": subprocess.os.environ.get("PATH", ""),
            "JAMES_LIBRARY_PATH": str(repo_root),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
    )
    assert result.returncode in (0, 1), (
        f"Preflight crashed (rc={result.returncode}):\n{result.stderr}"
    )


def test_preflight_uses_env_var(repo_root):
    """LIBRARY_PATH should come from JAMES_LIBRARY_PATH, not a hardcoded string."""
    source = (repo_root / "rain_preflight_check.py").read_text(encoding="utf-8")
    assert "JAMES_LIBRARY_PATH" in source
    assert r"C:\Users" not in source
