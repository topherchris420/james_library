"""Promote governed-memory review items into evidence-gathering remediation tasks."""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STOPWORDS = {
    "about",
    "after",
    "against",
    "around",
    "because",
    "before",
    "between",
    "could",
    "guide",
    "right",
    "their",
    "there",
    "these",
    "those",
    "under",
    "which",
    "would",
}

MIN_SUPPORT_MATCHES = 3
MIN_SUPPORT_RATIO = 0.35
MIN_BIGRAM_MATCHES = 1
MIN_FINAL_SUPPORT_SCORE = 0.45
MIN_ORDER_RATIO = 0.45
NEGATION_TERMS = ("not", "never", "no", "cannot", "can't", "without", "break down", "fails")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_id(review_item_id: str) -> str:
    return f"remediate-{review_item_id}"


def _build_task(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _task_id(item["id"]),
        "source_review_item_id": item["id"],
        "status": "pending",
        "task_type": "gather_evidence",
        "topic": item.get("topic", ""),
        "candidate_memory": item.get("candidate_memory", ""),
        "failure_focus": item.get("replay_failures", []),
        "priority_score": item.get("priority_score", 0),
        "suggested_query": f'{item.get("topic", "")} evidence for "{item.get("candidate_memory", "")[:120]}"',
        "created_at": _iso_now(),
    }


def _candidate_files(library_path: Path) -> list[Path]:
    excluded = {".git", "__pycache__", "node_modules", "meeting_archives", "state", ".venv", "venv", "target"}
    files: list[Path] = []
    for path in library_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in excluded for part in path.parts):
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        if "papers" not in path.parts:
            continue
        files.append(path)
    return files


def _query_terms(task: dict[str, Any]) -> list[str]:
    raw = task.get("candidate_memory", "")
    terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", raw.lower())
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        if term in STOPWORDS:
            continue
        if term in seen:
            continue
        seen.add(term)
        ordered.append(term)
    return ordered[:16]


def _claim_bigrams(terms: list[str]) -> list[str]:
    return [f"{terms[i]} {terms[i + 1]}" for i in range(len(terms) - 1)]


def _has_negation(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in NEGATION_TERMS)


def _anchor_phrases(terms: list[str]) -> list[str]:
    anchors: list[str] = []
    for size in (3, 2):
        for i in range(len(terms) - size + 1):
            phrase = " ".join(terms[i : i + size])
            anchors.append(phrase)
    deduped: list[str] = []
    seen: set[str] = set()
    for phrase in anchors:
        if phrase in seen:
            continue
        seen.add(phrase)
        deduped.append(phrase)
    return deduped[:8]


def _best_snippet(text: str, terms: list[str]) -> tuple[float, str]:
    best_score = 0.0
    best_snippet = ""
    bigrams = _claim_bigrams(terms)
    anchors = _anchor_phrases(terms)
    claim_negated = _has_negation(" ".join(terms))
    for block in re.split(r"\n\s*\n", text):
        snippet = " ".join(block.split())
        if not snippet:
            continue
        lowered = snippet.lower()
        snippet_negated = _has_negation(lowered)
        if claim_negated != snippet_negated:
            continue
        matched_terms = [term for term in terms if term in lowered]
        match_count = len(matched_terms)
        if match_count < MIN_SUPPORT_MATCHES:
            continue
        support_ratio = match_count / max(len(terms), 1)
        if support_ratio < MIN_SUPPORT_RATIO:
            continue
        bigram_matches = sum(1 for phrase in bigrams if phrase in lowered)
        if bigram_matches < MIN_BIGRAM_MATCHES:
            continue
        phrase_ratio = bigram_matches / max(len(bigrams), 1)
        anchor_matches = sum(1 for phrase in anchors if phrase in lowered)
        if anchor_matches == 0:
            continue
        anchor_ratio = anchor_matches / max(len(anchors), 1)
        snippet_terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", lowered)
        ordered_terms = [term for term in snippet_terms if term in terms]
        order_ratio = SequenceMatcher(None, terms, ordered_terms).ratio() if ordered_terms else 0.0
        if order_ratio < MIN_ORDER_RATIO:
            continue
        score = (support_ratio * 0.35) + (phrase_ratio * 0.15) + (anchor_ratio * 0.2) + (order_ratio * 0.3)
        if score > best_score:
            best_score = score
            best_snippet = snippet[:280]
    return best_score, best_snippet


def _gather_local_evidence(task: dict[str, Any], library_path: Path, max_hits: int = 3) -> list[dict[str, str]]:
    terms = _query_terms(task)
    hits: list[tuple[float, Path, str]] = []
    for path in _candidate_files(library_path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        score, snippet = _best_snippet(text, terms)
        if score <= 0 or not snippet:
            continue
        hits.append((score, path, snippet))
    hits.sort(key=lambda item: (-item[0], len(item[2])))
    return [
        {
            "source": path.relative_to(library_path).as_posix(),
            "quote": snippet,
            "support_score": round(score, 2),
        }
        for score, path, snippet in hits[:max_hits]
        if score >= MIN_FINAL_SUPPORT_SCORE
    ]


def build_remediation_queue(
    review_queue_path: Path | str,
    remediation_queue_path: Path | str,
    *,
    top_n: int = 5,
) -> dict[str, Any]:
    review_queue_path = Path(review_queue_path)
    remediation_queue_path = Path(remediation_queue_path)
    remediation_queue_path.parent.mkdir(parents=True, exist_ok=True)

    review_queue = _load_json(review_queue_path)
    if remediation_queue_path.exists():
        remediation_queue = _load_json(remediation_queue_path)
    else:
        remediation_queue = {"schema_version": "rain-memory-remediation-queue/v1", "tasks": []}

    existing_sources = {task.get("source_review_item_id") for task in remediation_queue.get("tasks", [])}
    eligible = [
        item
        for item in review_queue.get("items", [])
        if item.get("status") == "needs_evidence"
    ]
    eligible.sort(key=lambda item: -int(item.get("priority_score", 0)))

    for item in eligible[:top_n]:
        if item["id"] in existing_sources:
            continue
        remediation_queue["tasks"].append(_build_task(item))
        existing_sources.add(item["id"])

    remediation_queue["updated_at"] = _iso_now()
    remediation_queue["tasks"].sort(key=lambda task: -int(task.get("priority_score", 0)))
    remediation_queue_path.write_text(json.dumps(remediation_queue, indent=2), encoding="utf-8")
    return remediation_queue


def execute_remediation_queue(
    review_queue_path: Path | str,
    remediation_queue_path: Path | str,
    *,
    library_path: Path | str,
    max_tasks: int = 5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    review_queue_path = Path(review_queue_path)
    remediation_queue_path = Path(remediation_queue_path)
    library_path = Path(library_path)
    review_queue = _load_json(review_queue_path)
    remediation_queue = _load_json(remediation_queue_path)

    review_by_id = {item["id"]: item for item in review_queue.get("items", [])}
    pending = [task for task in remediation_queue.get("tasks", []) if task.get("status") == "pending"]
    pending.sort(key=lambda task: -int(task.get("priority_score", 0)))

    for task in pending[:max_tasks]:
        evidence = _gather_local_evidence(task, library_path)
        task["executed_at"] = _iso_now()
        task["evidence"] = evidence
        review_item = review_by_id.get(task.get("source_review_item_id"))
        if review_item is None:
            task["status"] = "orphaned"
            continue

        review_item["remediation_task_id"] = task["id"]
        review_item["remediation_status"] = "completed"
        if evidence:
            task["status"] = "completed"
            review_item["status"] = "pending_review"
            review_item["evidence"] = evidence
            review_item["provenance"] = sorted({entry["source"] for entry in evidence})
            review_item["confidence"] = max(float(review_item.get("confidence", 0.0)), 0.55)
        else:
            task["status"] = "no_evidence"
            review_item["status"] = "rejected"
            review_item["rejection_reason"] = "no_local_evidence_found"

    review_queue["updated_at"] = _iso_now()
    remediation_queue["updated_at"] = _iso_now()
    review_queue_path.write_text(json.dumps(review_queue, indent=2), encoding="utf-8")
    remediation_queue_path.write_text(json.dumps(remediation_queue, indent=2), encoding="utf-8")
    return review_queue, remediation_queue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an evidence-gathering remediation queue from governed-memory "
            "review items."
        )
    )
    parser.add_argument(
        "--review-queue",
        type=str,
        default="state/memory_review_queue.json",
        help="Governed-memory review queue path.",
    )
    parser.add_argument(
        "--remediation-queue",
        type=str,
        default="state/memory_remediation_queue.json",
        help="Output remediation queue path.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Maximum number of new remediation tasks to create.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute pending remediation tasks instead of only generating them.",
    )
    parser.add_argument(
        "--library",
        type=str,
        default=".",
        help="Library/repo root for local evidence search.",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=5,
        help="Maximum number of pending remediation tasks to execute.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    if args.execute:
        review_queue, remediation_queue = execute_remediation_queue(
            args.review_queue,
            args.remediation_queue,
            library_path=args.library,
            max_tasks=args.max_tasks,
        )
        output: dict[str, Any] = {
            "review_queue": review_queue,
            "remediation_queue": remediation_queue,
        }
    else:
        output = build_remediation_queue(
            args.review_queue,
            args.remediation_queue,
            top_n=args.top_n,
        )

    if args.json:
        print(json.dumps(output, indent=2))
        return 0

    print("R.A.I.N. Memory Remediation")
    if args.execute:
        executed = len(
            [
                task
                for task in output["remediation_queue"]["tasks"]
                if task.get("status") != "pending"
            ]
        )
        print(f"Tasks executed: {executed}")
    else:
        print(f"Tasks: {len(output['tasks'])}")
    print(f"Queue path: {Path(args.remediation_queue).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
