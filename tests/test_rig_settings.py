"""Tests for james_library.utilities.rig_settings (shared [rig] contract)."""

import ipaddress
from pathlib import Path

import pytest

from james_library.utilities import rig_settings as rs


def _write_config(dir_path: Path, body: str) -> Path:
    path = dir_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _resolver(table):
    def resolve(host):
        values = table.get(host)
        return [ipaddress.ip_address(v) for v in values] if values else None

    return resolve


def test_no_config_keeps_pre_rig_behaviour(tmp_path):
    env = {"rain_CONFIG_DIR": str(tmp_path)}
    settings = rs.load_rig_settings(env)
    assert settings.effective_privacy() == ("hybrid", "default")
    # Hybrid never refuses anything, including cloud models.
    assert rs.enforce_meeting_privacy("https://api.example.com/v1", "m:cloud", env=env) == "hybrid"


def test_config_resolution_order(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    _write_config(cfg, "[rig]\nprivacy = \"local\"\n")
    assert rs.resolve_config_path({"rain_CONFIG_DIR": str(cfg)}) == cfg / "config.toml"

    home = tmp_path / "home"
    (home / ".R.A.I.N.").mkdir(parents=True)
    default_cfg = _write_config(home / ".R.A.I.N.", "")
    assert rs.resolve_config_path({"HOME": str(home)}) == default_cfg

    marked = tmp_path / "marked"
    marked.mkdir()
    marked_cfg = _write_config(marked, "")
    (home / ".R.A.I.N." / "active_workspace.toml").write_text(f'config_dir = "{marked}"\n')
    assert rs.resolve_config_path({"HOME": str(home)}) == marked_cfg

    ws = tmp_path / "ws"
    ws.mkdir()
    ws_cfg = _write_config(ws, "")
    assert rs.resolve_config_path({"HOME": str(home), "rain_WORKSPACE": str(ws)}) == ws_cfg


def test_profile_privacy_comes_from_the_shared_profile_files(tmp_path):
    for profile in rs.PROFILES:
        assert (rs.PROFILE_DIR / f"{profile}.toml").is_file()
        settings = rs.RigSettings(profile=profile)
        assert settings.effective_privacy() == ("local", "profile")
    assert rs.RigSettings(profile="local", privacy="hybrid").effective_privacy() == ("hybrid", "explicit")


@pytest.mark.parametrize("use_minimal", [False, True])
def test_parsing_rig_and_meeting_tables(use_minimal):
    text = (
        "default_provider = \"llamacpp\"\n"
        "[rig]\nprofile = \"field\"  # comment\nnode_name = 'kit'\n"
        "[rig.meeting]\nbase_url = \"http://127.0.0.1:8080/v1\"\nmodel = \"Qwen3.gguf\"\n"
        "[gateway]\nhost = \"127.0.0.1\"\n"
    )
    rig = rs._parse_rig_tables_minimal(text) if use_minimal else rs.parse_rig_table(text)
    assert rig["profile"] == "field"
    assert rig["meeting"] == {"base_url": "http://127.0.0.1:8080/v1", "model": "Qwen3.gguf"}


def test_invalid_privacy_value_and_malformed_rig_fail_closed(tmp_path):
    _write_config(tmp_path, "[rig]\nprivacy = \"everything\"\n")
    with pytest.raises(rs.RigPrivacyError):
        rs.load_rig_settings({"rain_CONFIG_DIR": str(tmp_path)})
    _write_config(tmp_path, "[rig\nprivacy = local\n")
    with pytest.raises(rs.RigPrivacyError):
        rs.load_rig_settings({"rain_CONFIG_DIR": str(tmp_path)})
    # A malformed config without [rig] is not this module's concern.
    _write_config(tmp_path, "[gateway\n")
    assert rs.load_rig_settings({"rain_CONFIG_DIR": str(tmp_path)}).privacy is None


def test_locality_mirrors_rust_rules():
    resolve = _resolver({
        "rig-node.local": ["192.168.1.40"],
        "split.home.arpa": ["192.168.1.2", "203.0.113.7"],
        "public.local": ["8.8.8.8"],
    })
    assert rs.classify_url("http://localhost:8080/v1", resolve) == "loopback"
    assert rs.classify_url("http://[::1]:8080", resolve) == "loopback"
    assert rs.classify_url("http://192.168.1.7:8080", resolve) == "private"
    assert rs.classify_url("http://[fd00::1]:8080", resolve) == "private"
    assert rs.classify_url("http://[::ffff:127.0.0.1]:1", resolve) == "loopback"
    assert rs.classify_url("http://rig-node.local:8080/v1", resolve) == "private"
    for url in (
        "http://split.home.arpa/v1",
        "http://public.local/v1",
        "http://unknown.local/v1",
        "http://0.0.0.0:8080",
        "http://100.64.0.1/",
        "https://api.openai.com/v1",
        "not a url",
    ):
        assert rs.classify_url(url, resolve) == "remote", url


def test_meeting_precedence_env_then_rig_meeting_then_default():
    settings = rs.RigSettings(meeting_base_url="http://127.0.0.1:8080/v1", meeting_model="Qwen3.gguf")
    assert rs.meeting_model("minimax-m2.7:cloud", env={}, settings=settings) == "Qwen3.gguf"
    assert rs.meeting_base_url("http://127.0.0.1:11434/v1", env={}, settings=settings) == "http://127.0.0.1:8080/v1"
    env = {"RAIN_LLM_MODEL": "env-model", "LM_STUDIO_BASE_URL": "http://10.0.0.2:1234/v1"}
    assert rs.meeting_model("d", env=env, settings=settings) == "env-model"
    assert rs.meeting_base_url("d", env=env, settings=settings) == "http://10.0.0.2:1234/v1"
    assert rs.meeting_model("default-model", env={}, settings=rs.RigSettings()) == "default-model"


def test_local_privacy_refuses_hosted_meeting_and_allows_local():
    local = rs.RigSettings(privacy="local")
    with pytest.raises(rs.RigPrivacyError, match="cloud"):
        rs.enforce_meeting_privacy("http://127.0.0.1:11434/v1", "minimax-m2.7:cloud", settings=local)
    with pytest.raises(rs.RigPrivacyError, match="api.example.com"):
        rs.enforce_meeting_privacy("https://api.example.com/v1", "m", settings=local, resolver=lambda h: None)
    assert rs.enforce_meeting_privacy("http://127.0.0.1:8080/v1", "Qwen3.gguf", settings=local) == "local"
    assert rs.enforce_meeting_privacy("https://api.example.com/v1", "m:cloud",
                                      settings=rs.RigSettings(privacy="hybrid")) == "hybrid"


def test_runtime_validation_refuses_hosted_model_in_local_mode(tmp_path, monkeypatch):
    import rain_lab_runtime

    _write_config(tmp_path, "[rig]\nprofile = \"local\"\n")
    monkeypatch.setenv("rain_CONFIG_DIR", str(tmp_path))
    config = rain_lab_runtime.load_runtime_config()
    config.llm_base_url = "http://127.0.0.1:1234/v1"
    config.llm_model = "minimax-m2.7:cloud"
    with pytest.raises(RuntimeError, match="privacy"):
        rain_lab_runtime.validate_runtime_config(config)
    config.llm_model = "local-model"
    rain_lab_runtime.validate_runtime_config(config)
