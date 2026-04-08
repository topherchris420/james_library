from pathlib import Path


def test_posix_installer_exists(repo_root: Path) -> None:
    assert (repo_root / "install.sh").exists()


def test_posix_installer_uses_fetch_first_flow(repo_root: Path) -> None:
    text = (repo_root / "install.sh").read_text(encoding="utf-8")
    assert "bootstrap_local.py" in text
    assert "chat_with_james.py" in text
    assert "--greet" in text
    assert "requirements-pinned.txt" in text
    assert '"https://astral.sh/uv/install.sh"' in text
    assert "cargo build --release" not in text
    assert "cargo install --path" not in text
