"""Curated bounded decisions, recorded in the existing session artifact format."""

import argparse
from pathlib import Path
from uuid import uuid4

from james_library.judgment.calibration import read_json
from james_library.judgment.config import create_decision_router, enabled
from james_library.judgment.process import PROCESS_ACTIONS
from james_library.judgment.routing import DecisionRequest
from james_library.utilities.session_artifact import SessionArtifactWriter
from james_library.utilities.session_replay import replay_recorded_judgments


def load_request(path):
    try:
        raw = read_json(path, 131_072)
        if not isinstance(raw, dict) or raw.pop("schema_version") != "rain-bounded-request/v1":
            raise ValueError
        # A file supplies observations, never trusted deterministic conclusions.
        if "deterministic_choice" in raw:
            raise ValueError
        choices = raw["choices"]
        if not isinstance(choices, dict):
            raise ValueError
        raw["choices"] = tuple(choices.items())
        return DecisionRequest(**raw)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        raise ValueError("invalid bounded request") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rain_lab.py decide", description="Propose; never execute a bounded action.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request")
    source.add_argument("--replay")
    parser.add_argument("--output-dir", default="meeting_archives/session_artifacts")
    args = parser.parse_args(argv)
    try:
        if args.replay:
            report = replay_recorded_judgments(args.replay)
            print("RECORDED DECISION")
            for item in report["decisions"]:
                print(f'{item["decision_id"]}: {item["destination"]} {item["selected"] or item["reason"]}')
            return 0
        request = load_request(args.request)
        router = create_decision_router()
        metacognitive = enabled("RAIN_METACOGNITIVE_CONTROL")
        def validator(req, selected):
            if req.decision_class == "research_process" and (
                not metacognitive or not set(dict(req.choices)) <= set(dict(PROCESS_ACTIONS))
            ):
                return False
            return selected is None or selected in dict(req.choices)
        envelope = router.decide(request, validator=validator)
        writer = SessionArtifactWriter(args.output_dir, "decision-" + uuid4().hex[:12],
                                       "Bounded workflow decision", "decision-router", 0, "", "")
        writer.record_decision(envelope)
        writer.finalize(status="completed", metrics={"destination": envelope.destination})
        print(f"Decision: {envelope.destination}")
        print(f"Proposal: {envelope.selected or 'none'}")
        if envelope.reason:
            print(f"Reason: {envelope.reason.value}")
        if envelope.destination == "rain":
            print("Return to the existing R.A.I.N. research workflow; no action was authorized.")
        print(f"Artifact: {Path(writer.path)}")
        return 0 if envelope.destination == "proposal" else 1
    except (ValueError, OSError, TypeError):
        print("Decision: INVALID REQUEST OR CONFIGURATION")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
