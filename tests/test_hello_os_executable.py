import json
import subprocess
import sys


def test_inspect_runs(repo_root):
    """hello_os_executable.py inspect must produce valid JSON."""
    result = subprocess.run(
        [sys.executable, str(repo_root / "hello_os_executable.py"), "inspect"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"inspect failed:\n{result.stderr}"
    data = json.loads(result.stdout)
    assert "lines" in data
    assert data["lines"] > 0


def test_inspect_reports_shell_magic(repo_root):
    """hello_os.py (Colab export) contains !pip lines — inspector should count them."""
    result = subprocess.run(
        [sys.executable, str(repo_root / "hello_os_executable.py"), "inspect"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    data = json.loads(result.stdout)
    assert data.get("shell_magic_lines", 0) > 0


def test_extract_csl(repo_root, tmp_path):
    """extract-csl should produce a non-empty Python file."""
    out_file = tmp_path / "csl_module.py"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "hello_os_executable.py"),
            "extract-csl",
            "--output",
            str(out_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"extract-csl failed:\n{result.stderr}"
    assert out_file.exists()
    assert out_file.stat().st_size > 0
