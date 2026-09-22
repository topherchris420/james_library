"""Typed judgments remain a separate, offline-replayable flight-recorder layer."""

import hashlib
import json

import pytest

from james_library.utilities.session_artifact import SessionArtifactWriter
from tests.judgment_helpers import evidence, service


def _writer(tmp_path):
    return SessionArtifactWriter(
        artifact_root=tmp_path,
        session_id="judgment-fixture",
        topic="bounded simulated claim",
        model="fixture",
        recursive_depth=1,
        library_path=str(tmp_path),
        log_path=str(tmp_path / "meeting.log"),
    )


def test_session_artifact_persists_judgment_separately_from_turns(tmp_path):
    evaluator, _ = service()
    envelope = evaluator.evaluate(evidence())
    writer = _writer(tmp_path)
    writer.record_judgment(envelope)
    checkpoint = writer.load()
    assert checkpoint["status"] == "in_progress"
    assert checkpoint["judgments"][0]["judgment_id"] == envelope.judgment_id
    writer.record_turn(agent_name="R.A.I.N.Reviewer", content="Peer score: 9", metadata={})
    writer.finalize(status="completed", metrics={"peer_critique_score": 9})
    payload = writer.load()
    assert len(payload["judgments"]) == 1
    assert payload["judgments"][0]["judgment_id"] == envelope.judgment_id
    assert payload["judgments"][0]["disposition"] == "PASS"
    assert payload["turns"][0]["content"] == "Peer score: 9"
    assert payload["judgments"][0]["state_hash"] == hashlib.sha256(
        payload["judgments"][0]["state"].encode("utf-8")
    ).hexdigest()


def test_artifact_rejects_untyped_judgment(tmp_path):
    with pytest.raises(TypeError, match="JudgmentEnvelope"):
        _writer(tmp_path).record_judgment({"disposition": "PASS"})


def test_recorded_replay_performs_zero_network_or_subprocess_calls(tmp_path, monkeypatch):
    from james_library.utilities import session_replay

    evaluator, _ = service()
    writer = _writer(tmp_path)
    writer.record_judgment(evaluator.evaluate(evidence()))
    path = writer.finalize(status="completed")
    monkeypatch.setenv("RAIN_JUDGMENT_PROVIDER", "typesafe")
    monkeypatch.setattr(session_replay.subprocess, "run", lambda *a, **k: pytest.fail("subprocess called"))
    monkeypatch.setattr("requests.sessions.Session.send", lambda *a, **k: pytest.fail("network called"))
    replay = session_replay.replay_recorded_judgments(path)
    assert replay["mode"] == "recorded_judgment"
    assert replay["session_id"] == "judgment-fixture"
    assert replay["judgments"][0]["disposition"] == "PASS"


def test_recorded_replay_detects_state_tampering(tmp_path):
    from james_library.utilities.session_replay import replay_recorded_judgments

    evaluator, _ = service()
    writer = _writer(tmp_path)
    writer.record_judgment(evaluator.evaluate(evidence()))
    path = writer.finalize(status="completed")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["judgments"][0]["state"] += "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="recorded_judgment_invalid"):
        replay_recorded_judgments(path)


def test_old_artifact_replays_with_no_judgments(tmp_path):
    from james_library.utilities.session_replay import replay_recorded_judgments

    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema_version": "rain-session-artifact/v1", "session_id": "old"}),
                    encoding="utf-8")
    assert replay_recorded_judgments(path)["judgments"] == []


def test_live_gold_replay_disables_remote_judgment_by_default(tmp_path):
    from james_library.utilities import session_replay

    gold = tmp_path / "gold.json"
    gold.write_text("[]", encoding="utf-8")
    report = session_replay.run_replay(
        gold_path=gold,
        artifact_dir=tmp_path / "artifacts",
        report_dir=tmp_path / "reports",
        library_path=tmp_path,
    )
    assert report["mode"] == "live_session_replay"
    assert report["judgment_mode"] == "disabled"
