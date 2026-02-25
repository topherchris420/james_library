import sys
from pathlib import Path

# Ensure the repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rain_lab as rain_launcher
from rain_lab import (
    build_command,
    build_godot_bridge_command,
    build_godot_client_command,
    parse_args,
    resolve_launch_plan,
)


def test_parse_defaults():
    args, _ = parse_args([])
    assert args.mode == "chat"
    assert args.topic is None
    assert args.ui == "auto"


def test_parse_rlm_mode():
    args, _ = parse_args(["--mode", "rlm", "--topic", "test"])
    assert args.mode == "rlm"
    assert args.topic == "test"


def test_parse_godot_mode_defaults():
    args, _ = parse_args(["--mode", "godot", "--topic", "demo"])
    assert args.mode == "godot"
    assert args.ui == "auto"
    assert args.godot_events_log.endswith("meeting_archives/godot_events.jsonl")
    assert args.godot_ws_host == "127.0.0.1"
    assert args.godot_ws_port == 8765


def test_parse_ui_env_invalid_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("RAIN_UI_MODE", "invalid")
    args, _ = parse_args(["--mode", "chat", "--topic", "demo"])
    assert args.ui == "auto"


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


def test_build_godot_client_command(repo_root, monkeypatch):
    args, _ = parse_args(["--mode", "chat", "--topic", "x"])

    def fake_which(name: str) -> str | None:
        if name == "godot4":
            return r"C:\Tools\Godot\godot4.exe"
        return None

    monkeypatch.setattr(rain_launcher.shutil, "which", fake_which)
    cmd = build_godot_client_command(args, repo_root)
    assert cmd is not None
    assert cmd[0].endswith("godot4.exe")
    assert cmd[1] == "--path"
    assert cmd[2].endswith("godot_client")


def test_resolve_launch_plan_chat_auto_prefers_godot(repo_root, monkeypatch):
    args, _ = parse_args(["--mode", "chat", "--topic", "x"])
    expected_client_cmd = ["godot4", "--path", str(repo_root / "godot_client")]
    monkeypatch.setattr(
        rain_launcher,
        "build_godot_client_command",
        lambda _args, _root: expected_client_cmd,
    )

    plan = resolve_launch_plan(args, repo_root)
    assert plan.effective_mode == "godot"
    assert plan.launch_bridge is True
    assert plan.launch_godot_client is True
    assert plan.godot_client_cmd == expected_client_cmd


def test_resolve_launch_plan_chat_auto_falls_back_without_client(repo_root, monkeypatch):
    args, _ = parse_args(["--mode", "chat", "--topic", "x"])
    monkeypatch.setattr(rain_launcher, "build_godot_client_command", lambda _args, _root: None)
    plan = resolve_launch_plan(args, repo_root)
    assert plan.effective_mode == "chat"
    assert plan.launch_bridge is False
    assert plan.launch_godot_client is False
    assert plan.godot_client_cmd is None


def test_resolve_launch_plan_chat_ui_on_requires_stack(repo_root, monkeypatch):
    args, _ = parse_args(["--mode", "chat", "--topic", "x", "--ui", "on"])
    monkeypatch.setattr(rain_launcher, "build_godot_client_command", lambda _args, _root: None)
    try:
        resolve_launch_plan(args, repo_root)
    except RuntimeError as exc:
        assert "UI mode 'on' requires" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when ui=on has no client")


def test_resolve_launch_plan_chat_ui_off_forces_cli(repo_root):
    args, _ = parse_args(["--mode", "chat", "--topic", "x", "--ui", "off"])
    plan = resolve_launch_plan(args, repo_root)
    assert plan.effective_mode == "chat"
    assert plan.launch_bridge is False
    assert plan.launch_godot_client is False


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
