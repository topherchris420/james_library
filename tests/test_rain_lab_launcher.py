import sys
from pathlib import Path

# Ensure the repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rain_lab import parse_args, build_command


def test_parse_defaults():
    args, pt = parse_args([])
    assert args.mode == "chat"
    assert args.topic is None


def test_parse_rlm_mode():
    args, pt = parse_args(["--mode", "rlm", "--topic", "test"])
    assert args.mode == "rlm"
    assert args.topic == "test"


def test_build_command_chat(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "x"])
    cmd = build_command(args, pt, repo_root)
    assert "chat_with_james.py" in cmd[1]


def test_build_command_rlm(repo_root):
    args, pt = parse_args(["--mode", "rlm", "--topic", "y"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_meeting.py" in cmd[1]


def test_build_command_hello_os(repo_root):
    args, pt = parse_args(["--mode", "hello-os"])
    cmd = build_command(args, pt, repo_root)
    assert "hello_os_executable.py" in cmd[1]


def test_passthrough_split():
    args, pt = parse_args(["--mode", "chat", "--", "--extra"])
    assert pt == ["--extra"]


def test_turns_forwarded(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "t", "--turns", "5"])
    cmd = build_command(args, pt, repo_root)
    assert "--max-turns" in cmd
    assert "5" in cmd

def test_build_command_chat_falls_back_to_legacy(repo_root, monkeypatch):
    args, pt = parse_args(["--mode", "chat", "--topic", "x"])
    monkeypatch.setattr(Path, "exists", lambda self: False if self.name == "chat_with_james.py" else Path.__dict__["exists"](self))
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_meeting_chat_version.py" in cmd[1]
