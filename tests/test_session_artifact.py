from pathlib import Path
from types import SimpleNamespace
import io

from james_library.utilities.session_artifact import SessionArtifactWriter
import rain_lab_meeting_chat_version as meeting_module


def test_session_artifact_writer_persists_grounded_turns_and_metrics(tmp_path: Path) -> None:
    writer = SessionArtifactWriter(
        artifact_root=tmp_path,
        session_id="sess-1234",
        topic="phononic assembly",
        model="minimax-m2.7:cloud",
        recursive_depth=1,
        library_path=str(tmp_path / "library"),
        log_path=str(tmp_path / "RAIN_LAB_MEETING_LOG.md"),
        loaded_papers=["paper_a.md", "paper_b.md"],
    )

    writer.record_turn(
        agent_name="James",
        content='The DRR paper says "standing wave anchoring remains plausible".',
        metadata={
            "verified": [("standing wave anchoring remains plausible", "paper_a.md")],
            "unverified": [],
            "citation_rate": 1.0,
        },
    )

    artifact_path = writer.finalize(
        status="completed",
        metrics={"citation_accuracy": 1.0, "novel_claim_density": 0.25},
        summary="Session ended cleanly.",
    )

    payload = writer.load()

    assert artifact_path.exists()
    assert payload["schema_version"] == "rain-session-artifact/v1"
    assert payload["session_id"] == "sess-1234"
    assert payload["status"] == "completed"
    assert payload["metrics"]["citation_accuracy"] == 1.0
    assert payload["loaded_papers_count"] == 2
    assert payload["summary"] == "Session ended cleanly."

    turn = payload["turns"][0]
    assert turn["agent"] == "James"
    assert turn["grounded_response"]["grounded"] is True
    assert turn["grounded_response"]["red_badge"] is False
    assert turn["grounded_response"]["provenance"] == ["paper_a.md"]
    assert turn["grounded_response"]["evidence"][0]["quote"] == "standing wave anchoring remains plausible"


def test_session_artifact_writer_marks_ungrounded_turns(tmp_path: Path) -> None:
    writer = SessionArtifactWriter(
        artifact_root=tmp_path,
        session_id="sess-ungrounded",
        topic="free-energy claim",
        model="minimax-m2.7:cloud",
        recursive_depth=2,
        library_path=str(tmp_path / "library"),
        log_path=str(tmp_path / "RAIN_LAB_MEETING_LOG.md"),
        loaded_papers=[],
    )

    writer.record_turn(
        agent_name="Elena",
        content="The claim is satisfiable but not plausible.",
        metadata={"verified": [], "unverified": ["The claim is satisfiable but not plausible."], "citation_rate": 0.0},
    )

    writer.finalize(status="interrupted")

    payload = writer.load()
    turn = payload["turns"][0]

    assert payload["status"] == "interrupted"
    assert turn["grounded_response"]["grounded"] is False
    assert turn["grounded_response"]["red_badge"] is True
    assert turn["metadata"]["verified_count"] == 0
    assert turn["metadata"]["unverified_count"] == 1


def test_run_meeting_writes_session_artifact_with_grounded_turn(tmp_path: Path, monkeypatch) -> None:
    config = meeting_module.Config(
        library_path=str(tmp_path),
        meeting_log="RAIN_LAB_MEETING_LOG.md",
        max_turns=1,
        wrap_up_turns=0,
        enable_web_search=False,
        export_tts_audio=False,
        verbose=False,
        model_name="test-model",
    )
    orchestrator = meeting_module.RainLabOrchestrator(config)

    fake_agent = SimpleNamespace(
        name="James",
        role="Lead Scientist",
        color="",
        citations_made=0,
        load_soul=lambda *args, **kwargs: None,
    )
    orchestrator.team = [fake_agent]
    orchestrator.test_connection = lambda: True
    orchestrator.context_manager.get_library_context = lambda verbose=False: ("context block", ["paper.md"])
    orchestrator.context_manager.loaded_papers = {"paper.md": "quoted evidence"}
    orchestrator.web_search_manager.enabled = False
    orchestrator.get_last_meeting_summary = lambda: ""
    orchestrator._start_visual_conversation = lambda topic: None
    orchestrator._end_visual_conversation = lambda: None
    orchestrator.diplomat = SimpleNamespace(check_inbox=lambda: None)
    orchestrator._generate_agent_response = (
        lambda current_agent, full_context, history_log, turn_count, topic, is_wrap_up=False: (
            '"quoted evidence" proves the point.',
            {},
        )
    )
    fake_citation_analyzer = SimpleNamespace(
        analyze_response=lambda agent_name, response: {
            "verified": [("quoted evidence", "paper.md")],
            "unverified": [],
            "citation_rate": 1.0,
        },
        get_stats=lambda: "Citation Rate: 1/1 (100.0% verified)",
    )
    monkeypatch.setattr(meeting_module, "CitationAnalyzer", lambda context_manager: fake_citation_analyzer)

    class _NoKeypress:
        @staticmethod
        def kbhit() -> bool:
            return False

    class _FakeStdout(io.StringIO):
        encoding = "utf-8"

        def reconfigure(self, **kwargs) -> None:
            return None

    fake_clock = {"value": 0.0}

    def _fake_time() -> float:
        current = fake_clock["value"]
        fake_clock["value"] += 2.0
        return current

    monkeypatch.setattr(meeting_module, "msvcrt", _NoKeypress())
    monkeypatch.setattr(meeting_module.time, "time", _fake_time)
    monkeypatch.setattr(meeting_module.time, "sleep", lambda _: None)

    stdout = _FakeStdout()
    monkeypatch.setattr(meeting_module.sys, "stdout", stdout)

    orchestrator.run_meeting("test topic")

    artifacts = sorted((tmp_path / "meeting_archives" / "session_artifacts").glob("session_*.json"))
    assert artifacts, "expected run_meeting to emit a session artifact"

    payload = meeting_module.json.loads(artifacts[-1].read_text(encoding="utf-8"))
    grounded_turns = [
        turn
        for turn in payload["turns"]
        if turn["agent"] == "James" and turn["grounded_response"]["grounded"] is True
    ]

    assert payload["status"] == "completed"
    assert grounded_turns, "expected a grounded James turn in the meeting artifact"
    assert grounded_turns[0]["grounded_response"]["provenance"] == ["paper.md"]
