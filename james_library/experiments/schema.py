"""Versioned experiment contracts, canonical JSON and validation.

The JSON Schemas under ``james_library/contracts/experiments/`` are the
language-neutral interface. This module adds the semantic checks a schema
cannot express (criteria must reference declared metrics, finite numbers).
Only repository-owned schemas are loaded; callers never supply a schema.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import cache
from pathlib import Path
from typing import Any

from .provenance import find_secrets, redact

DEFINITION_SCHEMA = "rain-experiment/v1"
RUN_SCHEMA = "rain-experiment-run/v1"
SUBMISSION_SCHEMA = "rain-experiment-submission/v1"

RUN_STATUSES = ("running", "passed", "failed", "inconclusive", "error")
EXPERIMENT_STATUSES = ("planned",) + RUN_STATUSES
VERDICTS = ("supported", "not_supported", "insufficient_evidence", "not_evaluated")
EVIDENCE_CLASSES = ("measured", "simulated", "model_inferred")

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts" / "experiments"


class ExperimentError(ValueError):
    """A definition, record or request that the host refuses to accept."""


def canonical_json(data: Any) -> str:
    """Stable, human-diffable JSON used for every file the registry writes."""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def sha256_json(data: Any) -> str:
    compact = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@cache
def _validator(name: str) -> Any:
    from jsonschema import Draft202012Validator  # imported lazily: routing must not need it

    schema = json.loads((CONTRACTS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_errors(value: Any, name: str) -> list[str]:
    errors = []
    for error in sorted(_validator(name).iter_errors(value), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        errors.append(f"{where}: {error.message}")
    return errors


def _finite_json_errors(value: Any) -> list[str]:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return [f"(root): not finite JSON ({exc})"]
    return []


def definition_errors(definition: Any) -> list[str]:
    """Return every problem with an experiment definition (empty when valid)."""
    errors = _finite_json_errors(definition) or _schema_errors(definition, "experiment")
    if errors:
        return errors
    metrics = [metric["name"] for metric in definition["metrics"]]
    if len(set(metrics)) != len(metrics):
        errors.append("metrics: duplicate metric names")
    ids: list[str] = []
    for group, prefix in (("guards", "G"), ("success", "S"), ("failure", "F")):
        for criterion in definition["criteria"][group]:
            ids.append(criterion["id"])
            if not criterion["id"].startswith(prefix):
                errors.append(f"criteria/{group}: id {criterion['id']!r} must start with {prefix!r}")
            if criterion["metric"] not in metrics:
                errors.append(f"criteria/{group}/{criterion['id']}: metric {criterion['metric']!r} is not declared")
            if not math.isfinite(criterion["value"]):
                errors.append(f"criteria/{group}/{criterion['id']}: threshold must be finite")
    if len(set(ids)) != len(ids):
        errors.append("criteria: duplicate criterion ids")
    if redact(definition) != definition or find_secrets(json.dumps(definition)):
        errors.append("(root): contains a credential-like value; definitions are committed and must not hold "
                      "secrets (pass credentials through the environment at run time)")
    runner = definition["runner"]
    if runner["kind"] == "external" and definition["subsystem"]["paths"]:
        errors.append("subsystem/paths: external experiments cannot hash files in this repository")
    return errors


def validate_definition(definition: Any) -> dict[str, Any]:
    errors = definition_errors(definition)
    if errors:
        raise ExperimentError("Invalid experiment definition:\n  " + "\n  ".join(errors))
    return definition


def run_record_errors(record: Any) -> list[str]:
    errors = _finite_json_errors(record) or _schema_errors(record, "run")
    if errors:
        return errors
    if record["run_id"].rsplit("-RUN-", 1)[0] != record["experiment_id"]:
        errors.append("run_id does not belong to experiment_id")
    if sha256_json(record["definition"]) != record["definition_sha256"]:
        errors.append("definition snapshot does not match definition_sha256")
    errors.extend(f"definition: {e}" for e in definition_errors(record["definition"]))
    if record["status"] == "error" and record["error"] is None:
        errors.append("status 'error' requires an error object")
    if record["status"] not in ("error", "running") and record["error"] is not None:
        errors.append("an error object is only valid with status 'error'")
    return errors


def submission_errors(submission: Any) -> list[str]:
    return _finite_json_errors(submission) or _schema_errors(submission, "submission")
