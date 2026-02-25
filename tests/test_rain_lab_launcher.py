import sys
from pathlib import Path

# Ensure the repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rain_lab import build_command, parse_args


def test_parse_defaults():
    args, _ = parse_args([])
    assert args.mode == "chat"
    assert args.topic is None


def test_parse_rlm_mode():
    args, _ = parse_args(["--mode", "rlm", "--topic", "test"])
    assert args.mode == "rlm"
    assert args.topic == "test"


def test_build_command_chat(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "x"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_runtime.py" in cmd[1]


def test_build_command_rlm(repo_root):
    args, pt = parse_args(["--mode", "rlm", "--topic", "y"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_meeting.py" in cmd[1]


def test_build_command_hello_os(repo_root):
    args, pt = parse_args(["--mode", "hello-os"])
    cmd = build_command(args, pt, repo_root)
    assert "hello_os_executable.py" in cmd[1]


def test_passthrough_split():
    _, pt = parse_args(["--mode", "chat", "--", "--extra"])
    assert pt == ["--extra"]


def test_build_command_chat_requires_runtime_script(repo_root, monkeypatch):
    args, pt = parse_args(["--mode", "chat", "--topic", "x"])
    original_exists = Path.exists

    def fake_exists(path_obj: Path) -> bool:
        if path_obj.name == "rain_lab_runtime.py":
            return False
        return original_exists(path_obj)

    monkeypatch.setattr(Path, "exists", fake_exists)
    try:
        build_command(args, pt, repo_root)
    except FileNotFoundError as exc:
        assert "rain_lab_runtime.py" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError when rain_lab_runtime.py is missing")


def test_build_command_compile(repo_root):
    args, pt = parse_args(["--mode", "compile"])
    cmd = build_command(args, pt, repo_root)
    assert "library_compiler.py" in cmd[1]
    assert "--library" in cmd


def test_build_command_preflight(repo_root):
    args, pt = parse_args(["--mode", "preflight"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_preflight_check.py" in cmd[1]


def test_build_command_backup(repo_root):
    args, pt = parse_args(["--mode", "backup"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_backup.py" in cmd[1]


def test_build_command_first_run(repo_root):
    args, pt = parse_args(["--mode", "first-run", "--topic", "hello"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_first_run.py" in cmd[1]
    assert "--topic" in cmd
    assert "hello" in cmd
