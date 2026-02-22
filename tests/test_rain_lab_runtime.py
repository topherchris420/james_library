import json
import asyncio

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

    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(async_trace))
    monkeypatch.setattr(
        runtime,
        "_load_context",
        lambda: ("--- paper.md ---\ncontent", ["paper.md"]),
    )
    monkeypatch.setattr(
        runtime,
        "_call_llm_sync",
        lambda messages, timeout_s: 'Answer with "quoted text" [from paper.md]',
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
    monkeypatch.setenv("RAIN_RUNTIME_TRACE_PATH", str(async_trace))
    monkeypatch.setattr(runtime, "_load_context", lambda: ("", []))

    def _raise(messages, timeout_s):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "_call_llm_sync", _raise)

    out = asyncio.run(runtime.run_rain_lab(query="test", mode="chat", agent=None, recursive_depth=1))
    assert "runtime error" in out.lower()
    assert async_trace.exists()
