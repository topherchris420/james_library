import pytest
from pathlib import Path


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def soul_files(repo_root):
    return list(repo_root.glob("*_SOUL.md"))


@pytest.fixture(autouse=True)
def _isolate_rain_config(tmp_path_factory, monkeypatch):
    """Keep tests independent of a developer's ~/.R.A.I.N./config.toml ([rig] privacy).

    Uses its own directory so a test's ``tmp_path`` stays empty.
    """
    config_dir = tmp_path_factory.mktemp("rain-config")
    monkeypatch.setenv("rain_CONFIG_DIR", str(config_dir))
