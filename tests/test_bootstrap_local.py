from pathlib import Path

import bootstrap_local as bootstrap


def test_choose_runtime_requirements_prefers_pinned(tmp_path):
    (tmp_path / "requirements.txt").write_text("x", encoding="utf-8")
    (tmp_path / "requirements-pinned.txt").write_text("y", encoding="utf-8")
    chosen = bootstrap._choose_runtime_requirements(tmp_path)
    assert chosen.name == "requirements-pinned.txt"


def test_choose_runtime_requirements_falls_back(tmp_path):
    (tmp_path / "requirements.txt").write_text("x", encoding="utf-8")
    chosen = bootstrap._choose_runtime_requirements(tmp_path)
    assert chosen.name == "requirements.txt"


def test_choose_dev_requirements_order(tmp_path):
    (tmp_path / "requirements-dev.txt").write_text("x", encoding="utf-8")
    assert bootstrap._choose_dev_requirements(tmp_path).name == "requirements-dev.txt"

    (tmp_path / "requirements-dev-pinned.txt").write_text("y", encoding="utf-8")
    assert bootstrap._choose_dev_requirements(tmp_path).name == "requirements-dev-pinned.txt"


def test_choose_dev_requirements_none(tmp_path):
    assert bootstrap._choose_dev_requirements(tmp_path) is None


def test_venv_python_path_shape(tmp_path):
    venv = tmp_path / ".venv"
    p = bootstrap._venv_python(venv)
    if p.parts[-2] == "Scripts":
        assert p.name == "python.exe"
    else:
        assert p.parts[-2] == "bin"
        assert p.name == "python"
