from pathlib import Path

import pytest


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def soul_files(repo_root):
    return list(repo_root.glob("*_SOUL.md"))
