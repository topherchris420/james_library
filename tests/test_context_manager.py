
import os
import tempfile
from pathlib import Path
import pytest
from rain_lab_meeting_chat_version import ContextManager, Config

@pytest.fixture
def temp_library():
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)

        # Create valid files
        (base / "valid.md").write_text("content")
        (base / "valid.txt").write_text("content")

        # Create ignored file
        (base / "ignored.bin").write_text("content")

        # Create nested valid
        (base / "nested").mkdir()
        (base / "nested" / "valid.md").write_text("content")

        # Create ignored directory
        (base / "node_modules").mkdir()
        (base / "node_modules" / "should_be_ignored.md").write_text("content")

        # Create another ignored dir
        (base / ".git").mkdir()
        (base / ".git" / "config.txt").write_text("content")

        yield base

def test_discovery_recursive(temp_library):
    config = Config(library_path=str(temp_library), recursive_library_scan=True)
    cm = ContextManager(config)

    files = cm._discover_files()
    filenames = {f.name for f in files}

    assert "valid.md" in filenames
    assert "valid.txt" in filenames
    # The file in nested/valid.md has name "valid.md", so it's in the set.
    # Let's check full paths relative to temp_library
    rel_paths = {str(f.relative_to(temp_library)) for f in files}

    assert "valid.md" in rel_paths
    assert "valid.txt" in rel_paths
    assert os.path.join("nested", "valid.md") in rel_paths

    # Check ignored
    assert "ignored.bin" not in rel_paths
    assert os.path.join("node_modules", "should_be_ignored.md") not in rel_paths
    assert os.path.join(".git", "config.txt") not in rel_paths

def test_discovery_non_recursive(temp_library):
    config = Config(library_path=str(temp_library), recursive_library_scan=False)
    cm = ContextManager(config)

    files = cm._discover_files()
    rel_paths = {str(f.relative_to(temp_library)) for f in files}

    assert "valid.md" in rel_paths
    assert "valid.txt" in rel_paths
    assert os.path.join("nested", "valid.md") not in rel_paths
