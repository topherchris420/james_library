"""Run the strict five-stage promotion boundary from a curated evidence packet."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from james_library.judgment import (
    ClaimEvidence,
    ValidationStatus,
    contains_sensitive_material,
    create_judgment_service,
    format_judgment,
)
from james_library.launcher.meeting_workflow import MeetingWorkflow
from james_library.utilities.session_artifact import SessionArtifactWriter
from james_library.utilities.session_replay import replay_recorded_judgments


CYCLE_SCHEMA_VERSION = "rain-judgment-cycle/v1"
MAX_PACKET_BYTES = 131_072
_REQUIRED_KEYS = {
    "schema_version", "claim", "method", "observations", "quantitative_results",
    "tool_evidence", "known_limitations", "source_identifiers", "synthesis_summary",
    "peer_critique",
}
_OPTIONAL_KEYS = {"formal_logic_result", "numerical_validation"}


@dataclass(frozen=True)
class JudgmentCycle:
    evidence: ClaimEvidence
    synthesis_summary: str
    reviewer: str
    peer_score: int


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _required_text(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid text field")
    return value.strip()


def _formal_channel(value: Any) -> tuple[str, ValidationStatus]:
    if value is None:
        return "[NOT RUN]", ValidationStatus.NOT_RUN
    if not isinstance(value, dict):
        raise ValueError("invalid formal result")
    if set(value) == {"error"} and isinstance(value["error"], str):
        return "[ERROR: formal validation unavailable]", ValidationStatus.ERROR
    if set(value) - {"satisfiable", "model"} or type(value.get("satisfiable")) is not bool:
        raise ValueError("invalid formal result")
    model = value.get("model")
    if model is not None and (
        not isinstance(model, dict)
        or not all(isinstance(key, str) and type(answer) is bool for key, answer in model.items())
    ):
        raise ValueError("invalid formal model")
    status = ValidationStatus.PASSED if value["satisfiable"] else ValidationStatus.FAILED
    return json.dumps(value, sort_keys=True, separators=(",", ":")), status


def _numerical_channel(value: Any) -> tuple[str, ValidationStatus]:
    if value is None:
        return "[NOT RUN]", ValidationStatus.NOT_RUN
    if not isinstance(value, dict):
        raise ValueError("invalid numerical result")
    if set(value) == {"error"} and isinstance(value["error"], str):
        return "[ERROR: numerical validation unavailable]", ValidationStatus.ERROR
    if set(value) - {"passed", "details"} or type(value.get("passed")) is not bool:
        raise ValueError("invalid numerical result")
    details = value.get("details", "[NO DETAILS SUPPLIED]")
    if not isinstance(details, str):
        raise ValueError("invalid numerical details")
    status = ValidationStatus.PASSED if value["passed"] else ValidationStatus.FAILED
    return details.strip() or "[NO DETAILS SUPPLIED]", status


def load_cycle(path: Path | str) -> JudgmentCycle:
    try:
        with Path(path).open("rb") as packet_file:
            raw = packet_file.read(MAX_PACKET_BYTES + 1)
        if len(raw) > MAX_PACKET_BYTES:
            raise ValueError
        decoded = raw.decode("utf-8")
        if contains_sensitive_material(decoded):
            raise ValueError
        payload = json.loads(
            decoded,
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_constant,
        )
        if not isinstance(payload, dict):
            raise ValueError
        if contains_sensitive_material(json.dumps(payload, ensure_ascii=False)):
            raise ValueError
        if set(payload) - (_REQUIRED_KEYS | _OPTIONAL_KEYS) or not _REQUIRED_KEYS <= set(payload):
            raise ValueError
        if payload["schema_version"] != CYCLE_SCHEMA_VERSION:
            raise ValueError
        sources = payload["source_identifiers"]
        if not isinstance(sources, list) or not all(isinstance(item, str) and item.strip() for item in sources):
            raise ValueError
        peer = payload["peer_critique"]
        if not isinstance(peer, dict) or set(peer) != {"reviewer", "score", "feedback"}:
            raise ValueError
        score = peer["score"]
        if type(score) is not int or not 1 <= score <= 10:
            raise ValueError
        formal_text, formal_status = _formal_channel(payload.get("formal_logic_result"))
        numerical_text, numerical_status = _numerical_channel(payload.get("numerical_validation"))
        evidence = ClaimEvidence(
            claim=_required_text(payload, "claim"),
            method=_required_text(payload, "method"),
            observations=_required_text(payload, "observations"),
            quantitative_results=_required_text(payload, "quantitative_results"),
            tool_evidence=_required_text(payload, "tool_evidence") + "\n" + numerical_text,
            peer_critique=_required_text(peer, "feedback"),
            formal_logic_result=formal_text,
            known_limitations=_required_text(payload, "known_limitations"),
            source_identifiers=tuple(item.strip() for item in sources),
            formal_status=formal_status,
            numerical_status=numerical_status,
        )
        return JudgmentCycle(
            evidence=evidence,
            synthesis_summary=_required_text(payload, "synthesis_summary"),
            reviewer=_required_text(peer, "reviewer"),
            peer_score=score,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        raise ValueError("invalid_evidence_packet") from exc


def _print_recorded(path: str) -> int:
    report = replay_recorded_judgments(path)
    print("RECORDED JUDGMENT")
    for item in report["judgments"]:
        print(f"{item.get('judgment_id', '')}: {item.get('disposition', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rain_lab.py judge",
        description="Evaluate one curated five-stage claim/evidence packet.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--evidence", type=str, help="Path to rain-judgment-cycle/v1 JSON.")
    source.add_argument("--replay", type=str, help="Read recorded judgments without a provider call.")
    parser.add_argument("--output-dir", default="meeting_archives/session_artifacts")
    args = parser.parse_args(argv)

    if args.replay:
        try:
            return _print_recorded(args.replay)
        except ValueError:
            print("Typed Judgment: RECORDED JUDGMENT INVALID")
            return 2

    try:
        cycle = load_cycle(args.evidence)
        service = create_judgment_service()
    except ValueError:
        print("Typed Judgment: INVALID EVIDENCE OR CONFIGURATION")
        return 2

    session_id = f"judgment-{uuid4().hex[:12]}"
    writer = SessionArtifactWriter(
        artifact_root=args.output_dir,
        session_id=session_id,
        topic=cycle.evidence.claim,
        model="typed-judgment",
        recursive_depth=0,
        library_path=str(Path(args.evidence).resolve().parent),
        log_path="",
        loaded_papers=list(cycle.evidence.source_identifiers),
    )
    workflow = MeetingWorkflow(
        judgment_service=service,
        judgment_recorder=writer.record_judgment if service is not None else None,
    )
    workflow.set_hypothesis(cycle.evidence.claim)
    workflow.set_simulation_data({"observations": cycle.evidence.observations})
    workflow.set_synthesis(cycle.synthesis_summary)
    workflow.set_peer_critique(cycle.reviewer, cycle.peer_score, cycle.evidence.peer_critique)
    accepted = workflow.finalize_discovery_gate(evidence=cycle.evidence if service is not None else None)
    envelope = workflow.record.judgment
    if envelope is not None:
        typed_status = envelope.decision.disposition.value
        gate_disposition = envelope.decision.disposition.value
    elif service is not None:
        typed_status = "NOT_RUN"
        gate_disposition = workflow.history[-1]["gate_disposition"]
    else:
        typed_status = "DISABLED"
        gate_disposition = "PASS" if accepted else "REVISE"
    writer.finalize(
        status="completed",
        metrics={
            "peer_critique_score": cycle.peer_score,
            "discovery_accepted": accepted,
            "gate_disposition": gate_disposition,
            "typed_judgment_status": typed_status,
        },
        summary=f"Peer score {cycle.peer_score}; typed judgment {typed_status}.",
    )
    print(f"Peer critique: {cycle.peer_score} / 10")
    if envelope is not None:
        print(format_judgment(envelope))
    elif service is not None:
        print("Typed Judgment: NOT RUN")
        print("Reason: peer_score_below_threshold")
        print(f"Gate: {gate_disposition}")
    else:
        print("Typed Judgment: DISABLED")
    print(f"Artifact: {writer.path}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
