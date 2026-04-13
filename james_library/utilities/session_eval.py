"""Artifact-based evaluation for R.A.I.N. Lab session outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DISAGREEMENT_MARKERS = (
    "disagree",
    "counter",
    "however",
    "but ",
    "not plausible",
    "reality-check",
    "wrong",
)

ACTIONABILITY_MARKERS = (
    "next step",
    "measure",
    "run ",
    "test ",
    "validate",
    "pull ",
    "compare",
    "check ",
)

NON_AGENT_NAMES = {"USER", "FOUNDER", "SYSTEM"}


def load_artifact(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_gold_cases(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _is_agent_turn(turn: dict[str, Any]) -> bool:
    return str(turn.get("agent", "")).upper() not in NON_AGENT_NAMES


def _marker_score(texts: list[str], markers: tuple[str, ...]) -> float:
    if not texts:
        return 0.0
    hits = 0
    for text in texts:
        lowered = text.lower()
        if any(marker in lowered for marker in markers):
            hits += 1
    return round(hits / len(texts), 2)


def evaluate_artifact(path: Path | str) -> dict[str, Any]:
    artifact_path = Path(path)
    payload = load_artifact(artifact_path)
    turns = payload.get("turns", [])
    agent_turns = [turn for turn in turns if _is_agent_turn(turn)]

    grounded_turns = [
        turn
        for turn in agent_turns
        if bool(turn.get("grounded_response", {}).get("grounded"))
    ]
    grounded_turn_ratio = round(len(grounded_turns) / len(agent_turns), 2) if agent_turns else 0.0

    texts = [str(turn.get("content", "")) for turn in agent_turns]
    disagreement_score = _marker_score(texts, DISAGREEMENT_MARKERS)
    actionability_score = _marker_score(texts + [str(payload.get("summary", ""))], ACTIONABILITY_MARKERS)

    citation_accuracy = float(payload.get("metrics", {}).get("citation_accuracy", grounded_turn_ratio))
    overall_score = round(
        (grounded_turn_ratio * 0.4)
        + (citation_accuracy * 0.25)
        + (disagreement_score * 0.2)
        + (actionability_score * 0.15),
        2,
    )

    return {
        "path": str(artifact_path),
        "topic": payload.get("topic", ""),
        "status": payload.get("status", ""),
        "agent_turn_count": len(agent_turns),
        "grounded_turn_ratio": grounded_turn_ratio,
        "disagreement_score": disagreement_score,
        "actionability_score": actionability_score,
        "citation_accuracy": round(citation_accuracy, 2),
        "overall_score": overall_score,
    }


def evaluate_artifacts_against_gold(
    artifact_paths: list[Path | str],
    gold_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    evaluations = [evaluate_artifact(path) for path in artifact_paths]
    eval_by_topic = {str(result["topic"]).strip(): result for result in evaluations}

    case_results: list[dict[str, Any]] = []
    passing_cases = 0
    for case in gold_cases:
        topic = str(case.get("topic", "")).strip()
        evaluation = eval_by_topic.get(topic)
        failures: list[str] = []

        if evaluation is None:
            failures.append("missing_artifact")
            passed = False
        else:
            if evaluation["grounded_turn_ratio"] < float(case.get("min_grounded_turn_ratio", 0.0)):
                failures.append("grounded_turn_ratio below threshold")
            if case.get("require_disagreement") and evaluation["disagreement_score"] <= 0.0:
                failures.append("missing disagreement signal")
            if evaluation["actionability_score"] < float(case.get("min_actionability_score", 0.0)):
                failures.append("actionability_score below threshold")
            passed = not failures

        if passed:
            passing_cases += 1

        case_results.append(
            {
                "id": case.get("id", topic),
                "topic": topic,
                "passed": passed,
                "failures": failures,
                "evaluation": evaluation,
            }
        )

    return {
        "summary": {
            "artifact_count": len(evaluations),
            "matched_cases": len(case_results),
            "passing_cases": passing_cases,
        },
        "artifacts": evaluations,
        "cases": case_results,
    }


def _discover_artifacts(artifact: str | None, artifacts_dir: str | None) -> list[Path]:
    if artifact:
        return [Path(artifact)]
    if artifacts_dir:
        return sorted(Path(artifacts_dir).glob("session_*.json"))
    return sorted((Path("meeting_archives") / "session_artifacts").glob("session_*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate R.A.I.N. session artifacts against a gold dataset.")
    parser.add_argument("--artifact", type=str, default=None, help="Single artifact JSON to score.")
    parser.add_argument("--artifacts-dir", type=str, default=None, help="Directory of session_*.json artifacts.")
    parser.add_argument(
        "--gold",
        type=str,
        default="benchmark_data/session_eval_gold.json",
        help="Gold prompt set JSON.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    args = parser.parse_args(argv)

    artifact_paths = _discover_artifacts(args.artifact, args.artifacts_dir)
    if not artifact_paths:
        raise SystemExit("No session artifacts found to evaluate.")

    report = evaluate_artifacts_against_gold(artifact_paths, load_gold_cases(args.gold))

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("R.A.I.N. Session Eval")
    print(f"Artifacts: {report['summary']['artifact_count']}")
    print(f"Matched gold cases: {report['summary']['matched_cases']}")
    print(f"Passing cases: {report['summary']['passing_cases']}")
    print("")
    for case in report["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        print(f"[{status}] {case['id']}: {case['topic']}")
        if case["failures"]:
            for failure in case["failures"]:
                print(f"  - {failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
