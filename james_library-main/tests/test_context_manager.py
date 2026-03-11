
import os
import tempfile
from pathlib import Path

import pytest

from rain_lab_meeting_chat_version import Config, ContextManager


@pytest.fixture
def temp_library():
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)

        # Create valid title-style paper files
        (base / "Temporal Re-Localization via Scalar Resonance.md").write_text("content")
        (base / "Discrete Celestial Holography.txt").write_text("content")

        # Create ignored file
        (base / "ignored.bin").write_text("content")
        (base / "README.md").write_text("content")

        # Create nested valid
        (base / "nested").mkdir()
        (base / "nested" / "Recursive Resonance Stabilization.md").write_text("content")

        # Create ignored directory
        (base / "node_modules").mkdir()
        (base / "node_modules" / "Should Be Ignored.md").write_text("content")

        # Create another ignored dir
        (base / ".git").mkdir()
        (base / ".git" / "Config Notes.txt").write_text("content")

        yield base

def test_discovery_recursive(temp_library):
    config = Config(library_path=str(temp_library), recursive_library_scan=True)
    config.paper_title_allowlist = ()
    cm = ContextManager(config)

    files = cm._discover_files()
    filenames = {f.name for f in files}

    assert "Temporal Re-Localization via Scalar Resonance.md" in filenames
    assert "Discrete Celestial Holography.txt" in filenames
    # Let's check full paths relative to temp_library
    rel_paths = {str(f.relative_to(temp_library)) for f in files}

    assert "Temporal Re-Localization via Scalar Resonance.md" in rel_paths
    assert "Discrete Celestial Holography.txt" in rel_paths
    assert os.path.join("nested", "Recursive Resonance Stabilization.md") in rel_paths

    # Check ignored
    assert "ignored.bin" not in rel_paths
    assert "README.md" not in rel_paths
    assert os.path.join("node_modules", "Should Be Ignored.md") not in rel_paths
    assert os.path.join(".git", "Config Notes.txt") not in rel_paths

def test_discovery_non_recursive(temp_library):
    config = Config(library_path=str(temp_library), recursive_library_scan=False)
    config.paper_title_allowlist = ()
    cm = ContextManager(config)

    files = cm._discover_files()
    rel_paths = {str(f.relative_to(temp_library)) for f in files}

    assert "Temporal Re-Localization via Scalar Resonance.md" in rel_paths
    assert "Discrete Celestial Holography.txt" in rel_paths
    assert os.path.join("nested", "Recursive Resonance Stabilization.md") not in rel_paths
