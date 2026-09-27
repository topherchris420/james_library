import re
from pathlib import Path


PRIMARY_DOC_EXPECTATIONS = {
    "README.md": ["INSTALL_RAIN.cmd", "./install.sh", "python rain_lab.py"],
    "START_HERE.md": ["INSTALL_RAIN.cmd", "./install.sh", "python rain_lab.py"],
    "docs/index.md": ["INSTALL_RAIN.cmd", "./install.sh", "python rain_lab.py"],
    "docs/getting-started/README.md": ["INSTALL_RAIN.cmd", "./install.sh", "python rain_lab.py"],
    "docs/one-click-bootstrap.md": ["INSTALL_RAIN.cmd", "./install.sh", "python rain_lab.py"],
    "docs/setup-guides/README.md": ["INSTALL_RAIN.cmd", "./install.sh", "python rain_lab.py"],
    "docs/setup-guides/one-click-bootstrap.md": ["INSTALL_RAIN.cmd", "./install.sh", "python rain_lab.py"],
    "docs/troubleshooting.md": ["./install.sh", "INSTALL_RAIN.cmd"],
    "docs/ops/troubleshooting.md": ["./install.sh", "INSTALL_RAIN.cmd"],
}

PRIMARY_DOCS = tuple(PRIMARY_DOC_EXPECTATIONS)
README_TAGLINE = (
    "A local-first research environment where four constrained AI perspectives "
    "investigate a question, challenge one another, and leave an inspectable record."
)
README_PRODUCT_SUMMARY_PATTERN = re.compile(
    r"Think with a room that is allowed to disagree\."
)
README_EXPERT_SUMMARY = (
    "Bring a hypothesis, a difficult paper, or an idea that needs pressure-testing. "
    "James, Jasmine, Luca, and Elena approach it through evidence, feasibility, "
    "geometry, and formal reasoning. The useful outcome is a clearer account of "
    "what is supported, what remains contested, and what to investigate next."
)
README_ASSISTANT_LINE_PATTERN = re.compile(
    r"\*\*R\.A\.I\.N\. Lab\*\* is the product\. "
    r"\*\*James\*\* is its lead assistant\."
)
README_HOSTED_URL = "https://rainlabteam.vercel.app"

LEGACY_DOC_MARKERS = (
    "MultiplicityFoundation/R.A.I.N.",
    "rainlabs.sh/install.sh",
    "R.A.I.N. onboard",
    "./install.sh --install-rust",
    "./install.sh --install-system-deps",
    "./install.sh --prefer-prebuilt",
    "./install.sh --prebuilt-only",
    "./install.sh --force-source-build",
    "./install.sh --docker",
)


def _read(repo_root: Path, rel_path: str) -> str:
    return (repo_root / rel_path).read_text(encoding="utf-8")


def _find_readme_chrome_index(text: str) -> int:
    candidates = []

    logo_index = text.find("assets/rain_lab.png")
    if logo_index != -1:
        candidates.append(logo_index)

    translation_match = re.search(r"README\.[A-Za-z-]+\.md", text)
    if translation_match:
        candidates.append(translation_match.start())

    assert candidates, "README.md is missing both the logo asset marker and translated README links"
    return min(candidates)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _find_required_index(text: str, marker: str | re.Pattern[str]) -> int:
    if isinstance(marker, str):
        return text.index(marker)

    match = marker.search(text)
    assert match is not None, f"README.md is missing required positioning marker: {marker.pattern!r}"
    return match.start()


def _lead_story_indexes(text: str) -> list[int]:
    normalized_text = _normalize_whitespace(text)
    lead_story_fragments = [
        "# R.A.I.N. Lab",
        README_TAGLINE,
        README_PRODUCT_SUMMARY_PATTERN,
        README_EXPERT_SUMMARY,
        README_ASSISTANT_LINE_PATTERN,
    ]
    return [_find_required_index(normalized_text, fragment) for fragment in lead_story_fragments]


def test_readme_chrome_detection_ignores_incidental_markup() -> None:
    text = f"""# R.A.I.N. Lab

**{README_TAGLINE}**

Think with a room that is allowed to disagree.

{README_EXPERT_SUMMARY}

**R.A.I.N. Lab** is the product. **James** is its lead assistant.

<p align="center">
  <img alt="R.A.I.N. Lab logo" src="assets/rain_lab.png" class="hero" />
</p>

<p align="center">
  <a href="README.vi.md">Tiếng Việt</a> •
  <a href="README.fr.md">Français</a> •
  <a href="README.zh-CN.md">简体中文</a>
</p>

## Try R.A.I.N. Lab
"""

    assert _find_readme_chrome_index(text) == text.index("assets/rain_lab.png")


def test_readme_lead_story_order_detection() -> None:
    text = f"""# R.A.I.N. Lab

**{README_TAGLINE}**

Think with a room that is allowed to disagree.

{README_EXPERT_SUMMARY}

**R.A.I.N. Lab** is the product. **James** is its lead assistant.

<p align="center">
  <img alt="R.A.I.N. Lab logo" src="assets/rain_lab.png" class="hero" />
</p>

## Try R.A.I.N. Lab
"""

    assert _lead_story_indexes(text) == sorted(_lead_story_indexes(text))


def test_readme_leads_with_research_panel_positioning(repo_root: Path) -> None:
    text = _read(repo_root, "README.md")

    heading = "# R.A.I.N. Lab"
    tagline = README_TAGLINE
    product_summary = README_PRODUCT_SUMMARY_PATTERN
    expert_summary = README_EXPERT_SUMMARY
    assistant_line = README_ASSISTANT_LINE_PATTERN
    hosted_url = README_HOSTED_URL
    local_runner = "python rain_lab.py"
    first_section = "## Try R.A.I.N. Lab"
    expected_sections = (
        "## Try R.A.I.N. Lab",
        "## What happens when you ask a question?",
        "## See it work",
        "## Why R.A.I.N.?",
        "## Meet the research panel",
        "## How authority works",
        "## How R.A.I.N. is structured",
        "## Recorded sessions and replay",
        "## Optional extensions",
        "## Privacy and network boundaries",
        "## What R.A.I.N. does not claim",
        "## Documentation and development",
        "## License and acknowledgments",
    )

    lead_story_indexes = _lead_story_indexes(text)
    normalized = _normalize_whitespace(text)
    heading_index = _find_required_index(normalized, heading)
    tagline_index = _find_required_index(normalized, tagline)
    product_summary_index = _find_required_index(normalized, product_summary)
    expert_summary_index = _find_required_index(normalized, expert_summary)
    assistant_line_index = _find_required_index(text, assistant_line)
    chrome_index = _find_readme_chrome_index(text)
    hosted_url_index = _find_required_index(text, hosted_url)
    local_runner_index = text.index(local_runner)
    first_section_index = text.index(first_section)

    assert lead_story_indexes == sorted(lead_story_indexes)
    assert heading_index < tagline_index
    assert product_summary_index < expert_summary_index
    assert expert_summary_index < chrome_index
    assert chrome_index < first_section_index
    assert first_section_index < assistant_line_index
    assert hosted_url_index < local_runner_index
    assert "### Public Web Experience (Coming Soon)" not in text

    section_indexes = [text.index(section) for section in expected_sections]
    assert section_indexes == sorted(section_indexes)
    for section in expected_sections:
        assert section in text, f"README.md is missing expected section: {section!r}"

    assert "# James and the R.A.I.N. Lab" not in text
    assert "The local-first autonomous coding agent runtime for Rust, Python, and hardware-adjacent teams." not in text


def test_primary_docs_keep_current_install_story(repo_root: Path) -> None:
    for rel_path, expected_fragments in PRIMARY_DOC_EXPECTATIONS.items():
        text = _read(repo_root, rel_path)
        for fragment in expected_fragments:
            assert fragment in text, f"{rel_path} is missing required cohesion marker: {fragment!r}"


def test_primary_docs_reject_legacy_repo_and_installer_markers(repo_root: Path) -> None:
    for rel_path in PRIMARY_DOCS:
        text = _read(repo_root, rel_path)
        for marker in LEGACY_DOC_MARKERS:
            assert marker not in text, f"{rel_path} still contains legacy marker: {marker!r}"


def test_clone_instructions_use_current_repo_identity(repo_root: Path) -> None:
    for rel_path in ("README.md", "docs/index.md", "CONTRIBUTING.md"):
        text = _read(repo_root, rel_path)
        assert "https://github.com/topherchris420/james_library.git" in text
        assert "cd james_library" in text


def test_security_doc_uses_current_issue_tracker(repo_root: Path) -> None:
    text = _read(repo_root, "SECURITY.md")
    assert "https://github.com/topherchris420/james_library/issues" in text
    assert "MultiplicityFoundation/R.A.I.N." not in text
