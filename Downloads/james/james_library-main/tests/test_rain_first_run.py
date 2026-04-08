import subprocess

from james_library.bootstrap import rain_first_run


def test_main_success_prints_next_steps(monkeypatch, capsys):
    def _ok(_repo_root):  # noqa: ARG001
        return subprocess.CompletedProcess(args=["preflight"], returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(rain_first_run, "_run_preflight", _ok)
    rc = rain_first_run.main(["--topic", "resonance"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Preflight passed" in out
    assert '--mode beginner --topic "resonance"' in out
    assert "--mode demo --preset startup-debate" in out


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
    assert "--mode first-run" in out
    assert "--mode demo --preset startup-debate" in out
