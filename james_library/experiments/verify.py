"""Re-derive every recorded conclusion from the stored data.

``verify`` never trusts a stored status: it re-validates the record against
its schema, recomputes statistics from the stored series, re-applies the
embedded pre-registered criteria to the stored measurements, re-hashes stored
artifacts and scans for credential patterns. SHA-256 detects inconsistency;
it is not a signature, so a writer able to rewrite both data and records can
still forge them. Git history is the tamper-evidence layer.
"""

from __future__ import annotations

from typing import Any

from .evaluate import evaluate
from .provenance import credential_formats_in
from .registry import Registry, read_json
from .runner import reproduction_report
from .schema import ExperimentError, definition_errors, run_record_errors, sha256_bytes, sha256_json
from .stats import summarize


def _verify_run(registry: Registry, experiment_id: str, definition: dict, run_dir) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    label = f"{experiment_id}/{run_dir.name}"
    path = run_dir / "result.json"
    if not path.is_file():
        return [f"{label}: missing result.json"], warnings
    raw = path.read_text(encoding="utf-8")
    if credential_formats_in(raw):
        problems.append(f"{label}: credential-like pattern present in record")
    try:
        record = read_json(path)
    except ExperimentError as exc:
        return problems + [f"{label}: {exc}"], warnings
    errors = run_record_errors(record)
    if errors:
        return problems + [f"{label}: {e}" for e in errors], warnings
    if record["run_id"] != f"{experiment_id}-{run_dir.name}":
        problems.append(f"{label}: run_id {record['run_id']} does not match its directory")
    if record["status"] == "running":
        warnings.append(f"{label}: still marked running (interrupted or in progress); not evaluated")
        return problems, warnings

    snapshot = record["definition"]
    if snapshot["experiment_version"] == definition["experiment_version"] and \
            record["definition_sha256"] != sha256_json(definition):
        problems.append(f"{label}: experiment.json was edited after this run without bumping experiment_version")
    elif snapshot["experiment_version"] > definition["experiment_version"]:
        problems.append(f"{label}: run references a newer definition version than experiment.json")

    recomputed = {name: summarize(values) for name, values in record["series"].items()}
    for name, summary in recomputed.items():
        if record["statistics"].get(name) != summary:
            problems.append(f"{label}: statistics for {name!r} do not match the stored series")

    if record["status"] == "error":
        if record["hypothesis_verdict"] != "not_evaluated" or record["evaluation"] is not None:
            problems.append(f"{label}: an error run must not carry a hypothesis evaluation")
    else:
        status, verdict, evaluation = evaluate(snapshot, record["measurements"])
        if (status, verdict) != (record["status"], record["hypothesis_verdict"]):
            problems.append(
                f"{label}: recorded {record['status']}/{record['hypothesis_verdict']} but the stored "
                f"measurements evaluate to {status}/{verdict}"
            )
        else:
            # Compare the structured evaluation; the summary sentence is presentation and may be reworded.
            structured = {k: v for k, v in evaluation.items() if k != "summary"}
            if structured != {k: v for k, v in record["evaluation"].items() if k != "summary"}:
                problems.append(f"{label}: stored evaluation detail differs from recomputation")

    problems.extend(_verify_reproduction(registry, experiment_id, label, record))

    artifact_dir = run_dir / "artifacts"
    stored_names = set()
    for artifact in record["artifacts"]:
        if not artifact["stored"]:
            continue
        stored_names.add(artifact["name"])
        target = artifact_dir / artifact["name"]
        if target.is_symlink() or not target.is_file():
            problems.append(f"{label}: stored artifact {artifact['name']} is missing")
        elif sha256_bytes(target.read_bytes()) != artifact["sha256"]:
            problems.append(f"{label}: artifact {artifact['name']} does not match its recorded SHA-256")
    if artifact_dir.is_dir():
        for extra in sorted(p.name for p in artifact_dir.iterdir() if p.name not in stored_names):
            problems.append(f"{label}: untracked file in artifacts/: {extra}")
    return problems, warnings


def _verify_reproduction(registry: Registry, experiment_id: str, label: str, record: dict) -> list[str]:
    """Recompute the reproduction claim from the source run; never trust the stored comparison."""
    kind, source_id, stored = record["kind"], record["reproduces"], record["reproduction"]
    if kind != "reproduce":
        if source_id is not None or stored is not None:
            return [f"{label}: only a reproduce run may carry reproduction data"]
        return []
    if source_id is None:
        return [f"{label}: reproduce run does not name its source run"]
    if record["status"] == "error":
        return [] if stored is None else [f"{label}: an error run must not carry a reproduction claim"]
    if stored is None or stored["source_run"] != source_id:
        return [f"{label}: reproduction claim is missing or names a different source run"]
    try:
        _, source = registry.resolve_run(source_id)
    except ExperimentError as exc:
        return [f"{label}: reproduction source unavailable: {exc}"]
    if source["experiment_id"] != experiment_id or \
            int(source_id.rsplit("-", 1)[1]) >= int(record["run_id"].rsplit("-", 1)[1]):
        return [f"{label}: reproduction source must be an earlier run of the same experiment"]
    if source["status"] not in ("passed", "failed", "inconclusive"):
        return [f"{label}: reproduction source {source_id} has no completed result"]
    if reproduction_report(record["definition"], source, record) != stored:
        return [f"{label}: stored reproduction claim differs from recomputation against {source_id}"]
    return []


def verify(registry: Registry, experiment_ids: list[str] | None = None) -> dict[str, Any]:
    problems: list[str] = []
    warnings: list[str] = []
    checked_runs = 0
    try:
        ledger_ids = {entry.get("id") for entry in registry.ledger()["allocated"]}
    except ExperimentError as exc:
        problems.append(str(exc))
        ledger_ids = set()
    directories = registry.experiment_ids()
    if experiment_ids is None:
        for missing in sorted(ledger_ids - set(directories)):
            warnings.append(f"{missing}: allocated in registry.json but has no directory (ID stays retired)")
    for experiment_id in experiment_ids or directories:
        if experiment_id not in ledger_ids:
            problems.append(f"{experiment_id}: directory exists but the ID is not in registry.json")
        definition_path = registry.experiment_dir(experiment_id) / "experiment.json"
        if not definition_path.is_file():
            problems.append(f"{experiment_id}: missing experiment.json")
            continue
        try:
            definition = read_json(definition_path)
        except ExperimentError as exc:
            problems.append(f"{experiment_id}: {exc}")
            continue
        errors = definition_errors(definition)
        if errors:
            problems.extend(f"{experiment_id}/experiment.json: {e}" for e in errors)
            continue
        if definition["experiment_id"] != experiment_id:
            problems.append(f"{experiment_id}: experiment.json declares {definition['experiment_id']}")
            continue
        for run_dir in registry.run_dirs(experiment_id):
            run_problems, run_warnings = _verify_run(registry, experiment_id, definition, run_dir)
            problems.extend(run_problems)
            warnings.extend(run_warnings)
            checked_runs += 1
    return {"valid": not problems, "problems": problems, "warnings": warnings,
            "experiments": len(experiment_ids or directories), "runs": checked_runs}
