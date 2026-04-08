import json

import bootstrap_local as bootstrap


def test_detect_platform_spec_windows_intel():
    spec = bootstrap.detect_platform_spec(system_name="Windows", machine_name="AMD64")
    assert spec.os_name == "windows"
    assert spec.arch_name == "intel"
    assert spec.target == "x86_64-pc-windows-msvc"
    assert spec.binary_name == "rain.exe"


def test_detect_platform_spec_macos_apple_silicon():
    spec = bootstrap.detect_platform_spec(system_name="Darwin", machine_name="arm64")
    assert spec.os_name == "macos"
    assert spec.arch_name == "apple-silicon"
    assert spec.target == "aarch64-apple-darwin"
    assert spec.archive_ext == "tar.gz"


def test_parse_github_repo_slug_from_https_url():
    assert (
        bootstrap._parse_github_repo_slug("https://github.com/topherchris420/james_library.git")
        == "topherchris420/james_library"
    )


def test_select_release_asset_prefers_exact_target_match():
    spec = bootstrap.PlatformSpec("windows", "intel", "x86_64-pc-windows-msvc", "zip", "rain.exe")
    releases = [
        {
            "tag_name": "v1.2.3",
            "draft": False,
            "assets": [
                {
                    "name": "R.A.I.N.-x86_64-pc-windows-msvc.zip",
                    "browser_download_url": "https://example.invalid/rain.zip",
                }
            ],
        }
    ]
    asset = bootstrap.select_release_asset(releases, spec)
    assert asset.tag_name == "v1.2.3"
    assert asset.asset_name == "R.A.I.N.-x86_64-pc-windows-msvc.zip"


def test_ensure_config_file_copies_from_example(tmp_path):
    (tmp_path / "config.example.toml").write_text('default_provider = "ollama"\n', encoding="utf-8")
    config_path = bootstrap.ensure_config_file(tmp_path)
    assert config_path.read_text(encoding="utf-8") == 'default_provider = "ollama"\n'


def test_ensure_env_file_uses_remote_provider_when_key_present(tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text(
        "API_KEY=your-api-key-here\nPROVIDER=openrouter\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "_clear_terminal", lambda: None)
    monkeypatch.setattr(bootstrap, "_prompt_for_primary_api_key", lambda: "sk-test-123")

    env_path = bootstrap.ensure_env_file(tmp_path, interactive=True)
    text = env_path.read_text(encoding="utf-8")

    assert "API_KEY=sk-test-123" in text
    assert "PROVIDER=openrouter" in text


def test_ensure_env_file_defaults_to_ollama_when_key_missing(tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text(
        "API_KEY=your-api-key-here\nPROVIDER=openrouter\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "_clear_terminal", lambda: None)

    env_path = bootstrap.ensure_env_file(tmp_path, interactive=False)
    text = env_path.read_text(encoding="utf-8")

    assert "API_KEY=" in text
    assert "PROVIDER=ollama" in text


def test_cached_release_matches_checks_metadata(tmp_path):
    metadata_path = tmp_path / "rain-engine-release.json"
    asset = bootstrap.ReleaseAsset(
        tag_name="v9.9.9",
        asset_name="R.A.I.N.-x86_64-unknown-linux-gnu.tar.gz",
        download_url="https://example.invalid/rain.tar.gz",
    )
    spec = bootstrap.PlatformSpec("linux", "intel", "x86_64-unknown-linux-gnu", "tar.gz", "rain")
    metadata_path.write_text(
        json.dumps(
            {
                "repo": "topherchris420/james_library",
                "tag": "v9.9.9",
                "asset": "R.A.I.N.-x86_64-unknown-linux-gnu.tar.gz",
                "target": "x86_64-unknown-linux-gnu",
            }
        ),
        encoding="utf-8",
    )

    assert bootstrap._cached_release_matches(
        metadata_path,
        repo_slug="topherchris420/james_library",
        asset=asset,
        spec=spec,
    )
