"""Exercise the real strict-cycle launcher using local evidence and typed fixtures."""

import json

import pytest


def packet():
    return {
        "schema_version": "rain-judgment-cycle/v1",
        "claim": "The measured peak is 40 Hz in the simulated setup.",
        "method": "Sweep 30 to 50 Hz.",
        "observations": "Three peaks at 40 Hz.",
        "quantitative_results": "Peaks [40, 40, 40] Hz; resolution 1 Hz.",
        "tool_evidence": "Run fixture-1 exported peaks [40, 40, 40].",
        "source_identifiers": ["fixture-1"],
        "known_limitations": "Simulation only.",
        "formal_logic_result": {"satisfiable": True, "model": {"peak": True}},
        "numerical_validation": {"passed": True, "details": "All peaks lie inside sweep bounds."},
        "synthesis_summary": "Peak repeats at 40 Hz; no physical replication.",
        "peer_critique": {"reviewer": "R.A.I.N.Reviewer", "score": 9, "feedback": "Narrow claim supported."},
    }


def test_strict_packet_rejects_unrelated_private_context(tmp_path):
    from james_library.launcher.judgment_cli import load_cycle

    data = packet()
    data["private_corpus"] = "Private material"
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_evidence_packet"):
        load_cycle(path)


@pytest.mark.parametrize("mutation", [
    lambda p: p["peer_critique"].update(score=True),
    lambda p: p["peer_critique"].update(score=8.5),
    lambda p: p["formal_logic_result"].update(satisfiable="true"),
    lambda p: p["numerical_validation"].update(passed="true"),
    lambda p: p.update(source_identifiers="corpus.md"),
    lambda p: p.update(claim=""),
    lambda p: p.update(schema_version="unknown"),
    lambda p: p.update(method={"private": "memory"}),
])
def test_malformed_packet_fails_before_network_or_artifacts(tmp_path, monkeypatch, mutation):
    from james_library.launcher import judgment_cli

    data = packet()
    mutation(data)
    source = tmp_path / "cycle.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "artifacts"
    monkeypatch.setattr(judgment_cli, "create_judgment_service", lambda: pytest.fail("provider constructed"))
    assert judgment_cli.main(["--evidence", str(source), "--output-dir", str(output)]) == 2
    assert not output.exists()


@pytest.mark.parametrize("provider_options,expected", [
    ({}, "PASS"), ({"support": "unsupported"}, "REVISE"),
    ({"confidence": 0.2}, "HUMAN_REVIEW"), ({"error_code": "provider_timeout"}, "UNAVAILABLE"),
])
def test_packet_runs_existing_five_stage_workflow(tmp_path, monkeypatch, capsys, provider_options, expected):
    from james_library.launcher import judgment_cli
    from tests.judgment_helpers import service

    evaluator, provider = service(**provider_options)
    monkeypatch.setattr(judgment_cli, "create_judgment_service", lambda: evaluator)
    source = tmp_path / "cycle.json"
    source.write_text(json.dumps(packet()), encoding="utf-8")
    output = tmp_path / "artifacts"
    result = judgment_cli.main(["--evidence", str(source), "--output-dir", str(output)])
    assert result == (0 if expected == "PASS" else 1)
    text = capsys.readouterr().out
    assert "Peer critique: 9 / 10" in text
    assert expected in text
    assert len(provider.calls) == 1
    artifact = json.loads(next(output.glob("session_*.json")).read_text(encoding="utf-8"))
    assert artifact["metrics"]["peer_critique_score"] == 9
    assert artifact["metrics"]["discovery_accepted"] is (expected == "PASS")
    assert len(artifact["judgments"]) == 1


def test_cli_disabled_gate_preserves_score_only_promotion(tmp_path, monkeypatch, capsys):
    from james_library.launcher import judgment_cli

    monkeypatch.setattr(judgment_cli, "create_judgment_service", lambda: None)
    data = packet()
    data.pop("formal_logic_result")
    data.pop("numerical_validation")
    source = tmp_path / "cycle.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    assert judgment_cli.main(["--evidence", str(source), "--output-dir", str(tmp_path / "artifacts")]) == 0
    assert "DISABLED" in capsys.readouterr().out


@pytest.mark.parametrize("validation", ["formal_logic_result", "numerical_validation"])
def test_failed_instruments_cannot_be_rescued_by_model(tmp_path, monkeypatch, validation):
    from james_library.launcher import judgment_cli
    from tests.judgment_helpers import service

    evaluator, _ = service()
    monkeypatch.setattr(judgment_cli, "create_judgment_service", lambda: evaluator)
    data = packet()
    data[validation] = {"satisfiable": False} if validation == "formal_logic_result" else {"passed": False}
    source = tmp_path / "cycle.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "artifacts"
    assert judgment_cli.main(["--evidence", str(source), "--output-dir", str(output)]) == 1
    artifact = json.loads(next(output.glob("session_*.json")).read_text(encoding="utf-8"))
    assert artifact["metrics"]["discovery_accepted"] is False


def test_packet_duplicate_keys_and_oversize_are_rejected(tmp_path):
    from james_library.launcher.judgment_cli import load_cycle

    source = tmp_path / "cycle.json"
    for content in ('{"claim":"a","claim":"b"}', " " * 131073):
        source.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="invalid_evidence_packet"):
            load_cycle(source)


def test_packet_with_configured_secret_is_never_persisted(tmp_path, monkeypatch, capsys):
    from james_library.launcher import judgment_cli

    secret = "fixture-credential-never-real"
    monkeypatch.setenv("TYPESAFE_API_KEY", secret)
    data = packet()
    data["claim"] += secret
    source = tmp_path / "cycle.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "artifacts"
    assert judgment_cli.main(["--evidence", str(source), "--output-dir", str(output)]) == 2
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert not output.exists()


def test_launcher_routes_judge_without_starting_a_conversation(monkeypatch):
    from james_library.launcher import rain_lab, judgment_cli

    received = []
    monkeypatch.setattr(judgment_cli, "main", lambda args: received.append(args) or 0)
    assert rain_lab.main(["judge", "--help"]) == 0
    assert received == [["--help"]]
