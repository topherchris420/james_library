import json
from pathlib import Path

from james_library.utilities.session_eval import (
    evaluate_artifact,
    evaluate_artifacts_against_gold,
    load_gold_cases,
)

TOPIC = "Could acoustic interference patterns guide molecular assembly the way DNA guides cell growth?"


def _turn_payload(*, index: int, agent: str, content: str, grounded: bool) -> dict[str, object]:
    return {
        "index": index,
        "timestamp": f"2026-04-13T00:00:0{index}Z",
        "agent": agent,
        "content": content,
        "metadata": {
            "verified_count": 1 if grounded else 0,
            "unverified_count": 0 if grounded else 1,
            "citation_rate": 1.0 if grounded else 0.0,
        },
        "grounded_response": {
            "answer": content,
            "confidence": 0.8 if grounded else 0.2,
            "provenance": ["paper.md"] if grounded else [],
            "evidence": [{"source": "paper.md", "quote": "quoted evidence"}] if grounded else [],
            "repro_steps": ["inspect artifact"],
            "grounded": grounded,
            "red_badge": not grounded,
        },
    }


def _write_artifact(path: Path, topic: str, grounded: bool, disagreement_text: str, next_step_text: str) -> Path:
    payload = {
        "schema_version": "rain-session-artifact/v1",
        "session_id": "sess-1",
        "status": "completed",
        "topic": topic,
        "model": "test-model",
        "recursive_depth": 1,
        "started_at": "2026-04-13T00:00:00Z",
        "completed_at": "2026-04-13T00:01:00Z",
        "library_path": ".",
        "log_path": "./meeting.log",
        "loaded_papers_count": 1,
        "loaded_papers": ["paper.md"],
        "metrics": {"citation_accuracy": 0.8},
        "summary": next_step_text,
        "turns": [
            _turn_payload(index=1, agent="James", content=disagreement_text, grounded=grounded),
            _turn_payload(index=2, agent="Elena", content=next_step_text, grounded=grounded),
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_evaluate_artifact_scores_grounding_disagreement_and_actionability(tmp_path: Path) -> None:
    artifact_path = _write_artifact(
        tmp_path / "artifact.json",
        topic=TOPIC,
        grounded=True,
        disagreement_text=(
            "I disagree with the optimistic framing, but the cited paper keeps "
            "the mechanism plausible."
        ),
        next_step_text=(
            "Next step: run the thermal numbers and measure whether the 10 Âµm "
            "target survives."
        ),
    )

    result = evaluate_artifact(artifact_path)

    assert result["topic"]
    assert result["grounded_turn_ratio"] == 1.0
    assert result["disagreement_score"] > 0.0
    assert result["actionability_score"] > 0.0
    assert result["overall_score"] > 0.7


def test_evaluate_artifacts_against_gold_flags_failures(tmp_path: Path) -> None:
    artifact_path = _write_artifact(
        tmp_path / "artifact.json",
        topic=TOPIC,
        grounded=False,
        disagreement_text="This sounds fine.",
        next_step_text="Interesting discussion.",
    )
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps(
            [
                {
                    "id": "phononic-assembly",
                    "topic": TOPIC,
                    "min_grounded_turn_ratio": 0.5,
                    "require_disagreement": True,
                    "min_actionability_score": 0.5,
                }
            ]
        ),
        encoding="utf-8",
    )

    gold_cases = load_gold_cases(gold_path)
    report = evaluate_artifacts_against_gold([artifact_path], gold_cases)

    assert report["summary"]["matched_cases"] == 1
    assert report["summary"]["passing_cases"] == 0
    assert report["cases"][0]["passed"] is False
    assert "grounded_turn_ratio" in " ".join(report["cases"][0]["failures"])
