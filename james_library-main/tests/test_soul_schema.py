"""Validate YAML frontmatter schema on every *_SOUL.md file.

Each soul file must begin with a ``---`` delimited YAML block containing
the keys defined by the schema contract so that identity drift between
agents is machine-detectable.
"""

import yaml

REQUIRED_KEYS = {
    "schema_version",
    "agent_name",
    "role",
    "lab",
    "word_limit",
    "last_updated",
}


def _parse_frontmatter(text: str) -> dict:
    """Return the YAML frontmatter dict from *text*, or raise."""
    # Strip UTF-8 BOM if present
    text = text.lstrip("\ufeff")
    assert text.startswith("---"), "missing YAML frontmatter (no leading ---)"
    end = text.index("---", 3)
    return yaml.safe_load(text[3:end])


# ------------------------------------------------------------------
# 1. Frontmatter exists and has all required keys
# ------------------------------------------------------------------


def test_soul_frontmatter(soul_files):
    """Every soul file must have valid YAML frontmatter with the required keys."""
    for sf in soul_files:
        text = sf.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{sf.name}: missing YAML frontmatter"
        meta = _parse_frontmatter(text)
        missing = REQUIRED_KEYS - set(meta.keys())
        assert not missing, f"{sf.name} missing keys: {missing}"


# ------------------------------------------------------------------
# 2. Value-level checks
# ------------------------------------------------------------------


def test_schema_version(soul_files):
    """schema_version must be a string parseable as a number."""
    for sf in soul_files:
        meta = _parse_frontmatter(sf.read_text(encoding="utf-8"))
        ver = str(meta["schema_version"])
        float(ver)  # raises ValueError if not numeric


def test_agent_name_nonempty(soul_files):
    for sf in soul_files:
        meta = _parse_frontmatter(sf.read_text(encoding="utf-8"))
        assert meta["agent_name"], f"{sf.name}: agent_name is empty"


def test_word_limit_is_pair(soul_files):
    """word_limit must be a two-element list [min, max] with min < max."""
    for sf in soul_files:
        meta = _parse_frontmatter(sf.read_text(encoding="utf-8"))
        wl = meta["word_limit"]
        assert isinstance(wl, list) and len(wl) == 2, (
            f"{sf.name}: word_limit must be [min, max]"
        )
        assert wl[0] < wl[1], f"{sf.name}: word_limit min >= max"


def test_lab_value(soul_files):
    """All agents should belong to R.A.I.N. Lab."""
    for sf in soul_files:
        meta = _parse_frontmatter(sf.read_text(encoding="utf-8"))
        assert meta["lab"] == "R.A.I.N. Lab", f"{sf.name}: unexpected lab value"


def test_last_updated_format(soul_files):
    """last_updated must be an ISO-8601 date string (YYYY-MM-DD)."""
    import re

    for sf in soul_files:
        meta = _parse_frontmatter(sf.read_text(encoding="utf-8"))
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta["last_updated"])), (
            f"{sf.name}: last_updated not in YYYY-MM-DD format"
        )


def test_all_four_souls_have_frontmatter(soul_files):
    """Ensure we're testing exactly the 4 expected soul files."""
    names = {sf.name for sf in soul_files}
    expected = {"JAMES_SOUL.md", "JASMINE_SOUL.md", "ELENA_SOUL.md", "LUCA_SOUL.md"}
    assert expected.issubset(names), f"Missing soul files: {expected - names}"
