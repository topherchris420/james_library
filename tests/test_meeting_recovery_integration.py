"""Run the real meeting loop with deterministic, offline agent responses."""

import itertools
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import rain_lab_meeting_chat_version as meeting


@pytest.fixture
def offline_meeting(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting, "VoiceEngine", Mock)
    monkeypatch.setattr(meeting, "HypergraphManager", Mock)
    monkeypatch.setattr(meeting, "MetricsTracker", None)
    monkeypatch.setattr(meeting.openai, "OpenAI", Mock)
    monkeypatch.setattr(meeting, "msvcrt", SimpleNamespace(kbhit=lambda: False))
    monkeypatch.setattr(meeting.select, "select", lambda *args: ([], [], []))
    clock = itertools.count(step=2)
    monkeypatch.setattr(meeting.time, "time", lambda: next(clock))
    monkeypatch.setattr(meeting.time, "sleep", lambda _: None)
    config = meeting.Config(
        library_path=str(tmp_path),
        max_turns=30,
        wrap_up_turns=4,
        enable_web_search=False,
        enable_citation_tracking=False,
        export_tts_audio=False,
        emit_visual_events=False,
        recursive_intellect=False,
    )
    lab = meeting.RainLabOrchestrator(config)
    lab.test_connection = lambda: True
    lab.context_manager.get_library_context = lambda **kwargs: ("Local research context", ["paper.md"])
    lab.context_manager.loaded_papers = {"paper.md": "Local research context"}
    lab.get_last_meeting_summary = lambda: ""
    lab.diplomat = SimpleNamespace(check_inbox=lambda: None)
    for agent in lab.team:
        agent.load_soul = lambda *args, **kwargs: None
    return lab


def run_responses(lab, content_for_turn):
    calls = []

    def respond(agent, context, history, turn, topic, is_wrap_up=False):
        calls.append({"agent": agent.name, "wrap_up": is_wrap_up, "history": list(history)})
        # Include changing speaker prefixes: recovery must compare the clean content.
        return f"{agent.name}: {content_for_turn(turn)}", {}

    lab._generate_agent_response = respond
    lab.run_meeting("Acoustic research question")
    return calls, lab.session_artifact_writer.load()


def test_persistent_loop_ends_early_with_a_full_panel_summary_and_ordered_artifact(offline_meeting):
    calls, artifact = run_responses(offline_meeting, lambda _: "The standing wave forms a nodal pattern.")

    assert len(calls) == 18  # 14 discussion turns, then 4 closing turns, within the 30-turn budget.
    assert not any(call["wrap_up"] for call in calls[:-4])
    assert all(call["wrap_up"] for call in calls[-4:])
    assert len({call["agent"] for call in calls[-4:]}) == 4
    interventions = [turn for turn in artifact["turns"] if turn["agent"] == "SYSTEM"]
    assert [turn["metadata"]["recovery"]["action"] for turn in interventions] == ["evidence", "alternative", "wrap_up"]
    assert all(turn["metadata"]["recovery"]["reason"] == "dead_end" for turn in interventions)
    for turn in interventions:
        previous = artifact["turns"][turn["index"] - 2]
        assert previous["agent"] != "SYSTEM"
        assert "The standing wave" in previous["content"]
    assert any("Adaptive recovery (evidence" in entry for entry in calls[4]["history"])
    assert artifact["status"] == "completed"


def test_normal_wrap_up_suppresses_recovery_and_preserves_configured_budget(offline_meeting):
    offline_meeting.config.max_turns = 6
    calls, artifact = run_responses(offline_meeting, lambda _: "The same conclusion.")

    assert len(calls) == 6
    assert sum(call["wrap_up"] for call in calls) == 4
    assert not any(turn["agent"] == "SYSTEM" for turn in artifact["turns"])


@pytest.mark.parametrize("max_turns,wrap_up_turns,expected", [(30, 0, 14), (16, 4, 16), (15, 1, 15)])
def test_recovery_never_extends_the_turn_budget(offline_meeting, max_turns, wrap_up_turns, expected):
    offline_meeting.config.max_turns = max_turns
    offline_meeting.config.wrap_up_turns = wrap_up_turns
    calls, _ = run_responses(offline_meeting, lambda _: "The same conclusion.")
    assert len(calls) == expected
    assert sum(call["wrap_up"] for call in calls) == wrap_up_turns


def test_reusing_an_orchestrator_resets_the_recovery_episode(offline_meeting):
    first, _ = run_responses(offline_meeting, lambda _: "The same conclusion.")
    second, artifact = run_responses(offline_meeting, lambda _: "The same conclusion.")
    assert len(first) == len(second) == 18
    interventions = [turn for turn in artifact["turns"] if turn["agent"] == "SYSTEM"]
    assert interventions[0]["metadata"]["recovery"]["action"] == "evidence"


def test_recovery_reaches_the_prompt_without_becoming_a_panel_speaker(offline_meeting):
    lab = offline_meeting
    lab.director = meeting.RainLabDirector(lab.config, ["paper.md"])
    lab._animate_spinner = lambda *args, **kwargs: None
    captured = []

    def respond(**kwargs):
        captured.append(kwargs["user_msg"])
        return "The missing measurement is the temperature drift over time.", "stop"

    lab._create_response_content = respond
    lab._generate_agent_response(
        lab.team[1],
        "Research context",
        [
            "James: The measurement is incomplete.",
            "SYSTEM: Adaptive recovery (evidence; dead_end). Identify the missing measurement.",
        ],
        4,
        "Acoustic research question",
    )
    assert captured
    assert "Adaptive recovery (evidence; dead_end)" in captured[0]
    assert "with James" in captured[0] or "what James said" in captured[0]
    assert "with SYSTEM" not in captured[0]
    assert "what SYSTEM said" not in captured[0]
