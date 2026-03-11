def test_all_four_souls_exist(soul_files):
    names = {f.name for f in soul_files}
    required = {"JAMES_SOUL.md", "JASMINE_SOUL.md", "ELENA_SOUL.md", "LUCA_SOUL.md"}
    assert required.issubset(names), f"Missing: {required - names}"


def test_soul_files_have_identity_section(soul_files):
    for sf in soul_files:
        content = sf.read_text(encoding="utf-8")
        assert "## Identity" in content, f"{sf.name} missing ## Identity"


def test_soul_files_non_empty(soul_files):
    for sf in soul_files:
        assert sf.stat().st_size > 100, f"{sf.name} suspiciously small"
