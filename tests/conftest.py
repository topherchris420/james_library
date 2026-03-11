import os

# Guard against tools.py module-level _init_rag() loading torch/sentence_transformers
# during test collection, which causes a Windows access violation and kills pytest.
# These must be set before any import of tools, rain_lab_meeting, etc.
os.environ.setdefault("RAIN_SKIP_RAG", "1")
os.environ.setdefault("RLM_REQUIRE_WEB", "0")

from pathlib import Path

import pytest


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def soul_files(repo_root):
    return list(repo_root.glob("*_SOUL.md"))
