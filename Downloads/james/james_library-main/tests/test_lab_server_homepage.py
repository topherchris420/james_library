import asyncio
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import lab_server.app as lab_app
import lab_server.research_panel as research_panel

RUNTIME_CANCELED_DETAIL = (
    "R.A.I.N. runtime canceled: the operation was canceled. "
    "Retry and verify LM Studio is running with a loaded model."
)
EXAMPLE_PROMPT = (
    "How should I interpret these conflicting findings, and what evidence "
    "separates the leading explanations?"
)
ROOM_FULL_OF_EXPERTS_TITLE = (
    "R.A.I.N. Lab | Ask a research question. Get a room full of experts."
)
PRIVATE_BY_DEFAULT_DESCRIPTION = (
    "Private by default, grounded in papers and explicit evidence."
)


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta_by_key: dict[tuple[str, str], str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        values = {name: value for name, value in attrs if value is not None}
        key_name = values.get("name")
        key_property = values.get("property")
        content = values.get("content")
        if content is None:
            return
        if key_name is not None:
            self.meta_by_key[("name", key_name)] = content
        if key_property is not None:
            self.meta_by_key[("property", key_property)] = content


def _read_meta_values(html: str) -> dict[tuple[str, str], str]:
    parser = _MetaParser()
    parser.feed(html)
    return parser.meta_by_key


def _read_json_ld_payload(html: str) -> dict[str, object]:
    match = re.search(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', html, re.S)
    assert match is not None
    return json.loads(match.group(1))


def _read_last_jsonl_payload(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    return json.loads(lines[-1])


def test_debate_endpoint_returns_structured_research_panel(monkeypatch) -> None:
    async def fake_run_research_panel(question: str) -> dict[str, object]:
        return {
            "question": question,
            "panel_title": "Bell Labs-style panel",
            "panel": [
                {
                    "agent_name": "Mechanism Hunter",
                    "role": "Mechanistic modeler",
                    "content": "The leading explanation points to magnetar activity [from web: Example Paper].",
                    "evidence_sources": ["Example Paper"],
                    "grounded": True,
                    "confidence": 0.86,
                }
            ],
            "synthesis": "Most evidence clusters around the magnetar explanation [from web: Example Paper].",
            "synthesis_evidence_sources": ["Example Paper"],
            "grounded": True,
            "confidence": 0.91,
        }

    monkeypatch.setattr(lab_app, "run_research_panel", fake_run_research_panel)
    client = TestClient(lab_app.app)

    response = client.post("/debate", json={"question": "What causes fast radio bursts?"})
    body = response.json()

    assert response.status_code == 200
    assert body["question"] == "What causes fast radio bursts?"
    assert body["panel_title"] == "Bell Labs-style panel"
    assert body["panel"][0]["agent_name"] == "Mechanism Hunter"
    assert body["panel"][0]["grounded"] is True
    assert body["synthesis"]
    assert body["grounded"] is True


@pytest.mark.parametrize(
    ("error_message", "expected_detail"),
    [
        (
            "R.A.I.N. runtime config error: file not found: missing.toml",
            "R.A.I.N. runtime config error: file not found: missing.toml",
        ),
        (
            "The operation was canceled.",
            RUNTIME_CANCELED_DETAIL,
        ),
        (
            "budget exceeded",
            "R.A.I.N. runtime error: unable to generate response.",
        ),
    ],
)
def test_debate_endpoint_translates_research_panel_failures(
    monkeypatch,
    error_message: str,
    expected_detail: str,
) -> None:
    async def fake_run_research_panel(question: str) -> dict[str, object]:
        raise RuntimeError(error_message)

    monkeypatch.setattr(lab_app, "run_research_panel", fake_run_research_panel)
    client = TestClient(lab_app.app, raise_server_exceptions=False)

    response = client.post("/debate", json={"question": "What causes fast radio bursts?"})

    assert response.status_code == 500
    assert response.json() == {"detail": expected_detail}


def test_debate_endpoint_surfaces_missing_runtime_config_detail(monkeypatch, tmp_path) -> None:
    missing_config = tmp_path / "missing-runtime.toml"

    async def fail_if_called(question: str) -> dict[str, object]:
        raise AssertionError("run_blackboard_lab should not be reached when runtime config is missing")

    monkeypatch.setenv("RAIN_RUNTIME_CONFIG", str(missing_config))
    monkeypatch.setattr(research_panel, "run_blackboard_lab", fail_if_called)
    client = TestClient(lab_app.app, raise_server_exceptions=False)

    response = client.post("/debate", json={"question": "What causes fast radio bursts?"})

    assert response.status_code == 500
    assert response.json() == {
        "detail": f"R.A.I.N. runtime config error: file not found: {missing_config.resolve()}"
    }


def test_debate_endpoint_translates_cancelled_error(monkeypatch) -> None:
    async def fake_run_research_panel(question: str) -> dict[str, object]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(lab_app, "run_research_panel", fake_run_research_panel)
    client = TestClient(lab_app.app, raise_server_exceptions=False)

    response = client.post("/debate", json={"question": "What causes fast radio bursts?"})

    assert response.status_code == 500
    assert response.json() == {"detail": RUNTIME_CANCELED_DETAIL}


def test_normalize_panel_note_extracts_grounding_metadata() -> None:
    normalized = research_panel._normalize_panel_note(
        {
            "agent_name": "Mechanism Hunter",
            "role": "Mechanistic modeler",
            "notes": (
                'Quoted support "coherent oscillatory inputs reduce cost" '
                "[from Local Paper.md] [from web: Example Site]."
            ),
        }
    )

    assert normalized["agent_name"] == "Mechanism Hunter"
    assert normalized["role"] == "Mechanistic modeler"
    assert normalized["grounded"] is True
    assert normalized["evidence_sources"] == ["Local Paper.md", "Example Site"]
    assert normalized["confidence"] == 0.71


def test_run_research_panel_normalizes_synthesis_provenance(monkeypatch) -> None:
    async def fake_run_blackboard_lab(**kwargs) -> dict[str, object]:
        return {
            "specialist_notes": [
                {
                    "agent_name": "Mechanism Hunter",
                    "role": "Mechanistic modeler",
                    "notes": "Magnetars remain strongest [from web: Example Paper].",
                }
            ],
            "synthesized_response": (
                '  Synthesis with "useful quoted support" [from Paper A.md] '
                "[from web: Example Paper].  "
            ),
        }

    monkeypatch.setattr(research_panel, "run_blackboard_lab", fake_run_blackboard_lab)

    result = asyncio.run(research_panel.run_research_panel("What causes fast radio bursts?"))

    assert result["question"] == "What causes fast radio bursts?"
    assert result["panel"][0]["evidence_sources"] == ["Example Paper"]
    assert result["synthesis"] == 'Synthesis with "useful quoted support" [from Paper A.md] [from web: Example Paper].'
    assert result["synthesis_evidence_sources"] == ["Paper A.md", "Example Paper"]
    assert result["grounded"] is True
    assert result["confidence"] == 0.71


def test_run_research_panel_writes_runtime_trace(monkeypatch, tmp_path) -> None:
    trace_path = tmp_path / "meeting_archives" / "runtime_events.jsonl"

    async def fake_run_blackboard_lab(**kwargs) -> dict[str, object]:
        return {
            "specialist_notes": [
                {
                    "agent_name": "Mechanism Hunter",
                    "role": "Mechanistic modeler",
                    "notes": "Magnetars remain strongest [from web: Example Paper].",
                }
            ],
            "synthesized_response": "A grounded synthesis [from web: Example Paper].",
        }

    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_ENABLED", "1")
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "qwen-test")
    monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)
    monkeypatch.setattr(research_panel, "run_blackboard_lab", fake_run_blackboard_lab)

    result = asyncio.run(research_panel.run_research_panel("What causes fast radio bursts?"))

    assert result["grounded"] is True
    assert trace_path.exists()

    payload = _read_last_jsonl_payload(trace_path)
    assert payload["status"] == "ok"
    assert payload["mode"] == "research_panel"
    assert payload["agent"] == "Bell Labs-style panel"
    assert payload["panel_count"] == 1
    assert payload["response"]["mode"] == "research_panel"
    assert payload["response"]["answer_chars"] > 0
    assert payload["response"]["provenance_count"] == 1


def test_homepage_shows_research_panel_positioning_and_no_longer_shows_coding_agent_copy() -> None:
    client = TestClient(lab_app.app)

    response = client.get("/")
    html = response.text

    assert response.status_code == 200
    assert "Ask a research question. Get a room full of experts." in html
    assert "Private by default. Strong claims tied to papers or explicit evidence." in html
    assert "expert panel in a box" in html
    assert "Different perspectives, not one flat answer" in html
    assert (
        "Search tools help you find papers. R.A.I.N. Lab helps you think with a "
        "room full of experts."
    ) in html
    assert "Read a paper written with R.A.I.N. Lab." in html
    assert 'href="https://topherchris420.github.io/research/"' in html
    assert f'placeholder="For example: {EXAMPLE_PROMPT}"' in html
    assert f'data-question="{EXAMPLE_PROMPT}"' in html
    assert re.search(
        (
            r'<button type="button" class="example-prompts__item" '
            r'data-question="How should I interpret these conflicting findings, '
            r'and what evidence separates the leading explanations\?">\s*'
            r"Conflicting findings\s*</button>"
        ),
        html,
    )
    assert "The local-first autonomous coding agent for Rust, Python, and hardware teams" not in html
    assert "Your engineering task or question" not in html
    assert "Run the task ->" not in html
    assert "fast radio bursts" not in html


def test_public_metadata_surfaces_reflect_research_panel_positioning() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    web_index = (repo_root / "web" / "index.html").read_text(encoding="utf-8")
    docs_override = (repo_root / "docs" / "overrides" / "main.html").read_text(encoding="utf-8")
    meta_values = _read_meta_values(web_index)
    json_ld = _read_json_ld_payload(docs_override)

    assert meta_values[("name", "description")] == (
        "A private-by-default expert panel in a box for researchers, independent thinkers, and R&D teams. "
        "It turns one research question into evidence-grounded debate and synthesis."
    )
    assert meta_values[("property", "og:title")] == ROOM_FULL_OF_EXPERTS_TITLE
    assert meta_values[("property", "og:description")] == PRIVATE_BY_DEFAULT_DESCRIPTION
    assert meta_values[("name", "twitter:title")] == ROOM_FULL_OF_EXPERTS_TITLE
    assert meta_values[("name", "twitter:description")] == (
        "A private-by-default expert panel in a box for researchers, independent thinkers, and R&D teams."
    )
    assert meta_values[("name", "description")].count("expert panel in a box") == 1
    assert "autonomous coding agent runtime" not in web_index

    assert json_ld["@type"] == "SoftwareApplication"
    assert json_ld["applicationCategory"] == "ResearchApplication"
    assert json_ld["applicationSubCategory"] == "Research Reasoning Software"
    assert json_ld["description"] == (
        "R.A.I.N. Lab is a private-by-default expert panel in a box for research reasoning. "
        "It turns one question into evidence-grounded debate and synthesis, "
        "with claims tied to papers and explicit evidence."
    )
    assert json_ld["audience"] == {
        "@type": "Audience",
        "audienceType": "Researchers, independent thinkers, and R&D teams",
    }
    assert json_ld["keywords"] == [
        "research reasoning software",
        "expert panel in a box",
        "private by default",
        "evidence-grounded synthesis",
        "papers and explicit evidence",
        "research debate",
        "scientific reasoning",
        "decision support",
        "R&D teams",
    ]
    assert json_ld["featureList"] == [
        "Private-by-default research sessions with explicit evidence tracking",
        "Evidence-grounded debate across multiple expert perspectives",
        "Synthesis that surfaces the strongest explanations, disagreements, and next moves",
        "Paper-backed claims and traceable support for review",
        "A broad research workflow for researchers, independent thinkers, and R&D teams",
    ]


def test_homepage_css_preserves_multiline_panel_text() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    css = (repo_root / "lab_server" / "static" / "homepage.css").read_text(encoding="utf-8")

    assert re.search(r"\.panel-card__content\s*\{[^}]*white-space:\s*pre-wrap;", css, re.S)
    assert re.search(r"#synthesis-text\s*\{[^}]*white-space:\s*pre-wrap;", css, re.S)
