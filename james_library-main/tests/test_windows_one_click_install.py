from pathlib import Path


def test_one_click_launcher_scripts_exist(repo_root: Path) -> None:
    expected = [
        "INSTALL_RAIN.ps1",
        "INSTALL_RAIN.cmd",
        "RAIN_Lab_Start.cmd",
        "RAIN_Lab_Chat.cmd",
        "RAIN_Lab_First_Run.cmd",
        "RAIN_Lab_Health_Check.cmd",
        "RAIN_Lab_Validate.cmd",
    ]
    for rel in expected:
        assert (repo_root / rel).exists(), f"Missing launcher artifact: {rel}"


def test_installer_mentions_shortcut_creation(repo_root: Path) -> None:
    text = (repo_root / "INSTALL_RAIN.ps1").read_text(encoding="utf-8")
    assert "NoShortcuts" in text
    assert "New-RainShortcut" in text
    assert "RAIN_Lab_Start.cmd" in text
    assert "R.A.I.N. Lab" in text
    assert "R.A.I.N. Lab Chat" in text
    assert "R.A.I.N. Lab Health Snapshot" in text
    assert "R.A.I.N. Lab Validate" in text


def test_start_launcher_runs_first_run_then_chat(repo_root: Path) -> None:
    text = (repo_root / "RAIN_Lab_Start.cmd").read_text(encoding="utf-8")
    assert ".first_run_complete" in text
    assert "--mode first-run --launch-chat" in text
    assert "--mode chat --ui auto" in text
