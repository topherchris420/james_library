"""Tests for godot_setup.py — Godot auto-download and discovery."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import godot_setup


class TestPlatformDetection:
    def test_detect_platform_returns_tuple(self):
        system, machine = godot_setup._detect_platform()
        assert isinstance(system, str)
        assert isinstance(machine, str)
        assert system in ("Windows", "Linux", "Darwin")

    def test_get_platform_info_returns_tuple_or_none(self):
        result = godot_setup._get_platform_info("4.4.1")
        if result is not None:
            url, zip_name, exe_name = result
            assert "4.4.1" in url
            assert zip_name.endswith(".zip")


class TestLocalBinaryName:
    def test_local_binary_name_contains_version(self):
        name = godot_setup._local_binary_name("4.4.1")
        assert "4.4.1" in name


class TestGetInstalledBinary:
    def test_returns_none_when_no_runtime_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", tmp_path / "nonexistent")
        assert godot_setup.get_installed_binary() is None

    def test_finds_binary_in_runtime_dir(self, tmp_path, monkeypatch):
        runtime = tmp_path / ".godot_runtime"
        runtime.mkdir()
        binary = runtime / "godot_v4.4.1.exe"
        binary.write_bytes(b"fake")
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", runtime)
        result = godot_setup.get_installed_binary()
        assert result is not None
        assert result.name == "godot_v4.4.1.exe"

    def test_finds_macos_bundle(self, tmp_path, monkeypatch):
        runtime = tmp_path / ".godot_runtime"
        macos_dir = runtime / "Godot.app" / "Contents" / "MacOS"
        macos_dir.mkdir(parents=True)
        binary = macos_dir / "Godot"
        binary.write_bytes(b"fake")
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", runtime)
        result = godot_setup.get_installed_binary()
        assert result is not None
        assert result.name == "Godot"


class TestGetInstalledVersion:
    def test_returns_none_when_no_marker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(godot_setup, "MARKER_FILE", tmp_path / ".godot_version")
        assert godot_setup.get_installed_version() is None

    def test_reads_version_from_marker(self, tmp_path, monkeypatch):
        marker = tmp_path / ".godot_version"
        marker.write_text("4.4.1", encoding="utf-8")
        monkeypatch.setattr(godot_setup, "MARKER_FILE", marker)
        assert godot_setup.get_installed_version() == "4.4.1"


class TestCheckGodotStatus:
    def test_not_installed_when_nothing_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", tmp_path / "none")
        monkeypatch.setattr(godot_setup, "MARKER_FILE", tmp_path / "marker")
        # Also prevent system PATH discovery
        monkeypatch.setattr(godot_setup.shutil, "which", lambda _: None)
        monkeypatch.delenv("RAIN_GODOT_BIN", raising=False)
        status = godot_setup.check_godot_status(verbose=False)
        assert status["installed"] is False

    def test_installed_when_binary_present(self, tmp_path, monkeypatch):
        runtime = tmp_path / ".godot_runtime"
        runtime.mkdir()
        binary = runtime / "godot_v4.4.1.exe"
        binary.write_bytes(b"fake")
        marker = runtime / ".godot_version"
        marker.write_text("4.4.1", encoding="utf-8")
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", runtime)
        monkeypatch.setattr(godot_setup, "MARKER_FILE", marker)
        status = godot_setup.check_godot_status(verbose=False)
        assert status["installed"] is True
        assert "4.4.1" in status["binary_path"]


class TestUninstall:
    def test_removes_runtime_dir(self, tmp_path, monkeypatch):
        runtime = tmp_path / ".godot_runtime"
        runtime.mkdir()
        (runtime / "godot_v4.4.1").write_bytes(b"fake")
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", runtime)
        assert godot_setup.uninstall_godot(verbose=False) is True
        assert not runtime.exists()

    def test_noop_when_nothing_to_remove(self, tmp_path, monkeypatch):
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", tmp_path / "nonexistent")
        assert godot_setup.uninstall_godot(verbose=False) is False


class TestCLI:
    def test_check_flag_returns_1_when_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", tmp_path / "none")
        monkeypatch.setattr(godot_setup, "MARKER_FILE", tmp_path / "marker")
        monkeypatch.setattr(godot_setup.shutil, "which", lambda _: None)
        monkeypatch.delenv("RAIN_GODOT_BIN", raising=False)
        assert godot_setup.main(["--check"]) == 1

    def test_check_flag_returns_0_when_installed(self, tmp_path, monkeypatch):
        runtime = tmp_path / ".godot_runtime"
        runtime.mkdir()
        (runtime / "godot_v4.4.1.exe").write_bytes(b"fake")
        marker = runtime / ".godot_version"
        marker.write_text("4.4.1", encoding="utf-8")
        monkeypatch.setattr(godot_setup, "RUNTIME_DIR", runtime)
        monkeypatch.setattr(godot_setup, "MARKER_FILE", marker)
        assert godot_setup.main(["--check"]) == 0
