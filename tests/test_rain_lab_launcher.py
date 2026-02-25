import sys
from pathlib import Path

# Ensure the repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rain_lab import build_command, build_godot_bridge_command, parse_args


def test_parse_defaults():
    args, _ = parse_args([])
    assert args.mode == "chat"
    assert args.topic is None


def test_parse_rlm_mode():
    args, _ = parse_args(["--mode", "rlm", "--topic", "test"])
    assert args.mode == "rlm"
    assert args.topic == "test"


def test_parse_godot_mode_defaults():
    args, _ = parse_args(["--mode", "godot", "--topic", "demo"])
    assert args.mode == "godot"
    assert args.godot_events_log.endswith("meeting_archives/godot_events.jsonl")
    assert args.godot_ws_host == "127.0.0.1"
    assert args.godot_ws_port == 8765


def test_parse_config_path():
    args, _ = parse_args(["--mode", "chat", "--topic", "x", "--config", "runtime.toml"])
    assert args.config == "runtime.toml"


def test_build_command_chat(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "x"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_runtime.py" in cmd[1]


def test_build_command_chat_with_config(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "x", "--config", "runtime.toml"])
    cmd = build_command(args, pt, repo_root)
    assert "--config" in cmd
    assert "runtime.toml" in cmd


def test_build_command_chat_forwards_runtime_flags(repo_root):
    args, pt = parse_args(
        [
            "--mode",
            "chat",
            "--topic",
            "x",
            "--turns",
            "1",
            "--timeout",
            "30",
            "--recursive-depth",
            "4",
        ]
    )
    cmd = build_command(args, pt, repo_root)
    assert "--max-turns" in cmd and "1" in cmd
    assert "--timeout" in cmd and "30.0" in cmd
    assert "--recursive-depth" in cmd and "4" in cmd


def test_build_command_chat_no_recursive_flag(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "x", "--no-recursive-intellect", "--recursive-depth", "9"])
    cmd = build_command(args, pt, repo_root)
    assert "--no-recursive-intellect" in cmd
    assert "--recursive-depth" not in cmd


def test_build_command_godot(repo_root):
    args, pt = parse_args(["--mode", "godot", "--topic", "x", "--turns", "2", "--timeout", "30"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_meeting_chat_version.py" in cmd[1]
    assert "--emit-visual-events" in cmd
    assert "--visual-events-log" in cmd
    assert "--tts-audio-dir" in cmd
    assert "--max-turns" in cmd and "2" in cmd
    assert "--timeout" in cmd and "30.0" in cmd


def test_build_godot_bridge_command(repo_root):
    args, _ = parse_args(
        [
            "--mode",
            "godot",
            "--topic",
            "x",
            "--godot-events-log",
            "meeting_archives/custom_events.jsonl",
            "--godot-ws-host",
            "0.0.0.0",
            "--godot-ws-port",
            "9000",
            "--godot-bridge-poll-interval",
            "0.25",
            "--godot-replay-existing",
        ]
    )
    cmd = build_godot_bridge_command(args, repo_root)
    assert "godot_event_bridge.py" in cmd[1]
    assert "--events-file" in cmd and "meeting_archives/custom_events.jsonl" in cmd
    assert "--host" in cmd and "0.0.0.0" in cmd
    assert "--port" in cmd and "9000" in cmd
    assert "--poll-interval" in cmd and "0.25" in cmd
    assert "--replay-existing" in cmd


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
