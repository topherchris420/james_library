"""Recorded proposal routing and the opt-in host integration."""

from dataclasses import asdict
import json

import pytest

from james_library.judgment.benchmark import fixture_profiles, FixtureProvider, measure
from james_library.judgment.config import create_decision_router
from james_library.judgment.process import create_process_controller, MeetingProcessController, propose_next_step
from james_library.judgment.routing import DecisionRouter
from james_library.launcher.decision_cli import load_request, main
from james_library.utilities.session_replay import replay_recorded_judgments
from tests.test_decision_routing import allow, profile, request, router
from tests.test_judgment_artifact import _writer


def test_decisions_checkpoint_and_replay_with_no_provider_calls(tmp_path, monkeypatch):
    envelope = router().decide(request(), validator=allow)
    writer = _writer(tmp_path)
    writer.record_decision(envelope)
    assert writer.load()["decisions"][0]["selected"] == "CONTINUE"
    assert "state" not in writer.load()["decisions"][0]
    monkeypatch.setattr(DecisionRouter, "decide", lambda *a, **k: pytest.fail("live evaluation"))
    result = replay_recorded_judgments(writer.path)
    assert result["decisions"][0]["request_hash"] == envelope.request_hash
    payload = writer.load()
    payload["decisions"][0]["selected"] = "VERIFY"
    writer.path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="recorded_judgment_invalid"):
        replay_recorded_judgments(writer.path)


def test_default_configuration_never_loads_providers(monkeypatch):
    monkeypatch.delenv("RAIN_DECISION_MODE", raising=False)
    monkeypatch.delenv("RAIN_METACOGNITIVE_CONTROL", raising=False)
    assert create_decision_router().mode == "off"
    assert create_process_controller() is None


def test_configuration_modes_are_optional_and_missing_models_escalate(monkeypatch):
    monkeypatch.setenv("RAIN_DECISION_MODE", "cascade")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("RAIN_LAYA_CHECKPOINT", raising=False)
    r = create_decision_router()
    assert r.decide(request(), validator=allow).destination == "rain"


def test_process_disabled_preserves_existing_behavior():
    r = router()
    assert propose_next_step(r, state="unused", allowed_actions=("CONTINUE", "VERIFY"),
                             validator=allow, enabled=False) is None
    assert r.laya.calls == r.jev.calls == 0


def test_process_mode_cannot_mutate_workflow_and_records_before_return():
    from james_library.launcher.meeting_workflow import MeetingWorkflow
    workflow = MeetingWorkflow()
    before = asdict(workflow)
    records = []
    r = router(mode="laya")
    # Capture the exact process schema, then provision test-only calibration.
    original = r.decide
    def decide(req, **kwargs):
        r.profiles = (profile("laya", req),)
        return original(req, **kwargs)
    r.decide = decide
    result = propose_next_step(r, state="A bounded research step.", allowed_actions=("CONTINUE", "VERIFY"),
                               validator=allow, enabled=True, recorder=records.append, consequence="low")
    assert result is records[0] and result.selected == "CONTINUE"
    assert asdict(workflow) == before
    def broken_recorder(value):
        raise OSError("checkpoint unavailable")
    with pytest.raises(OSError):
        propose_next_step(r, state="A bounded research step.", allowed_actions=("CONTINUE", "VERIFY"),
                          validator=allow, enabled=True, recorder=broken_recorder, consequence="low")


def test_chat_controller_preserves_budget_and_requires_recorder():
    r = router()
    c = MeetingProcessController(r)
    assert c.suggest(turn_count=10, max_turns=10, verified_count=0, recorder=lambda x: None) is None
    assert c.suggest(turn_count=1, max_turns=10, verified_count=0, recorder=None) is None
    assert r.laya.calls == 0


def test_cli_request_and_replay(tmp_path, monkeypatch, capsys):
    payload = asdict(request())
    del payload["deterministic_choice"]
    payload["choices"] = dict(payload["choices"])
    payload["schema_version"] = "rain-bounded-request/v1"
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload))
    assert load_request(path) == request()
    monkeypatch.setattr("james_library.launcher.decision_cli.create_decision_router", router)
    assert main(["--request", str(path), "--output-dir", str(tmp_path)]) == 0
    artifact = next(tmp_path.glob("session_decision-*.json"))
    assert main(["--replay", str(artifact)]) == 0
    assert "RECORDED DECISION" in capsys.readouterr().out


def test_packet_cannot_claim_deterministic_authority(tmp_path):
    path = tmp_path / "bad.json"
    payload = asdict(request(deterministic_choice="CONTINUE"))
    payload["schema_version"] = "rain-bounded-request/v1"
    payload["choices"] = dict(payload["choices"])
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_request(path)


def test_fixture_benchmark_reports_handoffs_not_fabricated_rain_accuracy():
    from pathlib import Path
    cases = json.loads(Path("benchmark_data/bounded_decisions.json").read_text())
    fixtures = {c["request"]["state"]: c["fixture"] for c in cases}
    r = DecisionRouter(mode="cascade", compare=True, profiles=fixture_profiles(cases),
                       laya=FixtureProvider("laya", fixtures), jev=FixtureProvider("typesafe", fixtures))
    result = measure(cases, r)
    assert result["rain_deliberation_accuracy"] is None
    assert result["disagreement_rate"] > 0
    assert result["invalid_output_rate"] > 0
    assert result["escalated_to_rain"] > 0
    refusal = next(row for row in result["rows"] if row["case_id"] == "validator-refusal")
    assert refusal["destination"] == "rejected"


def test_process_hint_cannot_claim_an_unrecorded_proposal(tmp_path):
    writer = _writer(tmp_path)
    with pytest.raises(ValueError, match="recorded proposal"):
        writer.record_turn(agent_name="SYSTEM", content="fixed hint",
                           metadata={"bounded_decision_id": "unknown", "process_action": "CONTINUE"})
