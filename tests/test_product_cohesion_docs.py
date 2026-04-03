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


def _lead_story_indexes(text: str) -> list[int]:
    normalized_text = _normalize_lead_story_whitespace(text)
    lead_story_fragments = [
        "# R.A.I.N. Lab",
        "A private-by-default expert panel in a box for researchers, independent thinkers, and R&D teams.",
        (
            "Ask a raw research question. R.A.I.N. Lab assembles multiple expert "
            "perspectives, grounds strong claims in papers or explicit evidence, and "
            "returns the strongest explanations, disagreements, and next moves."
        ),
        "Most tools help you find papers. R.A.I.N. Lab helps you think with a room full of experts.",
        "James is the assistant inside R.A.I.N. Lab",
    ]
    return [_find_lead_story_index(normalized_text, fragment) for fragment in lead_story_fragments]


def _normalize_lead_story_whitespace(text: str) -> str:
    """Normalize whitespace within line content but preserve line boundaries."""
    lines = text.splitlines()
    return "\n".join(" ".join(line.split()) for line in lines)


def _find_lead_story_index(text: str, fragment: str) -> int:
    return text.index(fragment)


def test_readme_chrome_detection_ignores_incidental_markup() -> None:
    text = """# R.A.I.N. Lab

**A private-by-default expert panel in a box for researchers, independent thinkers, and R&D teams.**

Ask a raw research question. R.A.I.N. Lab assembles multiple expert perspectives, grounds strong claims in papers or explicit evidence, and returns the strongest explanations, disagreements, and next moves.

Most tools help you find papers. R.A.I.N. Lab helps you think with a room full of experts.

James is the assistant inside R.A.I.N. Lab.

<p align="center">
  <img alt="R.A.I.N. Lab logo" src="assets/rain_lab.png" class="hero" />
</p>

<p align="center">
  <a href="README.vi.md">Tiếng Việt</a> •
  <a href="README.fr.md">Français</a> •
  <a href="README.zh-CN.md">简体中文</a>
</p>

## What It Does
"""

    assert _find_readme_chrome_index(text) == text.index("assets/rain_lab.png")


def test_readme_lead_story_order_detection() -> None:
    text = """# R.A.I.N. Lab

**A private-by-default expert panel in a box for researchers, independent thinkers, and R&D teams.**

Ask a raw research question. R.A.I.N. Lab assembles multiple expert perspectives, grounds strong claims in papers or explicit evidence, and returns the strongest explanations, disagreements, and next moves.

Most tools help you find papers. R.A.I.N. Lab helps you think with a room full of experts.

James is the assistant inside R.A.I.N. Lab.

<p align="center">
  <img alt="R.A.I.N. Lab logo" src="assets/rain_lab.png" class="hero" />
</p>

## What It Does
"""

    assert _lead_story_indexes(text) == sorted(_lead_story_indexes(text))


def test_readme_leads_with_research_panel_positioning(repo_root: Path) -> None:
    text = _read(repo_root, "README.md")

    heading = "# R.A.I.N. Lab"
    tagline = "A private-by-default expert panel in a box for researchers, independent thinkers, and R&D teams."
    product_summary = (
        "Ask a raw research question. R.A.I.N. Lab assembles multiple expert perspectives, grounds strong claims in papers or explicit evidence, and returns the strongest explanations, disagreements, and next moves."
    )
    expert_summary = "Most tools help you find papers. R.A.I.N. Lab helps you think with a room full of experts."
    assistant_line = "James is the assistant inside R.A.I.N. Lab"
    hosted_url = "https://lab.vers3dynamics.com"
    local_runner = "python rain_lab.py"
    first_section = "## What It Does"
    expected_sections = (
        "## What It Does",
        "## Try It Now",
        "## Who It Is For",
        "## What You Can Do",
        "## Why It Is Different",
        "## Local and Private Workflow",
        "## Features",
        "## Requirements",
        "## Documentation",
        "## For Developers",
    )

    for fragment in (heading, tagline, product_summary, expert_summary, assistant_line, hosted_url):
        assert fragment in text, f"README.md is missing required positioning marker: {fragment!r}"

    lead_story_indexes = _lead_story_indexes(text)
    heading_index, tagline_index, product_summary_index, expert_summary_index, assistant_line_index = lead_story_indexes
    chrome_index = _find_readme_chrome_index(text)
    hosted_url_index = text.index(hosted_url)
    local_runner_index = text.index(local_runner)
    first_section_index = text.index(first_section)

    assert lead_story_indexes == sorted(lead_story_indexes)
    assert assistant_line_index < chrome_index
    assert chrome_index < first_section_index
    assert hosted_url_index < local_runner_index

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
