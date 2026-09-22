"""Offline corpus-boundary and citation-span tests. No model process."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from james_library.utilities.citation_corpus import (
    citation_console_status,
    discover_corpus_files,
    resolve_corpus_root,
)
from james_library.utilities.session_artifact import SessionArtifactWriter
import rain_lab_meeting_chat_version as meeting


UNIQUE = "Zed corpus token alpha refuses readme substitution in this sentence."
PREFIX = " ".join(UNIQUE.split()[:5])


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo_like(tmp_path: Path) -> Path:
    _write(tmp_path / "README.md", f"# Product\n\n{UNIQUE}\n")
    _write(tmp_path / "JAMES_SOUL.md", "soul text that must not be a paper")
    _write(tmp_path / "docs" / "pitch.md", f"marketing copy {UNIQUE}")
    _write(tmp_path / "START_HERE.md", "start here is not a paper")
    return tmp_path


def test_readme_only_quote_is_not_a_verified_citation(tmp_path: Path) -> None:
    library = _repo_like(tmp_path)
    config = meeting.Config(library_path=str(library), include_product_surface=False, corpus_dir=None)
    manager = meeting.ContextManager(config)
    context, papers = manager.get_library_context(verbose=False)

    assert "README.md" not in papers
    assert all("docs/" not in name and not name.upper().startswith("README") for name in papers)
    assert UNIQUE not in context

    match = manager.verify_citation(UNIQUE)
    assert match is None

    discovered = discover_corpus_files(resolve_corpus_root(library))
    assert all(path.name != "README.md" for path in discovered)


def test_designated_corpus_quote_verifies_with_filename_and_span(tmp_path: Path) -> None:
    library = _repo_like(tmp_path)
    paper = library / "papers" / "note.md"
    body = f"Intro paragraph.\n\n{UNIQUE}\n\nClosing."
    _write(paper, body)

    config = meeting.Config(library_path=str(library), corpus_dir=str(library / "papers"))
    manager = meeting.ContextManager(config)
    _context, papers = manager.get_library_context(verbose=False)

    assert papers == ["note.md"]
    match = manager.verify_citation(UNIQUE)
    assert match is not None
    assert match.source == "note.md"
    loaded = manager.loaded_papers["note.md"]
    assert loaded[match.span_start : match.span_end] == UNIQUE

    # A longer sentence that only shares a five-word prefix must not verify.
    longer = f"{PREFIX} not present anywhere in the corpus file"
    assert manager.verify_citation(longer) is None


def test_whitespace_and_case_still_require_the_full_quote(tmp_path: Path) -> None:
    library = tmp_path / "only_papers"
    text = "Prefix Zed   Corpus Token alpha refuses readme substitution in this sentence. Suffix"
    _write(library / "note.md", text)
    config = meeting.Config(library_path=str(library), corpus_dir=str(library))
    manager = meeting.ContextManager(config)
    manager.get_library_context(verbose=False)
    match = manager.verify_citation(UNIQUE.lower())
    assert match is not None
    snippet = manager.loaded_papers["note.md"][match.span_start : match.span_end]
    assert " ".join(snippet.split()).lower() == UNIQUE.lower()


def test_require_quotes_stores_ungrounded_and_does_not_print_success(tmp_path: Path, capsys) -> None:
    library = tmp_path / "corpus"
    _write(library / "note.md", "This file discusses unrelated laboratory fixtures only.")
    config = meeting.Config(
        library_path=str(library),
        corpus_dir=str(library),
        require_quotes=True,
        enable_web_search=False,
    )
    manager = meeting.ContextManager(config)
    manager.get_library_context(verbose=False)
    analyzer = meeting.CitationAnalyzer(manager)
    response = f'The paper says "{UNIQUE}" and that settles it.'
    metadata = analyzer.analyze_response("Elena", response)

    assert metadata["require_quotes"] is True
    assert metadata["citation_success"] is False
    assert metadata["verified"] == []
    assert citation_console_status(metadata) == "ungrounded"

    status = citation_console_status(metadata)
    buffer = io.StringIO()
    if status == "verified":
        buffer.write(f"✓ {len(metadata['verified'])} citation(s) verified")
    elif status == "ungrounded":
        buffer.write("ungrounded: required quote did not match the corpus")
    printed = buffer.getvalue()
    assert "citation(s) verified" not in printed
    assert "ungrounded" in printed

    writer = SessionArtifactWriter(
        artifact_root=tmp_path / "artifacts",
        session_id="sess-ungrounded",
        topic="corpus boundary",
        model="offline-test",
        recursive_depth=0,
        library_path=str(library),
        log_path=str(tmp_path / "log.md"),
        loaded_papers=manager.paper_list,
        corpus_files=list(manager.corpus_hashes),
    )
    writer.record_turn(agent_name="Elena", content=response, metadata=metadata)
    writer.finalize(status="completed")
    payload = writer.load()
    turn = payload["turns"][0]
    assert turn["grounded_response"]["grounded"] is False
    assert turn["grounded_response"]["red_badge"] is True
    assert turn["metadata"]["citation_success"] is False
    assert payload["corpus_files"]
    assert payload["corpus_files"][0]["path"] == "note.md"
    expected = hashlib.sha256((library / "note.md").read_bytes()).hexdigest()
    assert payload["corpus_files"][0]["sha256"] == expected
    captured = capsys.readouterr()
    assert "citation(s) verified" not in captured.out


def test_verified_turn_records_span_and_success_status(tmp_path: Path) -> None:
    library = tmp_path / "corpus"
    _write(library / "note.md", f"Before. {UNIQUE} After.")
    config = meeting.Config(library_path=str(library), corpus_dir=str(library), require_quotes=True)
    manager = meeting.ContextManager(config)
    manager.get_library_context(verbose=False)
    metadata = meeting.CitationAnalyzer(manager).analyze_response("James", f'Quote: "{UNIQUE}"')

    assert metadata["citation_success"] is True
    assert citation_console_status(metadata) == "verified"
    assert metadata["verified_spans"][0]["source"] == "note.md"
    assert metadata["verified_spans"][0]["span_start"] >= 0
    assert metadata["verified_spans"][0]["span_end"] > metadata["verified_spans"][0]["span_start"]

    writer = SessionArtifactWriter(
        artifact_root=tmp_path / "artifacts",
        session_id="sess-grounded",
        topic="span",
        model="offline-test",
        recursive_depth=0,
        library_path=str(library),
        log_path=str(tmp_path / "log.md"),
        loaded_papers=["note.md"],
        corpus_files=list(manager.corpus_hashes),
    )
    writer.record_turn(agent_name="James", content=f'Quote: "{UNIQUE}"', metadata=metadata)
    writer.finalize(status="completed")
    evidence = writer.load()["turns"][0]["grounded_response"]["evidence"][0]
    assert evidence["source"] == "note.md"
    assert evidence["span_start"] == metadata["verified_spans"][0]["span_start"]
    assert evidence["span_end"] == metadata["verified_spans"][0]["span_end"]
    assert writer.load()["turns"][0]["grounded_response"]["grounded"] is True


def test_rlm_host_selection_uses_corpus_discovery() -> None:
    source = Path("rain_lab_meeting.py").read_text(encoding="utf-8")
    assert "def _corpus_candidate_files" in source
    assert "discover_corpus_files" in source
    assert "def _host_select_files" in source
    host = source.split("def _host_select_files", 1)[1].split("def _host_snippets", 1)[0]
    assert "_corpus_candidate_files()" in host
    assert 'lib.glob("*.md")' not in host
