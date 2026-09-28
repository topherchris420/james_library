"""Reviewable, explicitly authorized offline example using the existing experiment protocol.

Run with ``python -m james_library.services.experiment_protocol.research --help``.
Approval is a local operator attestation, not identity authentication or a sandbox.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
from datetime import datetime, timezone
from pathlib import Path

from .analysis import run_deterministic_analysis
from .bundle import save_experiment_bundle, verify_bundle_integrity
from .executor import SimulatedCircleExecutor
from .ingestion import ingest_result, validate_contract
from .manifest import calculate_sha256
from .reasoning import assemble_experiment_analysis, design_experiment


def create_plan() -> dict:
    manifest = design_experiment(
        research_question="Does the simulated active condition reduce the control mean by at least 15 ohms?",
        hypothesis="The simulated active-minus-control contrast is at most -15 ohms.",
        minimum_effect_ohms=15.0,
        expected_direction="decrease",
    )
    return {
        "schema_version": "1.0.0",
        "manifest": manifest,
        "seed": 42,
        "scenario": {"sample_count": 30, "baseline_mean": 100.0, "active_effect": -16.0,
                     "noise_std": 1.2, "phantom_effect": 0.05},
        "proposal": {"origin": "SCRIPTED_MODEL_STAND_IN", "predicted_difference_ohms": -20.0},
    }


def validate_plan(plan: dict) -> str:
    """Recheck the exact plan before approval; model fields never grant permission."""
    keys = {"schema_version", "manifest", "seed", "scenario", "proposal"}
    if not isinstance(plan, dict) or set(plan) != keys or plan["schema_version"] != "1.0.0":
        raise ValueError("Invalid research plan or unsupported schema version")
    validate_contract(plan["manifest"], "manifest")
    if type(plan["seed"]) is not int or not 0 <= plan["seed"] < 2**32:
        raise ValueError("Seed must be a 32-bit unsigned integer")
    if plan["manifest"]["randomization"]["seed"] != plan["seed"]:
        raise ValueError("Plan seed must match the preregistered manifest")
    scenario = plan["scenario"]
    if not isinstance(scenario, dict) or set(scenario) != {
        "sample_count", "baseline_mean", "active_effect", "noise_std", "phantom_effect"
    }:
        raise ValueError("Unsupported simulation parameters")
    if type(scenario["sample_count"]) is not int or not 2 <= scenario["sample_count"] <= 10_000:
        raise ValueError("Sample count must be an integer between 2 and 10000")
    for key in ("baseline_mean", "active_effect", "noise_std", "phantom_effect"):
        value = scenario[key]
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1_000_000:
            raise ValueError("Simulation parameters must be finite and bounded")
    if scenario["noise_std"] < 0:
        raise ValueError("Noise must be nonnegative")
    proposal = plan["proposal"]
    if not isinstance(proposal, dict) or set(proposal) != {"origin", "predicted_difference_ohms"}:
        raise ValueError("Invalid proposal")
    if proposal["origin"] != "SCRIPTED_MODEL_STAND_IN":
        raise ValueError("This example uses a scripted proposal, not a live model")
    prediction = proposal["predicted_difference_ohms"]
    if type(prediction) not in (int, float) or not math.isfinite(prediction):
        raise ValueError("Prediction must be finite")
    return calculate_sha256(plan)


def execute_plan(plan: dict, *, approved_sha256: str | None, operator: str,
                 code_revision: str, base_dir: Path) -> Path:
    # Snapshot prevents caller mutation between validation, approval and execution.
    plan = json.loads(json.dumps(plan, allow_nan=False))
    digest = validate_plan(plan)
    if approved_sha256 != digest:
        raise ValueError("Explicit approval of this exact plan digest is required")
    if not isinstance(operator, str) or not re.fullmatch(r"R\.A\.I\.N\.[A-Za-z_]{1,40}", operator):
        raise ValueError("Use a project role such as R.A.I.N.Operator for the attestation")
    if not isinstance(code_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", code_revision):
        raise ValueError("Supply the full code commit SHA (caller-attested)")
    authorized_at = datetime.now(timezone.utc).isoformat()
    manifest = plan["manifest"]
    executor = SimulatedCircleExecutor(seed=plan["seed"])
    executor.prepare_experiment(manifest)
    result = executor.run_trial(manifest, calculate_sha256(manifest), custom_scenario=plan["scenario"])
    clean = {key: value for key, value in result.items() if not key.startswith("_")}
    result = ingest_result(manifest, clean, result["_embedded_data"])
    stats = run_deterministic_analysis(manifest, result, calculate_sha256(manifest))
    analysis = assemble_experiment_analysis(manifest, result, stats)
    record = {
        "schema_version": "1.0.0",
        "claim_id": f"{manifest['experiment_id']}:hypothesis",
        "plan": plan,
        "plan_sha256": digest,
        "validation": {"status": "PASSED", "checks": ["plan_contract", "parameters", "result_ingestion"]},
        "human_authorization": {"status": "GRANTED", "scope": "one_local_simulated_trial",
                                "plan_sha256": digest, "operator_role": operator, "at": authorized_at},
        "observation": {"difference_ohms": stats["effect_sizes"]["mean_difference"],
                        "provenance": "SIMULATED", "source": "data/measurements.json"},
        "interpretation": {"conclusion": analysis["conclusion"], "origin": "DETERMINISTIC_TEMPLATE",
                           "next_step": "Human decides keep, revise or revert; no follow-up executes."},
        "reproducibility": {"code_revision": code_revision, "revision_origin": "CALLER_ATTESTED",
                            "python": platform.python_version(), "seed": plan["seed"],
                            "analysis_method": stats["statistical_results"]["method"]},
        "limitations": ["Synthetic observations do not establish physical or biological effects.",
                        "The proposal is scripted; no model was called.",
                        "Authorization is a local attestation, not authenticated identity.",
                        "Checksums are not signatures. A writer can replace both records and hashes.",
                        "Seed replay reproduces measurements, not timestamps or generated identifiers."],
    }
    return save_experiment_bundle(base_dir, manifest, result, analysis, research_record=record)


def inspect_record(bundle: Path) -> dict:
    """Recompute observations from saved data without executing record-supplied code."""
    if not verify_bundle_integrity(bundle)["valid"]:
        raise ValueError("Bundle integrity check failed")
    def read(name: str) -> dict:
        value = json.loads((bundle / name).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    manifest = read("manifest.json")
    result = ingest_result(manifest, read("result.json"), read("data/measurements.json"))
    stats = run_deterministic_analysis(manifest, result, calculate_sha256(manifest))
    saved = read("analysis.json")
    if any(saved.get(key) != value for key, value in stats.items()):
        raise ValueError("Saved analysis disagrees with recomputed evidence")
    interpretation_check = assemble_experiment_analysis(manifest, result, stats)
    for key in ("initial_analysis", "adversarial_critique", "recommended_next_experiment",
                "model_identity", "model_version"):
        if saved.get(key) != interpretation_check[key]:
            raise ValueError("Saved interpretation disagrees with deterministic templates")
    record = read("research.json")
    if record.get("schema_version") != "1.0.0":
        raise ValueError("Unsupported research record version")
    if not isinstance(record.get("limitations"), list) or not record["limitations"] or any(
        not isinstance(value, str) or not value.strip() for value in record["limitations"]
    ):
        raise ValueError("Research record must state its limitations")
    plan = record.get("plan")
    digest = validate_plan(plan)
    if plan["manifest"] != manifest or record.get("plan_sha256") != digest:
        raise ValueError("Research plan binding mismatch")
    if record.get("claim_id") != f"{manifest['experiment_id']}:hypothesis":
        raise ValueError("Claim binding mismatch")
    authorization = record.get("human_authorization")
    if (not isinstance(authorization, dict) or authorization.get("status") != "GRANTED"
            or authorization.get("scope") != "one_local_simulated_trial"
            or authorization.get("plan_sha256") != digest):
        raise ValueError("Missing or mismatched authorization attestation")
    try:
        authorized_at = datetime.fromisoformat(authorization["at"])
        if (authorized_at.utcoffset() is None or authorized_at > datetime.fromisoformat(result["started_at"])
                or not re.fullmatch(r"R\.A\.I\.N\.[A-Za-z_]{1,40}", authorization["operator_role"])):
            raise ValueError("Invalid authorization attestation")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid authorization attestation") from exc
    validation = record.get("validation")
    if validation != {"status": "PASSED", "checks": ["plan_contract", "parameters", "result_ingestion"]}:
        raise ValueError("Invalid validation record")
    provenance = record.get("reproducibility")
    if (not isinstance(provenance, dict) or provenance.get("seed") != plan["seed"]
            or provenance.get("analysis_method") != stats["statistical_results"]["method"]
            or provenance.get("revision_origin") != "CALLER_ATTESTED"
            or not isinstance(provenance.get("code_revision"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", provenance["code_revision"])
            or not isinstance(provenance.get("python"), str)):
        raise ValueError("Invalid reproducibility metadata")
    observation = record.get("observation", {})
    if (not isinstance(observation, dict)
            or observation.get("difference_ohms") != stats["effect_sizes"]["mean_difference"]
            or observation.get("provenance") != "SIMULATED"
            or observation.get("source") != "data/measurements.json"):
        raise ValueError("Observation disagrees with evidence")
    interpretation = record.get("interpretation")
    if (not isinstance(interpretation, dict) or interpretation.get("conclusion") != stats["conclusion"]
            or interpretation.get("origin") != "DETERMINISTIC_TEMPLATE"):
        raise ValueError("Interpretation disagrees with evidence")
    # Reproduce only the built-in simulator, never a command/path from the record.
    replay = SimulatedCircleExecutor(plan["seed"]).run_trial(
        manifest, calculate_sha256(manifest), custom_scenario=plan["scenario"]
    )
    if replay["_embedded_data"]["measurements"] != result["_embedded_data"]["measurements"]:
        raise ValueError("Seed and scenario do not reproduce observations")
    return {"claim_id": record.get("claim_id"), "question": manifest["research_question"],
            "claim": manifest["hypothesis"], "predicted_difference_ohms": plan["proposal"]["predicted_difference_ohms"],
            "observed_difference_ohms": stats["effect_sizes"]["mean_difference"],
            "conclusion": stats["conclusion"], "authorization": authorization,
            "validation": validation, "reproducibility": provenance,
            "proposal_origin": plan["proposal"]["origin"],
            "reproduced_measurements": True, "limitations": record.get("limitations", []),
            "supporting_evidence": saved.get("adversarial_critique", {}).get("supporting_evidence", []),
            "contradicting_evidence": saved.get("adversarial_critique", {}).get("contradicting_evidence", []),
            "falsification_criteria": manifest["preregistered_analysis"]["falsification_criteria"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("plan", help="Write a reviewable plan; does not execute a trial")
    draft.add_argument("path", type=Path)
    run = sub.add_parser("run", help="Validate and execute one explicitly approved simulated trial")
    run.add_argument("path", type=Path)
    run.add_argument("--approve", required=True, help="Exact reviewed plan SHA-256")
    run.add_argument("--operator", default="R.A.I.N.Operator")
    run.add_argument("--code-revision", required=True)
    run.add_argument("--out-dir", type=Path, default=Path("."))
    inspect = sub.add_parser("inspect", help="Verify, reanalyze and reproduce saved simulated observations")
    inspect.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = create_plan()
            digest = validate_plan(plan)
            with args.path.open("x", encoding="utf-8") as stream:
                json.dump(plan, stream, indent=2, allow_nan=False)
            print(f"Review {args.path}. Plan SHA-256: {digest}")
        elif args.command == "inspect":
            print(json.dumps(inspect_record(args.path), indent=2, allow_nan=False))
        else:
            plan = json.loads(args.path.read_text(encoding="utf-8"))
            print(execute_plan(plan, approved_sha256=args.approve, operator=args.operator,
                               code_revision=args.code_revision, base_dir=args.out_dir))
        return 0
    except (ValueError, TypeError, OSError) as exc:
        print(f"Research workflow rejected: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
