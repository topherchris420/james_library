import json
import asyncio
import os
from pathlib import Path

import pytest

import rain_lab_runtime as runtime


def test_extract_provenance_local_and_web():
    text = (
        'This aligns with "coherent oscillatory inputs reduce cost" '
        "[from Location is a Dynamic Variable.md] and [from web: Teleportation - Wikipedia]."
    )
    prov = runtime._extract_provenance(text)

    sources = {(p.source_type, p.source) for p in prov}
    assert ("paper", "Location is a Dynamic Variable.md") in sources
    assert ("web", "Teleportation - Wikipedia") in sources
    assert len(prov) == 2


def test_confidence_score_penalizes_speculation_and_uncertainty():
    response = "[SPECULATION] not sure, papers don't cover this."
    prov = [runtime.ProvenanceItem(source="x.md", source_type="paper")]
    score = runtime._confidence_score(response, prov)
    assert 0.05 <= score < 0.5


def test_run_rain_lab_happy_path(monkeypatch, tmp_path):
    async_trace = tmp_path / "runtime_events.jsonl"

    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(async_trace))
    monkeypatch.setattr(
        runtime,
        "_load_context",
        lambda: ("--- paper.md ---\ncontent", ["paper.md"]),
    )
    monkeypatch.setattr(
        runtime,
        "_call_llm_sync",
        lambda *args, **kwargs: 'Answer with "quoted text" [from paper.md]',
    )

    out = asyncio.run(
        runtime.run_rain_lab(
            query="test query",
            mode="chat",
            agent="James",
            recursive_depth=1,
        )
    )

    assert "Confidence:" in out
    assert "Provenance:" in out
    assert async_trace.exists()

    lines = async_trace.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["status"] == "ok"
    assert payload["mode"] == "chat"
    assert payload["agent"] == "James"
    assert "events" in payload and payload["events"]


def test_run_rain_lab_error_path(monkeypatch, tmp_path):
    async_trace = tmp_path / "runtime_events_error.jsonl"
    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(async_trace))
    monkeypatch.setattr(runtime, "_load_context", lambda: ("", []))

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "_call_llm_sync", _raise)

    out = asyncio.run(runtime.run_rain_lab(query="test", mode="chat", agent=None, recursive_depth=1))
    assert "runtime error" in out.lower()
    assert async_trace.exists()


def test_run_rain_lab_canceled_path(monkeypatch, tmp_path):
    async_trace = tmp_path / "runtime_events_canceled.jsonl"
    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(async_trace))
    monkeypatch.setattr(runtime, "_load_context", lambda: ("", []))

    def _raise(*args, **kwargs):
        raise RuntimeError("The operation was canceled.")

    monkeypatch.setattr(runtime, "_call_llm_sync", _raise)

    out = asyncio.run(runtime.run_rain_lab(query="test", mode="chat", agent=None, recursive_depth=1))
    assert "runtime canceled" in out.lower()
    payload = json.loads(async_trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["status"] == "canceled"


def test_run_rain_lab_strict_grounding_blocks_ungrounded(monkeypatch, tmp_path):
    async_trace = tmp_path / "runtime_events_strict.jsonl"
    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(async_trace))
    monkeypatch.setenv("RAIN_STRICT_GROUNDING", "1")
    monkeypatch.setenv("RAIN_MIN_GROUNDED_CONFIDENCE", "0.8")
    monkeypatch.setattr(runtime, "_load_context", lambda: ("", []))
    monkeypatch.setattr(runtime, "_call_llm_sync", lambda *args, **kwargs: "Ungrounded answer")

    out = asyncio.run(runtime.run_rain_lab(query="test", mode="chat", agent="James", recursive_depth=1))
    assert "grounding policy blocked" in out.lower()
    assert "Grounded: no" in out

    payload = json.loads(async_trace.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["status"] == "blocked"
    assert payload["grounded"] is False


def test_runtime_healthcheck_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(tmp_path / "meeting_archives" / "runtime_events.jsonl"))

    result = runtime.runtime_healthcheck()
    assert "ok" in result
    assert "checks" in result
    assert "library_exists" in result["checks"]


def test_runtime_cli_main_success(monkeypatch, capsys, tmp_path):
    async def _fake_run_rain_lab(query, mode, agent, recursive_depth, config_path=None):
        assert query == "test topic"
        assert mode == "chat"
        assert recursive_depth == 2
        assert config_path is None
        return "Answer [from paper.md]\n\nConfidence: 0.70"

    monkeypatch.setattr(runtime, "run_rain_lab", _fake_run_rain_lab)
    rc = runtime.main(["--topic", "test topic", "--recursive-depth", "2", "--library", str(tmp_path)])

    assert rc == 0
    assert os.environ.get("JAMES_LIBRARY_PATH") == str(tmp_path)
    assert "Answer [from paper.md]" in capsys.readouterr().out


def test_runtime_cli_main_passes_config(monkeypatch, tmp_path):
    async def _fake_run_rain_lab(query, mode, agent, recursive_depth, config_path=None):
        assert config_path == "runtime.toml"
        return "Answer"

    monkeypatch.setattr(runtime, "run_rain_lab", _fake_run_rain_lab)
    rc = runtime.main(["--topic", "x", "--config", "runtime.toml", "--library", str(tmp_path)])
    assert rc == 0


def test_runtime_cli_main_requires_query(capsys):
    rc = runtime.main([])
    assert rc == 2
    assert "provide --topic or --query" in capsys.readouterr().out.lower()


def test_runtime_cli_main_blocked_exit(monkeypatch):
    async def _blocked(*args, **kwargs):
        return "Grounding policy blocked this answer."

    monkeypatch.setattr(runtime, "run_rain_lab", _blocked)
    rc = runtime.main(["--topic", "x"])
    assert rc == 2


def test_runtime_cli_main_canceled_exit(monkeypatch):
    async def _canceled(*args, **kwargs):
        return "R.A.I.N. runtime canceled: the operation was canceled."

    monkeypatch.setattr(runtime, "run_rain_lab", _canceled)
    rc = runtime.main(["--topic", "x"])
    assert rc == 3


def test_trace_path_defaults_inside_library(monkeypatch, tmp_path):
    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    monkeypatch.delenv("RAIN_RUNTIME_TRACE_PATH", raising=False)
    path = runtime._trace_log_path()
    assert str(path).startswith(str(tmp_path))


def test_trace_path_blocks_external_without_override(monkeypatch, tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    external = tmp_path / "external" / "trace.jsonl"
    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(library))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(external))
    monkeypatch.delenv("RAIN_ALLOW_EXTERNAL_TRACE_PATH", raising=False)

    path = runtime._trace_log_path()
    assert path == (library / "meeting_archives" / "runtime_events.jsonl")


def test_trace_path_allows_external_with_override(monkeypatch, tmp_path):
    library = tmp_path / "lib"
    library.mkdir()
    external = tmp_path / "external" / "trace.jsonl"
    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(library))
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(external))
    monkeypatch.setenv("RAIN_ALLOW_EXTERNAL_TRACE_PATH", "1")

    path = runtime._trace_log_path()
    assert path == external.resolve()


def test_load_runtime_config_from_toml(monkeypatch, tmp_path):
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        """
[runtime]
llm_retries = 4
return_json = true

[llm]
base_url = "http://127.0.0.1:11434/v1"
model = "qwen-test"
api_key = "toml-key"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.delenv("LM_STUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_MODEL", raising=False)
    monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)

    config = runtime._load_runtime_config(config_path=str(config_path))
    assert config.llm_retries == 4
    assert config.return_json is True
    assert config.llm_base_url == "http://127.0.0.1:11434/v1"
    assert config.llm_model == "qwen-test"
    assert config.llm_api_key == "toml-key"


def test_run_rain_lab_missing_api_key_for_remote_endpoint(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "https://api.example.com/v1")
    monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)

    out = asyncio.run(runtime.run_rain_lab(query="test", mode="chat", agent="James", recursive_depth=1))
    assert "missing api key" in out.lower()


def test_read_context_excerpt_matches_strip_slice(tmp_path):
    file_path = tmp_path / "a.md"
    raw = "  \n\t" + ("alpha " * 2000) + "   \n\n"
    file_path.write_text(raw, encoding="utf-8")

    for budget in [1, 5, 50, 1200, 12000]:
        assert runtime._read_context_excerpt(file_path, budget) == raw.strip()[:budget]


def test_load_context_matches_reference_logic(monkeypatch, tmp_path):
    files: dict[str, str] = {
        "b.md": "  beta content   ",
        "a.txt": "alpha",
        "ZZ_SOUL.md": "should be filtered",
        "NOTES_LOG.txt": "should be filtered",
        "_hidden.md": "should be filtered",
        "c.md": "gamma",
    }
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")

    monkeypatch.setenv("JAMES_LIBRARY_PATH", str(tmp_path))
    max_chars = 9
    max_files = 3

    context, names = runtime._load_context(max_chars=max_chars, max_files=max_files)

    def _reference(base: Path, budget: int, limit: int) -> tuple[str, list[str]]:
        selected = sorted(list(base.glob("*.md")) + list(base.glob("*.txt")))
        selected = [
            p
            for p in selected
            if "SOUL" not in p.name.upper() and "LOG" not in p.name.upper() and not p.name.startswith("_")
        ][:limit]

        ref_names: list[str] = []
        ref_chunks: list[str] = []
        remaining = budget
        for p in selected:
            text = p.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            ref_names.append(p.name)
            take = min(len(text), remaining)
            ref_chunks.append(f"--- {p.name} ---\n{text[:take]}")
            remaining -= take
            if remaining <= 0:
                break
        return "\n\n".join(ref_chunks), ref_names

    expected_context, expected_names = _reference(tmp_path, max_chars, max_files)
    assert context == expected_context
    assert names == expected_names
