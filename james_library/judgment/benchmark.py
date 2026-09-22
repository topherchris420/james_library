"""Bounded routing measurements; fixture mode is explicitly synthetic, never a leaderboard."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from time import monotonic

from .calibration import CalibrationProfile, CalibrationSample, fit_profile, metrics, read_json
from .config import create_decision_router
from .contracts import JudgmentAnswer, JudgmentResult, QuestionType
from .routing import DecisionRequest, DecisionRouter


class FixtureProvider:
    """Fault-injection test double. Never loaded by the runtime factory."""

    def __init__(self, engine, fixtures):
        self.engine, self.fixtures = engine, fixtures

    def evaluate(self, state, questions):
        fixture = self.fixtures[state.canonical_text][self.engine]
        error = fixture.get("error")
        if error:
            return JudgmentResult(self.engine, state_hash=state.state_hash,
                                  question_set_version=questions.version, error_code=error)
        keys = tuple(dict(questions.questions[0].choices))
        choice = fixture["choice"]
        p = fixture.get("probability", .99)
        probabilities = tuple((key, p if key == choice else (1-p)/(len(keys)-1)) for key in keys)
        answer = JudgmentAnswer("next_action", QuestionType.CHOICE, choice, probabilities, p)
        return JudgmentResult(self.engine, "fixture-" + self.engine, (answer,), state.state_hash, questions.version)


def fixture_profiles(cases):
    profiles = {}
    for case in cases:
        request = case_request(case)
        for engine in ("laya", "typesafe"):
            key = (engine, request.decision_class, request.question_hash)
            selected = request.choices[0][0]
            samples = tuple(CalibrationSample(f"fixture-{i}", selected, selected, .99, .98) for i in range(400))
            profiles[key] = CalibrationProfile(
                engine, "fixture-" + engine, request.decision_class, request.question_hash, .9, .15, .95,
                samples[:200], samples[200:], (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            )
    return tuple(profiles.values())


def case_request(case):
    payload = dict(case["request"])
    payload["choices"] = tuple(payload["choices"].items())
    return DecisionRequest(**payload)


def measure(cases, router):
    rows, samples = [], []
    started = monotonic()
    for case in cases:
        request = case_request(case)
        envelope = router.decide(request, validator=lambda req, selected: (
            case.get("precheck", True) is True
            and (selected is None or case.get("postcheck", True) is True)
        ))
        row = envelope.to_dict()
        row["case_id"] = case["id"]
        row["expected"] = case["expected"]
        rows.append(row)
        for attempt in envelope.attempts:
            if attempt.selected is not None:
                probabilities = sorted(dict(attempt.probabilities).values(), reverse=True)
                sample = CalibrationSample(case["id"], case["expected"], attempt.selected,
                                           probabilities[0], probabilities[0]-probabilities[1])
                samples.append({"engine": attempt.engine, "model": attempt.model,
                                "decision_class": request.decision_class, "question_hash": request.question_hash,
                                **asdict(sample)})
    resolved = [r for r in rows if r["destination"] == "proposal"]
    n = len(rows)
    def fraction(count):
        return count / n if n else None
    latencies = sorted(r["latency_ms"] for r in rows)
    return {
        "cases": n, "elapsed_ms": (monotonic()-started)*1000,
        "proposal_accuracy": sum(r["selected"] == r["expected"] for r in resolved)/len(resolved) if resolved else None,
        "abstention_rate": fraction(n-len(resolved)),
        "escalation_rate": fraction(sum(r["destination"] == "rain" for r in rows)),
        "invalid_output_rate": fraction(sum(any(a["reason"] == "INVALID_OUTPUT" for a in r["attempts"]) for r in rows)),
        "disagreement_rate": fraction(sum(r["reason"] == "ENGINE_DISAGREEMENT" for r in rows)),
        "resolved_locally": fraction(sum(r["destination"] == "proposal" and bool(r["attempts"])
                                         and r["attempts"][-1]["engine"] == "laya" for r in rows)),
        "evaluated_by_jev": fraction(sum(any(a["engine"] == "typesafe" and a["model"] is not None
                                            for a in r["attempts"]) for r in rows)),
        "escalated_to_jev": fraction(sum(len(r["attempts"]) == 2 for r in rows)),
        "escalated_to_rain": fraction(sum(r["destination"] == "rain" for r in rows)),
        "latency_p50_ms": latencies[len(latencies)//2] if n else None,
        "latency_p95_ms": latencies[min(n-1, int(n*.95))] if n else None,
        "raw_calibration": metrics([CalibrationSample(**{k: s[k] for k in (
            "sample_id", "expected", "selected", "probability", "margin"
        )}) for s in samples]),
        "rows": rows, "samples": samples,
        "rain_deliberation_accuracy": None,
        "rain_deliberation_note": "Measures handoff only; no generative R.A.I.N. answers were run or graded.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="benchmark_data/bounded_decisions.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--fixture", action="store_true",
                        help="Synthetic providers and calibration; no quality claims.")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args(argv)
    cases = read_json(args.cases)
    if not isinstance(cases, list) or not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("benchmark cases must have unique IDs")
    if args.fixture:
        fixtures = {case["request"]["state"]: case["fixture"] for case in cases}
        base = DecisionRouter(mode="cascade", laya=FixtureProvider("laya", fixtures),
                              jev=FixtureProvider("typesafe", fixtures), profiles=fixture_profiles(cases))
    else:
        base = create_decision_router()
    reports = {}
    for mode in ("laya", "jev", "cascade", "off"):
        router = DecisionRouter(mode=mode, laya=base.laya, jev=base.jev, profiles=base.profiles,
                                minimum_samples=base.minimum_samples, timeout=base.timeout, compare=args.compare)
        reports["rain_fallback" if mode == "off" else mode] = measure(cases, router)
    result = {"schema_version": "rain-decision-benchmark/v1",
              "mode": "synthetic_fixture" if args.fixture else "configured_providers",
              "comparison": args.compare, "reports": reports}
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({mode: {k: v for k, v in report.items() if k not in {"rows", "samples", "raw_calibration"}}
                      for mode, report in reports.items()}, indent=2))
    return 0


def calibration_main(argv=None):
    parser = argparse.ArgumentParser(description="Fit on one labeled split and validate on a disjoint held-out split.")
    parser.add_argument("--fit", required=True)
    parser.add_argument("--heldout", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target", type=float, default=.95)
    parser.add_argument("--minimum-samples", type=int, default=100)
    parser.add_argument("--check", help="Check drift against a locked profile file instead of fitting.")
    args = parser.parse_args(argv)
    fit, heldout = read_json(args.fit), read_json(args.heldout)
    identity_keys = ("engine", "model", "decision_class", "question_hash")
    identities = {tuple(row[k] for k in identity_keys) for row in fit + heldout}
    if len(identities) != 1:
        raise ValueError("calibrate one concrete model and question definition at a time")
    identity = dict(zip(identity_keys, identities.pop()))
    def samples(rows):
        return tuple(CalibrationSample(**{k: v for k, v in row.items() if k not in identity_keys}) for row in rows)
    if args.check:
        from .calibration import load_profiles
        profile = next((p for p in load_profiles(args.check)
                        if all(getattr(p, k) == v for k, v in identity.items())), None)
        if profile is None:
            raise ValueError("model/question drift: no matching locked profile")
        checked = replace(profile, fit_samples=samples(fit), heldout_samples=samples(heldout))
        old_coverage = 1 - metrics(profile.heldout_samples, profile.threshold, profile.margin)["abstention_rate"]
        new_metrics = metrics(checked.heldout_samples, profile.threshold, profile.margin)
        new_coverage = 1 - new_metrics["abstention_rate"] if checked.heldout_samples else 0
        valid = checked.supports(args.minimum_samples) and new_coverage >= old_coverage - .05
        result = {"drift_check_passed": valid, "coverage_change": new_coverage - old_coverage,
                  "report": checked.report()}
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
        return 0 if valid else 1
    profile = fit_profile(**identity, fit_samples=samples(fit), heldout_samples=samples(heldout),
                          target_accuracy=args.target, minimum_samples=args.minimum_samples)
    Path(args.output).write_text(json.dumps([asdict(profile)], indent=2) + "\n")
    print(json.dumps(profile.report(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
