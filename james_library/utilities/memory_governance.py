"""Governed-memory review queue built from session artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOW_SIGNAL_PATTERNS = (
    "meeting adjourned",
    "great discussion everyone",
    "is processing... let me gather my thoughts",
    "[search:",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _source_type(turn: dict[str, Any]) -> str:
    provenance = turn.get("grounded_response", {}).get("provenance", [])
    if provenance:
        return "paper"
    agent = str(turn.get("agent", "")).upper()
    if agent == "USER":
        return "user"
    return "inference"


def _acl_for_agent(agent_name: str) -> dict[str, list[str]]:
    if agent_name.lower() == "james":
        return {"read": ["research", "founder"], "write": ["maintainer"]}
    return {"read": ["research"], "write": ["maintainer"]}


def _fingerprint(session_id: str, turn_index: int, content: str) -> str:
    digest = hashlib.sha256(f"{session_id}:{turn_index}:{content}".encode("utf-8")).hexdigest()
    return digest[:16]


def _is_low_signal(content: str) -> bool:
    lowered = content.lower()
    return any(pattern in lowered for pattern in LOW_SIGNAL_PATTERNS)


def _replay_failures_for_topic(replay_report: dict[str, Any] | None, topic: str) -> list[str]:
    if not replay_report:
        return []
    candidate_sets = []
    if isinstance(replay_report.get("eval"), dict):
        candidate_sets.append(replay_report["eval"].get("cases", []))
    candidate_sets.append(replay_report.get("cases", []))

    normalized_topic = topic.strip()
    for cases in candidate_sets:
        for case in cases:
            if str(case.get("topic", "")).strip() == normalized_topic:
                return [str(failure) for failure in case.get("failures", [])]
    return []


def _priority_score(candidate: dict[str, Any]) -> int:
    score = 10
    if candidate["status"] == "pending_review":
        score += 20
    if candidate["status"] == "needs_evidence":
        score += 15
    score += int(float(candidate.get("confidence", 0.0)) * 20)
    for failure in candidate.get("replay_failures", []):
        if "grounded_turn_ratio" in failure:
            score += 40
        elif "actionability_score" in failure:
            score += 20
        else:
            score += 10
    return score


def extract_review_candidates(artifact_path: Path | str) -> list[dict[str, Any]]:
    payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    candidates: list[dict[str, Any]] = []

    for turn in payload.get("turns", []):
        grounded = bool(turn.get("grounded_response", {}).get("grounded"))
        content = str(turn.get("content", "")).strip()
        if not content or _is_low_signal(content):
            continue

        confidence = float(turn.get("grounded_response", {}).get("confidence", 0.0))
        created_at = _now()
        review_by = created_at + timedelta(days=7 if confidence < 0.85 else 30)
        expires_at = created_at + timedelta(days=30 if confidence < 0.85 else 90)
        session_id = str(payload.get("session_id", "unknown"))
        turn_index = int(turn.get("index", 0))

        candidates.append(
            {
                "id": _fingerprint(session_id, turn_index, content),
                "status": "pending_review" if grounded else "needs_evidence",
                "session_id": session_id,
                "topic": payload.get("topic", ""),
                "agent": turn.get("agent", ""),
                "turn_index": turn_index,
                "candidate_memory": content,
                "source_type": _source_type(turn),
                "confidence": round(confidence, 2),
                "provenance": turn.get("grounded_response", {}).get("provenance", []),
                "evidence": turn.get("grounded_response", {}).get("evidence", []),
                "review_by": _iso(review_by),
                "expires_at": _iso(expires_at),
                "acl": _acl_for_agent(str(turn.get("agent", ""))),
                "created_at": _iso(created_at),
                "artifact_path": str(Path(artifact_path)),
            }
        )

    return candidates


def update_review_queue(
    queue_path: Path | str,
    candidates: list[dict[str, Any]],
    *,
    replay_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    queue_path = Path(queue_path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    if queue_path.exists():
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    else:
        queue = {"schema_version": "rain-memory-review-queue/v1", "items": []}

    existing_ids = {item["id"] for item in queue.get("items", [])}
    for candidate in candidates:
        candidate = dict(candidate)
        candidate["replay_failures"] = _replay_failures_for_topic(replay_report, candidate["topic"])
        candidate["priority_score"] = _priority_score(candidate)
        if candidate["id"] in existing_ids:
            continue
        queue["items"].append(candidate)
        existing_ids.add(candidate["id"])

    queue["items"].sort(key=lambda item: (-int(item.get("priority_score", 0)), item.get("review_by", "")))
    queue["updated_at"] = _iso(_now())
    queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    return queue


def _discover_artifacts(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("session_*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed-memory review queue from session artifacts.")
    parser.add_argument(
        "--artifact",
        type=str,
        default=None,
        help="Single session artifact JSON to ingest.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=str,
        default="meeting_archives/session_artifacts",
        help="Directory of session artifacts to scan.",
    )
    parser.add_argument(
        "--queue",
        type=str,
        default="state/memory_review_queue.json",
        help="Governed-memory review queue output path.",
    )
    parser.add_argument(
        "--replay-report",
        type=str,
        default=None,
        help="Optional replay report JSON used to prioritize queue items.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    artifacts = _discover_artifacts(Path(args.artifact) if args.artifact else Path(args.artifacts_dir))
    all_candidates: list[dict[str, Any]] = []
    for artifact in artifacts:
        all_candidates.extend(extract_review_candidates(artifact))

    replay_report = None
    if args.replay_report:
        replay_report = json.loads(Path(args.replay_report).read_text(encoding="utf-8"))

    queue = update_review_queue(args.queue, all_candidates, replay_report=replay_report)

    if args.json:
        print(json.dumps(queue, indent=2))
        return 0

    print("R.A.I.N. Governed Memory")
    print(f"Artifacts scanned: {len(artifacts)}")
    print(f"Queue items: {len(queue['items'])}")
    print(f"Queue path: {Path(args.queue).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
