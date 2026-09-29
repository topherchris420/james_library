"""Run pipeline: resolve → validate → capture provenance → execute → measure →
evaluate → store artifacts → write the run record.

Runners return measurements only. The host computes statistics and applies
the pre-registered criteria (``evaluate.py``). An exception inside a runner
becomes an ``error`` run: a failed execution is recorded, not hidden, and is
never confused with a failed hypothesis.

External repositories do not execute here; they submit measurements for a
registered external experiment and the host evaluates them the same way.
"""

from __future__ import annotations

import copy
import inspect
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import provenance
from .evaluate import evaluate
from .registry import Registry, read_json, utc_now
from .schema import (
    RUN_SCHEMA,
    ExperimentError,
    sha256_bytes,
    sha256_json,
    submission_errors,
)
from .stats import summarize

MAX_STORED_ARTIFACT_BYTES = 5 * 1024 * 1024
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

_CLASS_NOTES = {
    "measured": "Measured on this code and data; the result is bounded by the listed limitations.",
    "simulated": "Simulated data: this characterizes the simulator and analysis pipeline, not a physical system.",
    "model_inferred": "Values are model output, not empirical measurement; treat as inference.",
}


@dataclass
class RunOutput:
    """What a runner hands back. It has no status field on purpose."""

    measurements: dict[str, float | int | None]
    series: dict[str, list[float]] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    models: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RunnerSpec:
    """A registered local experiment implementation (factory entry)."""

    name: str
    version: str
    evidence_class: str
    func: Callable[[RunContext], RunOutput]


class RunContext:
    def __init__(self, experiment_id: str, run_id: str, parameters: dict[str, Any], seed: int | None) -> None:
        self.experiment_id = experiment_id
        self.run_id = run_id
        self.parameters = copy.deepcopy(parameters)
        self.seed = seed
        self.artifacts: list[tuple[str, bytes, str]] = []

    def add_artifact(self, name: str, content: bytes | str | dict | list, kind: str) -> None:
        if not _ARTIFACT_NAME.match(name) or any(name == existing for existing, _, _ in self.artifacts):
            raise ExperimentError(f"Invalid or duplicate artifact name: {name!r}")
        if isinstance(content, (dict, list)):
            content = json.dumps(content, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.artifacts.append((name, bytes(content), kind))


# ── helpers ────────────────────────────────────────────────────────────

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_output(output: Any) -> RunOutput:
    if not isinstance(output, RunOutput):
        raise ExperimentError("Runner must return RunOutput")
    for name, value in output.measurements.items():
        if not re.match(r"^[a-z][a-z0-9_]{0,63}$", str(name)):
            raise ExperimentError(f"Invalid measurement name {name!r}")
        if value is not None and not _is_number(value):
            raise ExperimentError(f"Measurement {name!r} is not a finite number: {value!r}")
    for name, values in output.series.items():
        if not isinstance(values, list) or not all(_is_number(v) for v in values):
            raise ExperimentError(f"Series {name!r} must be a list of finite numbers")
    json.dumps([output.inputs, output.observations, output.limitations, output.models], allow_nan=False)
    return output


def _statistics(series: dict[str, list[float]], models: list[dict[str, Any]]) -> dict[str, Any]:
    stats = {name: summarize(values) for name, values in sorted(series.items())}
    for model in models:
        latencies = model.get("latency_ms")
        if isinstance(latencies, list) and latencies:
            stats[f"model.{model.get('role', 'model')}.latency_ms"] = summarize(latencies)
    return stats


def _interpretation(evidence_class: str, evaluation: dict[str, Any] | None, error: dict | None) -> str:
    if error is not None:
        return (f"Execution error at stage '{error['stage']}' ({error['type']}). "
                "The hypothesis was not evaluated; this is not a failed hypothesis.")
    return f"{evaluation['summary']} {_CLASS_NOTES[evidence_class]}"


def _error(stage: str, exc: BaseException) -> dict[str, str]:
    return {"stage": stage, "type": type(exc).__name__, "message": provenance.redact(str(exc))[:2000]}


def _store_artifacts(run_dir: Path, definition: dict[str, Any], artifacts: list[tuple[str, bytes, str]]) -> list[dict]:
    policy = definition["data_policy"]
    allow_store = policy["store_artifacts"] and policy["classification"] != "sensitive"
    rows = []
    for name, content, kind in artifacts:
        note = None
        stored = allow_store
        if stored and len(content) > MAX_STORED_ARTIFACT_BYTES:
            stored, note = False, f"larger than {MAX_STORED_ARTIFACT_BYTES} bytes; hash only"
        if stored:
            if provenance.credential_formats_in(content.decode("utf-8", errors="ignore")):
                stored, note = False, "credential-like content detected; content withheld"
        if not allow_store:
            note = f"data policy ({policy['classification']}) keeps hashes only"
        if stored:
            target = run_dir / "artifacts"
            target.mkdir(exist_ok=True)
            (target / name).write_bytes(content)
        rows.append({"name": name, "sha256": sha256_bytes(content), "bytes": len(content),
                     "kind": kind, "stored": stored, "note": note})
    return rows


def reproduction_report(definition: dict, source: dict, record: dict) -> dict[str, Any]:
    """Compare a replay with its source run; ``verify`` recomputes this from the stored records."""
    mismatches = []
    outcome_matches = source["status"] == record["status"]
    if not outcome_matches:
        mismatches.append(f"status: {source['status']} -> {record['status']}")
    metrics_match = True
    for metric in definition["metrics"]:
        name = metric["name"]
        before, after = source["measurements"].get(name), record["measurements"].get(name)
        if metric["deterministic"] and before != after:
            metrics_match = False
            mismatches.append(f"{name}: {before} -> {after}")
    if source["definition_sha256"] != record["definition_sha256"]:
        mismatches.append(
            f"definition: v{source['definition']['experiment_version']} -> v{definition['experiment_version']}"
        )
    return {
        "source_run": source["run_id"],
        "outcome_matches": outcome_matches,
        "deterministic_metrics_match": metrics_match,
        "mismatches": mismatches,
    }


def _complete(record: dict[str, Any], definition: dict[str, Any], output: RunOutput | None,
              error: dict | None, started: float) -> dict[str, Any]:
    """Fill measurements, statistics and the deterministic evaluation (no I/O)."""
    record["finished_at"] = utc_now()
    record["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    if output is not None:
        record["measurements"] = dict(sorted(output.measurements.items()))
        record["series"] = dict(sorted(output.series.items()))
        record["inputs"] = provenance.redact(output.inputs)
        record["observations"] = provenance.redact(list(output.observations))
        record["limitations"] = list(definition["limitations"]) + provenance.redact(list(output.limitations))
        record["models"] = provenance.redact(output.models)
        record["statistics"] = _statistics(record["series"], record["models"])
    if error is None:
        status, verdict, evaluation = evaluate(definition, record["measurements"])
        record.update(status=status, hypothesis_verdict=verdict, evaluation=evaluation)
    else:
        record.update(status="error", hypothesis_verdict="not_evaluated", evaluation=None, error=error)
    record["interpretation"] = {"deterministic": _interpretation(record["evidence_class"], record["evaluation"],
                                                                 record["error"]), "model": None}
    return record


# ── local execution ────────────────────────────────────────────────────

def run_experiment(registry: Registry, experiment_id: str, runners: dict[str, RunnerSpec], *,
                   seed: int | None = None, reproduces: str | None = None) -> dict[str, Any]:
    """Execute a registered builtin experiment once and record the run."""
    definition = registry.load_definition(experiment_id)
    runner = definition["runner"]
    if runner["kind"] != "builtin":
        raise ExperimentError(
            f"{experiment_id} executes in {runner['repository']}; submit its runs with "
            f"`experiment record {experiment_id} <submission.json>`"
        )
    spec = runners.get(runner["name"])
    if spec is None:
        raise ExperimentError(f"No registered runner named {runner['name']!r}")
    if spec.evidence_class != definition["evidence_class"]:
        raise ExperimentError(
            f"Runner {spec.name!r} produces {spec.evidence_class} evidence, but {experiment_id} "
            f"declares {definition['evidence_class']}; evidence classes are never relabelled"
        )

    source = None
    parameters = definition["parameters"]
    run_seed = definition["seed"] if seed is None else seed
    if reproduces is not None:
        _, source = registry.resolve_run(reproduces)
        if source["experiment_id"] != experiment_id:
            raise ExperimentError(f"{reproduces} does not belong to {experiment_id}")
        if source["status"] in ("running", "error"):
            raise ExperimentError(f"{reproduces} has status {source['status']}; nothing to reproduce")
        parameters, run_seed = source["parameters"], source["seed"]
    if run_seed is not None and (isinstance(run_seed, bool) or not isinstance(run_seed, int)
                                 or not 0 <= run_seed < 2**32):
        raise ExperimentError("Seed must be an integer in [0, 2^32)")

    run_id, run_dir = registry.begin_run(experiment_id)
    record: dict[str, Any] = {
        "schema_version": RUN_SCHEMA,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "kind": "reproduce" if source else "run",
        "reproduces": source["run_id"] if source else None,
        "status": "running",
        "hypothesis_verdict": "not_evaluated",
        "evidence_class": definition["evidence_class"],
        "started_at": utc_now(),
        "finished_at": None,
        "duration_ms": None,
        "seed": run_seed,
        "parameters": provenance.redact(parameters),
        "definition": definition,
        "definition_sha256": sha256_json(definition),
        "inputs": {}, "measurements": {}, "series": {}, "statistics": {},
        "evaluation": None, "observations": [], "interpretation": {"deterministic": "", "model": None},
        "limitations": [], "artifacts": [], "models": [], "reproduction": None, "error": None,
        "provenance": {
            "source": "local_run",
            "git": provenance.git_state(excluded=[registry.root, registry.results_path]),
            "environment": provenance.environment(),
            "dependencies": provenance.dependency_versions(definition["dependencies"]),
            "subject_files": provenance.hash_repo_files(definition["subsystem"]["paths"]),
            "runner": {
                "name": spec.name,
                "version": spec.version,
                "source": provenance.repo_relative(inspect.getsourcefile(spec.func)),
                "source_sha256": sha256_bytes(Path(inspect.getsourcefile(spec.func)).read_bytes()),
            },
            "recorded_at": utc_now(),
        },
    }
    registry.write_run(run_dir, record)

    context = RunContext(experiment_id, run_id, parameters, run_seed)
    started = time.perf_counter()
    output = None
    error = None
    try:
        output = spec.func(context)
    except KeyboardInterrupt as exc:
        registry.write_run(run_dir, _complete(record, definition, None, _error("execute", exc), started))
        raise
    except Exception as exc:  # recorded, never swallowed: the run shows status 'error'
        error = _error("execute", exc)
    if error is None:
        try:
            output = _check_output(output)
            record["artifacts"] = _store_artifacts(run_dir, definition, context.artifacts)
        except Exception as exc:
            output, error = None, _error("validate_output", exc)
    record = _complete(record, definition, output, error, started)
    if source is not None and record["status"] != "error":
        record["reproduction"] = reproduction_report(definition, source, record)
    registry.write_run(run_dir, record)
    return record


# ── external submissions ───────────────────────────────────────────────

def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentError(f"Invalid timestamp {value!r}") from exc
    if parsed.utcoffset() is None:
        raise ExperimentError(f"Timestamp {value!r} must include a timezone")
    return parsed


def record_submission(registry: Registry, experiment_id: str, submission: Any) -> dict[str, Any]:
    """Admit one externally executed run. Nothing referenced by it is opened or fetched."""
    errors = submission_errors(submission)
    if errors:
        raise ExperimentError("Invalid submission:\n  " + "\n  ".join(errors))
    definition = registry.load_definition(experiment_id)
    if definition["runner"]["kind"] != "external":
        raise ExperimentError(f"{experiment_id} is a builtin experiment; the host runs it, it cannot be submitted")
    if submission["experiment_id"] != experiment_id:
        raise ExperimentError(f"Submission is for {submission['experiment_id']}, not {experiment_id}")
    if submission["experiment_version"] != definition["experiment_version"]:
        raise ExperimentError(
            f"Submission targets v{submission['experiment_version']}; {experiment_id} is "
            f"v{definition['experiment_version']}. Re-run against the current pre-registration."
        )
    if submission["evidence_class"] != definition["evidence_class"]:
        raise ExperimentError("Submission evidence class does not match the registered experiment")
    submission_sha256 = sha256_json(submission)
    for existing in registry.runs(experiment_id):
        if existing["provenance"].get("submission_sha256") == submission_sha256:
            raise ExperimentError(f"This submission is already recorded as {existing['run_id']}")
    started, finished = _parse_time(submission["started_at"]), _parse_time(submission["finished_at"])
    if finished < started:
        raise ExperimentError("finished_at precedes started_at")

    output = RunOutput(
        measurements=submission["measurements"], series=submission["series"], inputs=submission["inputs"],
        observations=submission["observations"], limitations=submission["limitations"],
        models=submission["models"],
    )
    run_id, run_dir = registry.begin_run(experiment_id)
    source_provenance = provenance.redact(submission["provenance"])
    record: dict[str, Any] = {
        "schema_version": RUN_SCHEMA, "experiment_id": experiment_id, "run_id": run_id,
        "kind": "external", "reproduces": None, "status": "running", "hypothesis_verdict": "not_evaluated",
        "evidence_class": definition["evidence_class"],
        "started_at": submission["started_at"], "finished_at": None, "duration_ms": None,
        "seed": submission["seed"], "parameters": provenance.redact(submission["parameters"]),
        "definition": definition, "definition_sha256": sha256_json(definition),
        "inputs": {}, "measurements": {}, "series": {}, "statistics": {}, "evaluation": None,
        "observations": [], "interpretation": {"deterministic": "", "model": None}, "limitations": [],
        "artifacts": [
            {"name": a["name"], "sha256": a["sha256"], "bytes": a["bytes"], "kind": a["kind"], "stored": False,
             "note": "external artifact; referenced by hash, never fetched",
             **({"uri": provenance.redact(a["uri"])} if "uri" in a else {})}
            for a in submission["artifacts"]
        ],
        "models": [], "reproduction": None, "error": None,
        "provenance": {
            "source": "external_submission",
            "submission_sha256": submission_sha256,
            "producer": source_provenance,
            "recorded_by": {"git": provenance.git_state(excluded=[registry.root, registry.results_path]),
                            "environment": provenance.environment()},
            "recorded_at": utc_now(),
        },
    }
    error = submission.get("error")
    record = _complete(record, definition, output, provenance.redact(error) if error else None,
                       time.perf_counter())
    record["finished_at"] = submission["finished_at"]
    record["duration_ms"] = round((finished - started).total_seconds() * 1000.0, 3)
    interpretation = submission.get("model_interpretation")
    if interpretation:
        # Kept apart from the deterministic reading and never used in evaluation.
        record["interpretation"]["model"] = {"origin": "MODEL_INFERRED", **provenance.redact(interpretation)}
    registry.write_run(run_dir, record)
    return record


def load_submission(path: Path) -> Any:
    return read_json(path, limit=8 * 1024 * 1024)
