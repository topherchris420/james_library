"""Strict, non-executing ingress for the existing v1 simulated experiment contracts."""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .manifest import calculate_sha256, canonical_json_str, validate_manifest

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "rain-circle"


def validate_contract(value: Any, name: str) -> None:
    """Use repository-owned schemas only; never resolve schemas supplied by a caller."""
    if name not in {"manifest", "result"}:
        raise ValueError("Unsupported contract")
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Contract must contain finite JSON values") from exc
    schema = json.loads((CONTRACTS / f"experiment-{name}.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        paths = ["/".join(map(str, error.absolute_path)) or "root" for error in errors]
        raise ValueError(f"Invalid {name} contract at: {', '.join(paths)}")
    if value["protocol_version"] != "1.0.0":
        raise ValueError("Unsupported protocol version")
    if name == "manifest" and validate_manifest(value):
        raise ValueError("Manifest failed deterministic parameter validation")


def ingest_result(manifest: dict, result: dict, measurements: dict) -> dict:
    """Validate supplied evidence and return an isolated in-process analysis payload.

    Artifact paths are opaque references: no file, URL, command or model is opened.
    Acceptance establishes internal consistency, not authenticity or authorization.
    This deliberately supports only v1 SIMULATED results and their single data artifact.
    """
    validate_contract(manifest, "manifest")
    validate_contract(result, "result")
    if result["executor_type"] != "SIMULATED" or result["provenance"] != "SIMULATED":
        raise ValueError("Only SIMULATED evidence is supported by this ingestion boundary")
    if result["manifest_sha256"] != calculate_sha256(manifest):
        raise ValueError("Result is not bound to the supplied manifest")
    if not isinstance(measurements, dict):
        raise ValueError("Measurements must be an object")
    for key in ("experiment_id", "trial_id"):
        if result[key] != manifest[key] or measurements.get(key) != manifest[key]:
            raise ValueError(f"Mismatched {key}")
    if measurements.get("execution_id") != result["execution_id"]:
        raise ValueError("Mismatched execution_id")
    if measurements.get("provenance") != "SIMULATED":
        raise ValueError("Invalid measurement provenance")
    if measurements.get("session_id") not in result["circle_session_references"]:
        raise ValueError("Missing session lineage")
    header = measurements.get("circle_session_header")
    intervention = measurements.get("circle_intervention")
    if (not isinstance(header, dict) or header.get("provenance") != "SIMULATED"
            or not isinstance(intervention, dict) or intervention.get("provenance") != "SIMULATED"
            or intervention.get("session_id") != measurements.get("session_id")
            or intervention.get("intervention_id") not in result["circle_intervention_references"]):
        raise ValueError("Invalid embedded provenance lineage")
    try:
        start = datetime.fromisoformat(result["started_at"])
        end = datetime.fromisoformat(result["ended_at"])
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            raise ValueError("Invalid time ordering")
    except (TypeError, ValueError) as exc:
        raise ValueError("Execution timestamps must be ordered timezone-aware ISO dates") from exc
    series = measurements.get("measurements")
    if not isinstance(series, dict) or set(series) != {"control", "active", "phantom"}:
        raise ValueError("Expected control, active and phantom observations")
    for values in series.values():
        if not isinstance(values, list) or not 2 <= len(values) <= 100_000 or any(
            type(value) not in (int, float) or not math.isfinite(value) for value in values
        ):
            raise ValueError("Observations must be bounded, finite numeric arrays")
    try:
        json.dumps(measurements, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Measurements must contain finite JSON values") from exc
    references = result["raw_artifact_references"]
    if len(references) != 1 or references[0]["type"] != "SIMULATED_TIME_SERIES":
        raise ValueError("Expected exactly one simulated time-series artifact")
    reference = references[0]
    digest = calculate_sha256(canonical_json_str(measurements))
    if reference["sha256"] != digest or result["checksums"] != {reference["path"]: digest}:
        raise ValueError("Measurement checksum mismatch")
    return {**copy.deepcopy(result), "_embedded_data": copy.deepcopy(measurements)}
