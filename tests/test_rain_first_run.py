import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rain_first_run


def test_main_success_prints_next_steps(monkeypatch, capsys):
    def _ok(_repo_root):  # noqa: ARG001
        return subprocess.CompletedProcess(args=["preflight"], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(rain_first_run, "_run_preflight", _ok)
    monkeypatch.setattr(rain_first_run, "_mark_first_run_complete", lambda _repo_root: None)
    # Stub _check_godot so it doesn't prompt for input during tests
    monkeypatch.setattr(rain_first_run, "_check_godot", lambda _repo_root: False)
    rc = rain_first_run.main(["--topic", "resonance"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Preflight passed" in out
    assert '--mode chat' in out
    assert "resonance" in out


def test_main_success_launches_chat_when_requested(monkeypatch, capsys):
    def _ok(_repo_root):  # noqa: ARG001
        return subprocess.CompletedProcess(args=["preflight"], returncode=0, stdout="ok", stderr="")

    launched: list[str] = []
    monkeypatch.setattr(rain_first_run, "_run_preflight", _ok)
    monkeypatch.setattr(rain_first_run, "_mark_first_run_complete", lambda _repo_root: None)
    monkeypatch.setattr(rain_first_run, "_check_godot", lambda _repo_root: False)
    monkeypatch.setattr(
        rain_first_run,
        "_launch_chat",
        lambda _repo_root, topic: launched.append(topic) or 0,
    )

    rc = rain_first_run.main(["--launch-chat", "--topic", "resonance"])
    out = capsys.readouterr().out

    assert rc == 0
    assert launched == ["resonance"]
    assert "Launching chat" in out


def test_main_failure_prints_retry_guidance(monkeypatch, capsys):
    def _fail(_repo_root):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=["preflight"],
            returncode=1,
            stdout="missing dependency",
            stderr="",
        )

    monkeypatch.setattr(rain_first_run, "_run_preflight", _fail)
    rc = rain_first_run.main([])
    out = capsys.readouterr().out

    assert rc == 1
    assert "Preflight reported actionable issues" in out
    assert "--mode doctor" in out
    assert "--mode first-run" in out
