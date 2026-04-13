import json
from pathlib import Path

from james_library.utilities.memory_governance import (
    extract_review_candidates,
    update_review_queue,
)

TOPIC = "Could acoustic interference patterns guide molecular assembly the way DNA guides cell growth?"
CLAIM = "I disagree with the optimistic framing, but the cited paper keeps the mechanism plausible."


def _write_artifact(path: Path) -> Path:
    payload = {
        "schema_version": "rain-session-artifact/v1",
        "session_id": "sess-governed",
        "status": "completed",
        "topic": TOPIC,
        "model": "test-model",
        "recursive_depth": 1,
        "started_at": "2026-04-13T00:00:00Z",
        "completed_at": "2026-04-13T00:01:00Z",
        "library_path": ".",
        "log_path": "./meeting.log",
        "loaded_papers_count": 1,
        "loaded_papers": ["paper.md"],
        "metrics": {"citation_accuracy": 0.9},
        "summary": "Next step: run the thermal numbers and compare against the 10 µm target.",
        "turns": [
            {
                "index": 1,
                "timestamp": "2026-04-13T00:00:01Z",
                "agent": "James",
                "content": CLAIM,
                "metadata": {"verified_count": 1, "unverified_count": 0, "citation_rate": 1.0},
                "grounded_response": {
                    "answer": CLAIM,
                    "confidence": 0.82,
                    "provenance": ["paper.md"],
                    "evidence": [{"source": "paper.md", "quote": "quoted evidence"}],
                    "repro_steps": ["inspect artifact"],
                    "grounded": True,
                    "red_badge": False,
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_extract_review_candidates_builds_governed_memory_records(tmp_path: Path) -> None:
    artifact_path = _write_artifact(tmp_path / "artifact.json")

    candidates = extract_review_candidates(artifact_path)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source_type"] == "paper"
    assert candidate["status"] == "pending_review"
    assert candidate["confidence"] == 0.82
    assert candidate["acl"]["read"] == ["research", "founder"]
    assert candidate["provenance"] == ["paper.md"]


def test_update_review_queue_deduplicates_candidates(tmp_path: Path) -> None:
    artifact_path = _write_artifact(tmp_path / "artifact.json")
    queue_path = tmp_path / "memory_review_queue.json"

    first = update_review_queue(queue_path, extract_review_candidates(artifact_path))
    second = update_review_queue(queue_path, extract_review_candidates(artifact_path))

    assert len(first["items"]) == 1
    assert len(second["items"]) == 1
    assert second["items"][0]["status"] == "pending_review"


def test_extract_review_candidates_keeps_ungrounded_items_as_needs_evidence(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    payload = {
        "schema_version": "rain-session-artifact/v1",
        "session_id": "sess-ungrounded",
        "status": "completed",
        "topic": "resonance in simple everyday language",
        "model": "test-model",
        "recursive_depth": 1,
        "started_at": "2026-04-13T00:00:00Z",
        "completed_at": "2026-04-13T00:01:00Z",
        "library_path": ".",
        "log_path": "./meeting.log",
        "loaded_papers_count": 0,
        "loaded_papers": [],
        "metrics": {},
        "summary": "Interesting discussion.",
        "turns": [
            {
                "index": 1,
                "timestamp": "2026-04-13T00:00:01Z",
                "agent": "James",
                "content": "Resonance is like pushing a swing at the right time.",
                "metadata": {"verified_count": 0, "unverified_count": 1, "citation_rate": 0.0},
                "grounded_response": {
                    "answer": "Resonance is like pushing a swing at the right time.",
                    "confidence": 0.2,
                    "provenance": [],
                    "evidence": [],
                    "repro_steps": ["inspect artifact"],
                    "grounded": False,
                    "red_badge": True,
                },
            }
        ],
    }
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    candidates = extract_review_candidates(artifact_path)

    assert len(candidates) == 1
    assert candidates[0]["status"] == "needs_evidence"
    assert candidates[0]["source_type"] == "inference"


def test_extract_review_candidates_filters_low_signal_turns(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    payload = {
        "schema_version": "rain-session-artifact/v1",
        "session_id": "sess-noise",
        "status": "completed",
        "topic": "noise topic",
        "model": "test-model",
        "recursive_depth": 1,
        "started_at": "2026-04-13T00:00:00Z",
        "completed_at": "2026-04-13T00:01:00Z",
        "library_path": ".",
        "log_path": "./meeting.log",
        "loaded_papers_count": 0,
        "loaded_papers": [],
        "metrics": {},
        "summary": "",
        "turns": [
            {
                "index": 1,
                "timestamp": "2026-04-13T00:00:01Z",
                "agent": "James",
                "content": "Meeting adjourned. Great discussion everyone!",
                "metadata": {"verified_count": 0, "unverified_count": 1, "citation_rate": 0.0},
                    "grounded_response": {
                        "answer": "",
                        "confidence": 0.2,
                        "provenance": [],
                        "evidence": [],
                        "repro_steps": [],
                        "grounded": False,
                        "red_badge": True,
                    },
            },
            {
                "index": 2,
                "timestamp": "2026-04-13T00:00:02Z",
                "agent": "Jasmine",
                "content": "[Jasmine is processing... Let me gather my thoughts on this topic.]",
                "metadata": {"verified_count": 0, "unverified_count": 1, "citation_rate": 0.0},
                    "grounded_response": {
                        "answer": "",
                        "confidence": 0.2,
                        "provenance": [],
                        "evidence": [],
                        "repro_steps": [],
                        "grounded": False,
                        "red_badge": True,
                    },
            },
            {
                "index": 3,
                "timestamp": "2026-04-13T00:00:03Z",
                "agent": "Elena",
                "content": "The key unresolved issue is whether the bound closes under realistic noise.",
                "metadata": {"verified_count": 0, "unverified_count": 1, "citation_rate": 0.0},
                    "grounded_response": {
                        "answer": "",
                        "confidence": 0.2,
                        "provenance": [],
                        "evidence": [],
                        "repro_steps": [],
                        "grounded": False,
                        "red_badge": True,
                    },
            },
        ],
    }
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    candidates = extract_review_candidates(artifact_path)

    assert len(candidates) == 1
    assert "unresolved issue" in candidates[0]["candidate_memory"].lower()


def test_update_review_queue_prioritizes_failed_replay_cases(tmp_path: Path) -> None:
    artifact_path = _write_artifact(tmp_path / "artifact.json")
    queue_path = tmp_path / "memory_review_queue.json"
    replay_report = {
        "cases": [
            {
                "topic": TOPIC,
                "failures": [
                    "grounded_turn_ratio below threshold",
                    "actionability_score below threshold",
                ],
            }
        ]
    }

    queue = update_review_queue(
        queue_path,
        extract_review_candidates(artifact_path),
        replay_report=replay_report,
    )

    assert queue["items"][0]["replay_failures"] == [
        "grounded_turn_ratio below threshold",
        "actionability_score below threshold",
    ]
    assert queue["items"][0]["priority_score"] > 0


def test_update_review_queue_reads_failures_from_eval_cases_shape(tmp_path: Path) -> None:
    artifact_path = _write_artifact(tmp_path / "artifact.json")
    queue_path = tmp_path / "memory_review_queue.json"
    replay_report = {
        "cases": [{"topic": TOPIC}],
        "eval": {
            "cases": [
                {
                    "topic": TOPIC,
                    "failures": ["grounded_turn_ratio below threshold"],
                }
            ]
        },
    }

    queue = update_review_queue(
        queue_path,
        extract_review_candidates(artifact_path),
        replay_report=replay_report,
    )

    assert queue["items"][0]["replay_failures"] == ["grounded_turn_ratio below threshold"]
