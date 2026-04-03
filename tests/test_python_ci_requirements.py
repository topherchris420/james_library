from pathlib import Path


def _read_requirements(rel_path: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / rel_path).read_text(encoding="utf-8")


def test_root_requirements_include_lab_server_dependencies() -> None:
    loose = _read_requirements("requirements.txt")
    pinned = _read_requirements("requirements-pinned.txt")

    for text in (loose, pinned):
        assert "fastapi" in text
        assert "uvicorn[standard]" in text
