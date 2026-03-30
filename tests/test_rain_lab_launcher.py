from pathlib import Path

import james_library.launcher.rain_lab as rain_launcher
from james_library.launcher.rain_lab import (
    _apply_beginner_shortcut,
    _build_follow_up_moves,
    _build_demo_session_markdown,
    _choose_beginner_mode,
    _prepare_beginner_args,
    _prepare_demo_args,
    _build_sidecar_specs,
    _resolve_launcher_log_path,
    _run_demo_session,
    _write_beginner_share_card,
    _write_beginner_showcase_page,
    build_command,
    build_godot_bridge_command,
    build_godot_client_command,
    main,
    parse_args,
    resolve_launch_plan,
)


def test_parse_defaults():
    args, _ = parse_args([])
    assert args.mode == "chat"
    assert args.topic is None
    assert args.ui == "off"
    assert args.restart_sidecars is True
    assert args.max_sidecar_restarts == 2
    assert args.sidecar_restart_backoff == 0.5
    assert args.sidecar_poll_interval == 0.25
    assert args.launcher_log.endswith("meeting_archives/launcher_events.jsonl")


def test_parse_rlm_mode():
    args, _ = parse_args(["--mode", "rlm", "--topic", "test"])
    assert args.mode == "rlm"
    assert args.topic == "test"


def test_parse_beginner_mode():
    args, _ = parse_args(["--mode", "beginner", "--topic", "make this simple"])
    assert args.mode == "beginner"
    assert args.topic == "make this simple"


def test_parse_demo_mode_with_preset():
    args, _ = parse_args(["--mode", "demo", "--preset", "idea-roast"])
    assert args.mode == "demo"
    assert args.preset == "idea-roast"


def test_parse_godot_mode_defaults():
    args, _ = parse_args(["--mode", "godot", "--topic", "demo"])
    assert args.mode == "godot"
    assert args.ui == "off"
    assert args.godot_events_log.endswith("meeting_archives/godot_events.jsonl")
    assert args.godot_ws_host == "127.0.0.1"
    assert args.godot_ws_port == 8765


def test_parse_ui_env_invalid_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("RAIN_UI_MODE", "invalid")
    args, _ = parse_args(["--mode", "chat", "--topic", "demo"])
    assert args.ui == "off"


def test_parse_supervision_env(monkeypatch):
    monkeypatch.setenv("RAIN_RESTART_SIDECARS", "0")
    monkeypatch.setenv("RAIN_MAX_SIDECAR_RESTARTS", "5")
    monkeypatch.setenv("RAIN_SIDECAR_RESTART_BACKOFF", "1.25")
    monkeypatch.setenv("RAIN_SIDECAR_POLL_INTERVAL", "0.4")
    args, _ = parse_args(["--mode", "chat", "--topic", "demo"])
    assert args.restart_sidecars is False
    assert args.max_sidecar_restarts == 5
    assert args.sidecar_restart_backoff == 1.25
    assert args.sidecar_poll_interval == 0.4


def test_resolve_launcher_log_path(repo_root):
    args, _ = parse_args(
        [
            "--mode",
            "chat",
            "--topic",
            "x",
            "--library",
            str(repo_root),
            "--launcher-log",
            "meeting_archives/custom_launcher_events.jsonl",
        ]
    )
    log_path = _resolve_launcher_log_path(args, repo_root)
    assert log_path == (repo_root / "meeting_archives" / "custom_launcher_events.jsonl").resolve()


def test_resolve_launcher_log_path_disabled(repo_root):
    args, _ = parse_args(["--mode", "chat", "--topic", "x", "--no-launcher-log"])
    assert _resolve_launcher_log_path(args, repo_root) is None


def test_parse_config_path():
    args, _ = parse_args(["--mode", "chat", "--topic", "x", "--config", "runtime.toml"])
    assert args.config == "runtime.toml"


def test_build_command_chat(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "x"])
    cmd = build_command(args, pt, repo_root)
    assert "rain_lab_meeting_chat_version.py" in cmd[1]


def test_build_command_chat_with_config(repo_root):
    args, pt = parse_args(["--mode", "chat", "--topic", "x", "--config", "runtime.toml"])
    cmd = build_command(args, pt, repo_root)
    assert "--config" not in cmd
    assert "runtime.toml" not in cmd


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
    assert "--visual-events-host" in cmd
    assert "--visual-events-port" in cmd
    assert "--tts-audio-dir" in cmd
    assert "--max-turns" in cmd and "2" in cmd
    assert "--timeout" in cmd and "30.0" in cmd


def test_build_godot_bridge_command_returns_none(repo_root):
    """Bridge is now embedded in the main process; function returns None."""
    args, _ = parse_args(
        [
            "--mode",
            "godot",
            "--topic",
            "x",
            "--godot-ws-host",
            "0.0.0.0",
            "--godot-ws-port",
            "9000",
        ]
    )
    result = build_godot_bridge_command(args, repo_root)
    assert result is None


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
    args, _ = parse_args(["--mode", "chat", "--ui", "auto", "--topic", "x"])
    expected_client_cmd = ["godot4", "--path", str(repo_root / "godot_client")]
    monkeypatch.setattr(
        rain_launcher,
        "build_godot_client_command",
        lambda _args, _root: expected_client_cmd,
    )

    plan = resolve_launch_plan(args, repo_root)
    assert plan.effective_mode == "godot"
    assert plan.launch_godot_client is True
    assert plan.godot_client_cmd == expected_client_cmd


def test_resolve_launch_plan_chat_auto_falls_back_without_client(repo_root, monkeypatch):
    args, _ = parse_args(["--mode", "chat", "--topic", "x"])
    monkeypatch.setattr(rain_launcher, "build_godot_client_command", lambda _args, _root: None)
    plan = resolve_launch_plan(args, repo_root)
    assert plan.effective_mode == "chat"
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
    assert plan.launch_godot_client is False


def test_build_sidecar_specs_strict_ui(repo_root):
    args, _ = parse_args(["--mode", "chat", "--topic", "x", "--ui", "on"])
    plan = rain_launcher.LaunchPlan(
        effective_mode="godot",
        launch_godot_client=True,
        godot_client_cmd=["godot4", "--path", str(repo_root / "godot_client")],
    )
    specs = _build_sidecar_specs(args, plan)
    assert len(specs) == 1
    assert specs[0].name == "Godot avatar client"
    assert specs[0].critical is True


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


def test_build_command_chat_requires_meeting_script(repo_root, monkeypatch):
    args, pt = parse_args(["--mode", "chat", "--topic", "x"])
    original_exists = Path.exists

    def fake_exists(path_obj: Path) -> bool:
        if path_obj.name == "rain_lab_meeting_chat_version.py":
            return False
        return original_exists(path_obj)

    monkeypatch.setattr(Path, "exists", fake_exists)
    try:
        build_command(args, pt, repo_root)
    except FileNotFoundError as exc:
        assert "rain_lab_meeting_chat_version.py" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError when rain_lab_meeting_chat_version.py is missing")


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


def test_choose_beginner_mode_prefers_chat_for_normal_prompt():
    assert _choose_beginner_mode("Explain resonance simply") == "chat"


def test_choose_beginner_mode_prefers_rlm_for_debate_prompt():
    assert _choose_beginner_mode("Debate two startup ideas vs each other") == "rlm"


def test_apply_beginner_shortcut_routes_presets_and_demo():
    assert _apply_beginner_shortcut("1") == ("startup-debate", None, False)
    assert _apply_beginner_shortcut("4") == (None, None, True)
    assert _apply_beginner_shortcut("custom topic") == (None, "custom topic", False)


def test_prepare_beginner_args_enables_auto_ui_and_routes_chat():
    args, _ = parse_args(["--mode", "beginner", "--topic", "Explain this clearly"])
    prepared = _prepare_beginner_args(args)
    assert prepared.mode == "chat"
    assert prepared.ui == "auto"


def test_prepare_beginner_args_keeps_explicit_ui():
    args, _ = parse_args(["--mode", "beginner", "--topic", "Explain this clearly", "--ui", "off"])
    prepared = _prepare_beginner_args(args, ui_was_explicit=True)
    assert prepared.mode == "chat"
    assert prepared.ui == "off"


def test_prepare_beginner_args_routes_debate_with_turn_budget():
    args, _ = parse_args(["--mode", "beginner", "--topic", "Compare solar vs wind for my town"])
    prepared = _prepare_beginner_args(args)
    assert prepared.mode == "rlm"
    assert prepared.turns == 4


def test_prepare_beginner_args_uses_preset_template():
    args, _ = parse_args(["--mode", "beginner", "--preset", "idea-roast"])
    prepared = _prepare_beginner_args(args)
    assert prepared.mode == "chat"
    assert prepared.display_topic == "a social app for roommates who never answer texts"
    assert "Roast this idea with wit" in prepared.topic


def test_prepare_demo_args_sets_default_preset_and_topic():
    args, _ = parse_args(["--mode", "demo"])
    prepared = _prepare_demo_args(args)
    assert prepared.mode == "demo"
    assert prepared.preset == "startup-debate"
    assert prepared.display_topic == "an AI tutor for overwhelmed college students"


def test_write_beginner_share_card_uses_session_log(repo_root, tmp_path):
    args, _ = parse_args(
        [
            "--mode",
            "beginner",
            "--topic",
            "Explain resonance simply",
            "--preset",
            "explain-like-im-12",
            "--library",
            str(tmp_path),
        ]
    )
    args.display_topic = "Explain resonance simply"
    log_path = tmp_path / "RAIN_LAB_MEETING_LOG.md"
    log_path.write_text("hello world from the session", encoding="utf-8")

    share_path = _write_beginner_share_card(
        args,
        repo_root,
        requested_mode="beginner",
        launched_mode="chat",
        exit_code=0,
    )

    assert share_path is not None
    assert share_path.exists()
    assert share_path.suffix == ".html"
    contents = share_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in contents
    assert "Explain resonance simply" in contents
    assert "hello world from the session" in contents
    assert "Copy Caption" in contents
    assert "Copy Quote" in contents
    assert "Open Poster SVG" in contents
    assert "Spotlight Quote" in contents
    assert "screenshot-friendly" in contents
    assert "Try Next" in contents
    assert "Open Local Showcase" in contents
    poster_path = share_path.parent / (
        share_path.name.replace("BEGINNER_SHARE_", "BEGINNER_POSTER_").replace(".html", ".svg")
    )
    assert poster_path.exists()
    assert (share_path.parent / share_path.name.replace(".html", ".md")).exists()


def test_write_beginner_share_card_skips_non_beginner(repo_root, tmp_path):
    args, _ = parse_args(["--mode", "chat", "--topic", "x", "--library", str(tmp_path)])
    share_path = _write_beginner_share_card(
        args,
        repo_root,
        requested_mode="chat",
        launched_mode="chat",
        exit_code=0,
    )
    assert share_path is None


def test_build_demo_session_markdown_mentions_no_model():
    args, _ = parse_args(["--mode", "demo", "--preset", "startup-debate"])
    args.display_topic = "an AI coach for anxious founders"
    text = _build_demo_session_markdown(args)
    assert "no-model demo generated locally" in text
    assert "an AI coach for anxious founders" in text


def test_run_demo_session_writes_artifacts(repo_root, tmp_path):
    args, _ = parse_args(["--mode", "demo", "--preset", "idea-roast", "--library", str(tmp_path)])
    args = _prepare_demo_args(args)
    rc = _run_demo_session(args, repo_root, tmp_path / "meeting_archives" / "launcher_events.jsonl")
    assert rc == 0
    artifacts = list((tmp_path / "meeting_archives").glob("DEMO_SESSION_*.md"))
    share_cards = list((tmp_path / "meeting_archives").glob("BEGINNER_SHARE_*.html"))
    posters = list((tmp_path / "meeting_archives").glob("BEGINNER_POSTER_*.svg"))
    showcases = list((tmp_path / "meeting_archives").glob("RAIN_LAB_SHOWCASE.html"))
    assert artifacts
    assert share_cards
    assert posters
    assert showcases


def test_write_beginner_showcase_page_includes_recent_sessions(repo_root, tmp_path):
    share_dir = tmp_path / "meeting_archives"
    share_dir.mkdir(parents=True)
    recent_html = share_dir / "BEGINNER_SHARE_20260324_120000.html"
    recent_md = share_dir / "BEGINNER_SHARE_20260324_120000.md"
    recent_svg = share_dir / "BEGINNER_POSTER_20260324_120000.svg"
    recent_html.write_text("<!DOCTYPE html>", encoding="utf-8")
    recent_md.write_text(
        "\n".join(
            [
                "# Beginner Session Share Card",
                "",
                "Topic: Explain resonance simply",
                "Preset: Explain Like I'm 12",
                "Session style: Guided chat",
            ]
        ),
        encoding="utf-8",
    )
    recent_svg.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>", encoding="utf-8")
    args, _ = parse_args(["--mode", "demo", "--library", str(tmp_path)])
    args = _prepare_demo_args(args)

    showcase_path = _write_beginner_showcase_page(args, repo_root, latest_share_card=recent_html)

    contents = showcase_path.read_text(encoding="utf-8")
    assert "Poster Wall" in contents
    assert "Explain resonance simply" in contents
    assert "BEGINNER_POSTER_20260324_120000.svg" in contents
    assert "Run the debate" in contents or "Roast the idea" in contents


def test_build_follow_up_moves_skips_current_preset():
    moves = _build_follow_up_moves("Explain resonance simply", "idea-roast")
    labels = [move.label for move in moves]
    assert "Roast the idea" not in labels
    assert "Run the debate" in labels
    assert "Instant wow demo" in labels


def test_main_without_args_defaults_to_demo(monkeypatch, repo_root):
    recorded: dict[str, str] = {}

    monkeypatch.setattr(rain_launcher, "_print_banner", lambda: None)
    monkeypatch.setattr(
        rain_launcher,
        "_write_beginner_showcase_page",
        lambda _args, _root, latest_share_card=None: repo_root / "meeting_archives" / "RAIN_LAB_SHOWCASE.html",
    )
    monkeypatch.setattr(rain_launcher, "_resolve_launcher_log_path", lambda _args, _root: None)
    monkeypatch.setattr(rain_launcher, "_append_launcher_event", lambda *_args, **_kwargs: None)

    def fake_run_demo_session(args, _repo_root, _log_path):
        recorded["mode"] = args.mode
        recorded["preset"] = args.preset
        recorded["display_topic"] = args.display_topic
        return 0

    monkeypatch.setattr(rain_launcher, "_run_demo_session", fake_run_demo_session)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    rc = main([])

    assert rc == 0
    assert recorded["mode"] == "demo"
    assert recorded["preset"] == "startup-debate"
    assert recorded["display_topic"] == "an AI tutor for overwhelmed college students"
