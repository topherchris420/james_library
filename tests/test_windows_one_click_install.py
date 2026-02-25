from pathlib import Path


def test_one_click_launcher_scripts_exist(repo_root: Path) -> None:
    expected = [
        "INSTALL_RAIN.ps1",
        "INSTALL_RAIN.cmd",
        "RAIN_Lab_Chat.cmd",
        "RAIN_Lab_First_Run.cmd",
    ]
    for rel in expected:
        assert (repo_root / rel).exists(), f"Missing launcher artifact: {rel}"


def test_installer_mentions_shortcut_creation(repo_root: Path) -> None:
    text = (repo_root / "INSTALL_RAIN.ps1").read_text(encoding="utf-8")
    assert "NoShortcuts" in text
    assert "New-RainShortcut" in text
    assert "R.A.I.N. Lab Chat" in text
