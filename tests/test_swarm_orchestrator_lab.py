from pathlib import Path

from james_library.launcher.swarm_orchestrator import (
    BlackboardEntry,
    load_lab_roster,
    plan_subtasks,
    post_to_blackboard,
    synthesize_lab_answer,
)


def test_plan_subtasks_selects_matching_capabilities(tmp_path: Path) -> None:
    manifest_a = tmp_path / "agent_math.json"
    manifest_b = tmp_path / "agent_systems.json"
    manifest_a.write_text(
        """{
        "id": "math_agent",
        "capability_tags": ["statistics", "algebra"],
        "tool_scopes": ["analysis"],
        "domain_hints": ["physics"],
        "system_prompt": "You are a math specialist."
    }""",
        encoding="utf-8",
    )
    manifest_b.write_text(
        """{
        "id": "systems_agent",
        "capability_tags": ["distributed", "runtime"],
        "tool_scopes": ["systems"],
        "domain_hints": ["computer_science"],
        "system_prompt": "You are a systems specialist."
    }""",
        encoding="utf-8",
    )

    roster = load_lab_roster([manifest_a, manifest_b])
    tasks = plan_subtasks("Need distributed runtime reliability analysis", roster)

    assert [task.required_tags for task in tasks[:2]] == [("distributed",), ("runtime",)]


def test_blackboard_merge_order_and_conflict_detection() -> None:
    blackboard = {
        "query": "Is the protocol safe?",
        "subtasks": [],
        "agent_outputs": [],
        "consensus": "pending",
    }

    # Intentionally post out of order to verify deterministic ordering.
    post_to_blackboard(
        blackboard,
        BlackboardEntry(task_id="task_02", agent_id="agent_b", output="This is valid and safe.", confidence=0.8),
    )
    post_to_blackboard(
        blackboard,
        BlackboardEntry(task_id="task_01", agent_id="agent_a", output="I reject this as unsafe.", confidence=0.9),
    )
    post_to_blackboard(
        blackboard,
        BlackboardEntry(task_id="task_02", agent_id="agent_a", output="I reject this as invalid.", confidence=0.7),
    )

    report = synthesize_lab_answer(blackboard)

    ordered_pairs = [(entry.task_id, entry.agent_id) for entry in blackboard["agent_outputs"]]
    assert ordered_pairs == [("task_01", "agent_a"), ("task_02", "agent_a"), ("task_02", "agent_b")]
    assert blackboard["consensus"] == "conflicted"
    assert "task_02: conflicting polarity across agent conclusions." in report
