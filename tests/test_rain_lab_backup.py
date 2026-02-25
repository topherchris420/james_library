from pathlib import Path
from zipfile import ZipFile

import rain_lab_backup as backup


def test_create_backup_writes_zip_and_manifest(tmp_path):
    library = tmp_path / "workspace"
    library.mkdir()
    (library / "README.md").write_text("hello", encoding="utf-8")
    (library / "__pycache__").mkdir()
    (library / "__pycache__" / "x.pyc").write_bytes(b"compiled")
    (library / "meeting_archives").mkdir()
    (library / "meeting_archives" / "runtime_events.jsonl").write_text("{}", encoding="utf-8")

    output = library / "backups" / "snapshot.zip"
    result = backup.create_backup(library, output)

    assert result["ok"] is True
    assert output.exists()
    with ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "README.md" in names
    assert "backup_manifest.json" in names
    assert "meeting_archives/runtime_events.jsonl" not in names
    assert "__pycache__/x.pyc" not in names


def test_create_backup_blocks_external_output_by_default(tmp_path):
    library = tmp_path / "workspace"
    library.mkdir()
    (library / "README.md").write_text("hello", encoding="utf-8")
    external_output = tmp_path / "outside.zip"

    try:
        backup.create_backup(library, external_output)
    except ValueError as exc:
        assert "Refusing to write backup outside" in str(exc)
    else:
        raise AssertionError("Expected backup path safety check to block external output")


def test_create_backup_allows_external_with_override(tmp_path):
    library = tmp_path / "workspace"
    library.mkdir()
    (library / "README.md").write_text("hello", encoding="utf-8")
    external_output = tmp_path / "outside.zip"

    result = backup.create_backup(library, external_output, allow_external_output=True)
    assert result["ok"] is True
    assert external_output.exists()
