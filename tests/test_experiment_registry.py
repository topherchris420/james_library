"""R.A.I.N. Experiments: registry, run pipeline, evaluation, provenance and views."""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

import pytest

from james_library.experiments import cli
from james_library.experiments.evaluate import evaluate
from james_library.experiments.provenance import REDACTED, credential_formats_in, redact
from james_library.experiments.registry import Registry
from james_library.experiments.results import compare_data, render_compare, render_results, render_show
from james_library.experiments.runner import (
    RunnerSpec,
    RunOutput,
    record_submission,
    run_experiment,
)
from james_library.experiments.runners import BUILTIN_RUNNERS
from james_library.experiments.schema import ExperimentError, definition_errors, run_record_errors
from james_library.experiments.stats import percent_change, summarize
from james_library.experiments.verify import verify

PLANTED_VALUE = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"  # assembled so the literal never appears in the repo


def draft(**overrides):
    fields = {
        "title": "R.A.I.N._project accuracy probe",
        "question": "Does the probe reach the target accuracy?",
        "hypothesis": "Accuracy is at least 0.9 over at least 20 trials.",
        "rationale": "Test fixture.",
        "subsystem": {"repository": "R.A.I.N._project", "component": "probe", "paths": []},
        "created_by": "R.A.I.N.Operator",
        "evidence_class": "measured",
        "runner": {"kind": "builtin", "name": "fake"},
        "seed": 11,
        "parameters": {"accuracy": 0.95, "trials": 30},
        "procedure": ["Run the fake probe."],
        "variables": {"independent": [], "dependent": ["accuracy"], "controls": []},
        "metrics": [
            {"name": "accuracy", "unit": "ratio", "description": "fraction correct", "deterministic": True},
            {"name": "trials", "unit": "", "description": "trial count", "deterministic": True},
            {"name": "latency_ms", "unit": "ms", "description": "timing", "deterministic": False},
        ],
        "criteria": {
            "guards": [{"id": "G1", "metric": "trials", "op": ">=", "value": 20}],
            "success": [{"id": "S1", "metric": "accuracy", "op": ">=", "value": 0.9}],
            "failure": [{"id": "F1", "metric": "accuracy", "op": "<", "value": 0.7}],
        },
        "dependencies": ["pytest"],
        "data_policy": {"classification": "public", "store_artifacts": True},
        "limitations": ["Fixture data."],
    }
    fields.update(overrides)
    return fields


def fake_runner(ctx):
    params = ctx.parameters
    if params.get("raise"):
        raise RuntimeError(f"probe crashed with key {PLANTED_VALUE}")
    measurements = {"accuracy": params.get("accuracy"), "trials": params.get("trials"), "latency_ms": 1.5}
    if params.get("drop_accuracy"):
        measurements.pop("accuracy")
    if params.get("nan"):
        measurements["accuracy"] = math.nan
    if params.get("secret_artifact"):
        ctx.add_artifact("log.txt", f"key={PLANTED_VALUE}", "log")
    for artifact in params.get("artifacts", []):
        ctx.add_artifact(artifact["name"], artifact["content"], "fixture")
    return RunOutput(
        measurements=measurements,
        series={"latency_ms": [1.0, 2.0, 1.5]},
        inputs={"note": "fixture", "api_key": PLANTED_VALUE},
        observations=["seed was %s" % ctx.seed],
        models=[{"role": "agent", "name": "fixture-model", "latency_ms": [10.0, 20.0],
                 "request_config": {"max_tokens": 64, "authorization": "Bearer abcdefghijklmnopqrstuv"}}],
    )


_COUNTER = {"n": 0}


def drifting_runner(ctx):
    _COUNTER["n"] += 1
    return RunOutput(measurements={"accuracy": 0.9 + _COUNTER["n"] / 1000, "trials": 30, "latency_ms": 1.0})


RUNNERS = {
    "fake": RunnerSpec("fake", "1", "measured", fake_runner),
    "drifting": RunnerSpec("drifting", "1", "measured", drifting_runner),
    "fake-sim": RunnerSpec("fake-sim", "1", "simulated", fake_runner),
}


@pytest.fixture
def registry(tmp_path):
    return Registry(tmp_path / "experiments")


def create(registry, **overrides):
    return registry.create(draft(**overrides))


# ── IDs and creation ───────────────────────────────────────────────────

def test_ids_are_sequential_and_recorded_in_ledger(registry):
    first, second = create(registry), create(registry)
    assert (first["experiment_id"], second["experiment_id"]) == ("V3D-EXP-0001", "V3D-EXP-0002")
    ledger = json.loads(registry.ledger_path.read_text())
    assert [e["id"] for e in ledger["allocated"]] == ["V3D-EXP-0001", "V3D-EXP-0002"]
    assert first["experiment_version"] == 1 and first["schema_version"] == "rain-experiment/v1"


def test_deleted_experiment_id_is_never_reused(registry):
    create(registry)
    second = create(registry)
    import shutil
    shutil.rmtree(registry.experiment_dir(second["experiment_id"]))
    assert create(registry)["experiment_id"] == "V3D-EXP-0003"
    report = verify(registry)
    assert any("V3D-EXP-0002" in w and "retired" in w for w in report["warnings"])


def test_invalid_definition_is_refused_before_consuming_an_id(registry):
    bad = draft(criteria={"guards": [], "success": [{"id": "S1", "metric": "accuracy", "op": ">=", "value": 1}],
                          "failure": []})
    with pytest.raises(ExperimentError, match="failure"):
        registry.create(bad)
    assert registry.experiment_ids() == []
    assert create(registry)["experiment_id"] == "V3D-EXP-0001"


def test_experiment_json_is_write_once(registry):
    definition = create(registry)
    path = registry.experiment_dir(definition["experiment_id"]) / "experiment.json"
    with pytest.raises(FileExistsError):
        path.open("x")


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(experiment_id="EXP-1"), "experiment_id"),
    (lambda d: d.update(surprise=True), "Additional properties"),
    (lambda d: d["criteria"]["success"][0].update(op="=="), "op"),
    (lambda d: d["criteria"]["success"][0].update(metric="undeclared"), "not declared"),
    (lambda d: d["criteria"]["success"][0].update(id="F9"), "must start with 'S'"),
    (lambda d: d["criteria"]["success"][0].update(value=float("nan")), "finite"),
    (lambda d: d.update(created_by="Jane Doe <jane@example.com>"), "created_by"),
    (lambda d: d["subsystem"].update(paths=["../../etc/passwd"]), "paths"),
    (lambda d: d["subsystem"].update(paths=["/etc/passwd"]), "paths"),
    (lambda d: d.update(evidence_class="anecdotal"), "evidence_class"),
    (lambda d: d["metrics"].append(dict(d["metrics"][0])), "duplicate metric"),
    (lambda d: d.update(procedure=[]), "procedure"),
    (lambda d: d.update(title="   "), "title"),
    (lambda d: d.update(runner={"kind": "shell", "command": "rm -rf /"}), "runner"),
    (lambda d: d.update(runner={"kind": "external", "repository": "x"}), "external experiments cannot hash"),
])
def test_malformed_definitions_are_rejected(mutate, message):
    definition = {"schema_version": "rain-experiment/v1", "experiment_id": "V3D-EXP-0001",
                  "experiment_version": 1, "created_at": "2026-01-01T00:00:00.000Z",
                  **draft(subsystem={"repository": "r", "component": "c", "paths": ["README.md"]})}
    assert definition_errors(copy.deepcopy(definition)) == []
    mutate(definition)
    errors = definition_errors(definition)
    assert errors and any(message in e for e in errors), errors


def test_load_definition_rejects_mismatched_id_and_bad_json(registry):
    definition = create(registry)
    path = registry.experiment_dir("V3D-EXP-0001") / "experiment.json"
    path.write_text(json.dumps({**definition, "experiment_id": "V3D-EXP-0009"}))
    with pytest.raises(ExperimentError, match="declares"):
        registry.load_definition("V3D-EXP-0001")
    path.write_text("{not json")
    with pytest.raises(ExperimentError, match="not valid JSON"):
        registry.load_definition("V3D-EXP-0001")
    with pytest.raises(ExperimentError, match="Not an experiment ID"):
        registry.load_definition("../V3D-EXP-0001")


# ── evaluation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("measurements, status, verdict", [
    ({"accuracy": 0.95, "trials": 30}, "passed", "supported"),
    ({"accuracy": 0.5, "trials": 30}, "failed", "not_supported"),
    ({"accuracy": 0.8, "trials": 30}, "inconclusive", "insufficient_evidence"),
    ({"accuracy": 0.95, "trials": 5}, "inconclusive", "insufficient_evidence"),
    ({"accuracy": 0.2, "trials": 5}, "inconclusive", "insufficient_evidence"),  # small sample decides nothing
    ({"trials": 30}, "inconclusive", "insufficient_evidence"),
    ({"accuracy": None, "trials": 30}, "inconclusive", "insufficient_evidence"),
    ({"accuracy": True, "trials": 30}, "inconclusive", "insufficient_evidence"),  # bools are not numbers
])
def test_deterministic_evaluation(measurements, status, verdict):
    assert evaluate(draft(), measurements)[:2] == (status, verdict)


def test_failure_criterion_dominates_success():
    definition = draft(criteria={
        "guards": [],
        "success": [{"id": "S1", "metric": "accuracy", "op": ">=", "value": 0.9}],
        "failure": [{"id": "F1", "metric": "trials", "op": "<", "value": 50}],
    })
    status, verdict, evaluation = evaluate(definition, {"accuracy": 0.99, "trials": 30})
    assert (status, verdict) == ("failed", "not_supported")
    assert "F1" in evaluation["summary"]


# ── runs ───────────────────────────────────────────────────────────────

def test_passed_run_record_is_complete_and_valid(registry):
    create(registry)
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert record["run_id"] == "V3D-EXP-0001-RUN-0001"
    assert (record["status"], record["hypothesis_verdict"]) == ("passed", "supported")
    assert run_record_errors(record) == []
    on_disk = json.loads((registry.experiment_dir("V3D-EXP-0001") / "runs/RUN-0001/result.json").read_text())
    assert on_disk == record
    assert record["statistics"]["latency_ms"]["n"] == 3
    assert record["statistics"]["model.agent.latency_ms"]["mean"] == 15.0
    assert record["seed"] == 11 and record["evaluation"]["rule"] == "rain-criteria/v1"


def test_failed_hypothesis_is_a_result_not_an_error(registry):
    create(registry, parameters={"accuracy": 0.4, "trials": 30})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert (record["status"], record["hypothesis_verdict"]) == ("failed", "not_supported")
    assert record["error"] is None
    assert "not supported" in record["interpretation"]["deterministic"]


def test_inconclusive_when_guard_unmet(registry):
    create(registry, parameters={"accuracy": 0.99, "trials": 3})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert (record["status"], record["hypothesis_verdict"]) == ("inconclusive", "insufficient_evidence")


def test_missing_measurement_is_inconclusive(registry):
    create(registry, parameters={"accuracy": 0.99, "trials": 30, "drop_accuracy": True})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert record["status"] == "inconclusive"
    assert "missing measurement" in record["evaluation"]["summary"]


def test_execution_error_is_recorded_redacted_and_distinct(registry):
    create(registry, parameters={"raise": True})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert (record["status"], record["hypothesis_verdict"]) == ("error", "not_evaluated")
    assert record["evaluation"] is None
    assert record["error"]["type"] == "RuntimeError" and record["error"]["stage"] == "execute"
    assert PLANTED_VALUE not in json.dumps(record) and REDACTED in record["error"]["message"]
    assert "not a failed hypothesis" in record["interpretation"]["deterministic"]


def test_non_finite_measurement_is_an_execution_error(registry):
    create(registry, parameters={"accuracy": 0.9, "trials": 30, "nan": True})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert record["status"] == "error" and record["error"]["stage"] == "validate_output"


def test_interrupted_run_is_recorded_then_reraised(registry):
    def interrupted(ctx):
        raise KeyboardInterrupt
    create(registry, runner={"kind": "builtin", "name": "stop"})
    with pytest.raises(KeyboardInterrupt):
        run_experiment(registry, "V3D-EXP-0001", {"stop": RunnerSpec("stop", "1", "measured", interrupted)})
    assert registry.runs("V3D-EXP-0001")[0]["status"] == "error"


def test_repeat_runs_never_overwrite_earlier_runs(registry):
    create(registry)
    run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    first = (registry.experiment_dir("V3D-EXP-0001") / "runs/RUN-0001/result.json").read_bytes()
    second = run_experiment(registry, "V3D-EXP-0001", RUNNERS, seed=99)
    assert second["run_id"] == "V3D-EXP-0001-RUN-0002" and second["seed"] == 99
    assert (registry.experiment_dir("V3D-EXP-0001") / "runs/RUN-0001/result.json").read_bytes() == first
    run_dir = registry.experiment_dir("V3D-EXP-0001") / "runs/RUN-0001"
    with pytest.raises(ExperimentError, match="never overwritten"):
        registry.write_run(run_dir, json.loads(first))


def test_invalid_seed_is_refused(registry):
    create(registry)
    for seed in (-1, 2**32, True):
        with pytest.raises(ExperimentError, match="Seed"):
            run_experiment(registry, "V3D-EXP-0001", RUNNERS, seed=seed)
    assert registry.runs("V3D-EXP-0001") == []


def test_refusals_create_no_run(registry):
    create(registry, runner={"kind": "builtin", "name": "missing"})
    with pytest.raises(ExperimentError, match="No registered runner"):
        run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    create(registry, runner={"kind": "builtin", "name": "fake-sim"})
    with pytest.raises(ExperimentError, match="never relabelled"):
        run_experiment(registry, "V3D-EXP-0002", RUNNERS)
    create(registry, runner={"kind": "external", "repository": "R.A.I.N._project/sim"},
           subsystem={"repository": "x", "component": "y", "paths": []})
    with pytest.raises(ExperimentError, match="experiment record"):
        run_experiment(registry, "V3D-EXP-0003", RUNNERS)
    assert all(registry.runs(i) == [] for i in registry.experiment_ids())


def test_reproduce_uses_source_seed_and_parameters_and_matches(registry):
    create(registry)
    source = run_experiment(registry, "V3D-EXP-0001", RUNNERS, seed=5)
    replay = run_experiment(registry, "V3D-EXP-0001", RUNNERS, reproduces=source["run_id"])
    assert replay["kind"] == "reproduce" and replay["reproduces"] == source["run_id"] and replay["seed"] == 5
    assert replay["reproduction"] == {"source_run": source["run_id"], "outcome_matches": True,
                                      "deterministic_metrics_match": True, "mismatches": []}


def test_reproduce_flags_deterministic_drift(registry):
    create(registry, runner={"kind": "builtin", "name": "drifting"})
    source = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    replay = run_experiment(registry, "V3D-EXP-0001", RUNNERS, reproduces=source["run_id"])
    assert replay["reproduction"]["deterministic_metrics_match"] is False
    assert any(m.startswith("accuracy:") for m in replay["reproduction"]["mismatches"])
    assert not any(m.startswith("latency_ms") for m in replay["reproduction"]["mismatches"])


def test_reproduce_refuses_error_runs_and_foreign_runs(registry):
    create(registry, parameters={"raise": True})
    create(registry)
    bad = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    with pytest.raises(ExperimentError, match="nothing to reproduce"):
        run_experiment(registry, "V3D-EXP-0001", RUNNERS, reproduces=bad["run_id"])
    good = run_experiment(registry, "V3D-EXP-0002", RUNNERS)
    with pytest.raises(ExperimentError, match="does not belong"):
        run_experiment(registry, "V3D-EXP-0001", RUNNERS, reproduces=good["run_id"])


# ── artifacts and privacy ──────────────────────────────────────────────

def test_artifacts_are_hashed_and_stored(registry):
    create(registry, parameters={"accuracy": 0.95, "trials": 30,
                                 "artifacts": [{"name": "trace.json", "content": {"steps": [1, 2]}}]})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    (artifact,) = record["artifacts"]
    stored = registry.experiment_dir("V3D-EXP-0001") / "runs/RUN-0001/artifacts/trace.json"
    assert artifact["stored"] and stored.is_file()
    import hashlib
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == artifact["sha256"]


def test_sensitive_data_policy_keeps_hashes_only(registry):
    create(registry, data_policy={"classification": "sensitive", "store_artifacts": True},
           parameters={"accuracy": 0.95, "trials": 30, "artifacts": [{"name": "raw.txt", "content": "biosignal"}]})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert record["artifacts"][0]["stored"] is False and "hashes only" in record["artifacts"][0]["note"]
    assert not (registry.experiment_dir("V3D-EXP-0001") / "runs/RUN-0001/artifacts").exists()


def test_artifact_containing_a_secret_is_withheld(registry):
    create(registry, parameters={"accuracy": 0.95, "trials": 30, "secret_artifact": True})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert record["artifacts"][0]["stored"] is False and "credential-like" in record["artifacts"][0]["note"]
    assert not (registry.experiment_dir("V3D-EXP-0001") / "runs/RUN-0001/artifacts").exists()


@pytest.mark.parametrize("name", ["../escape.txt", ".hidden", "a/b.txt", ""])
def test_unsafe_artifact_names_become_execution_errors(registry, name):
    create(registry, parameters={"accuracy": 0.95, "trials": 30, "artifacts": [{"name": name, "content": "x"}]})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert record["status"] == "error"
    assert not list(registry.root.parent.glob("escape.txt"))


def test_definitions_holding_secrets_are_refused(registry):
    for parameters in ({"api_key": "anything"}, {"note": f"use {PLANTED_VALUE}"}):
        with pytest.raises(ExperimentError, match="credential"):
            create(registry, parameters=parameters)
    assert registry.experiment_ids() == []


def test_secrets_are_redacted_from_records(registry):
    create(registry)
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    text = json.dumps(record)
    assert PLANTED_VALUE not in text and "abcdefghijklmnopqrstuv" not in text
    assert record["inputs"]["api_key"] == REDACTED
    assert record["models"][0]["request_config"] == {"max_tokens": 64, "authorization": REDACTED}


def test_redact_and_credential_formats_in():
    value = {"token": "abc", "max_tokens": 5, "nested": [{"password": "p"}, f"use {PLANTED_VALUE} now"],
             "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz"}
    assert redact(value) == {"token": REDACTED, "max_tokens": 5, "nested": [{"password": REDACTED},
                             f"use {REDACTED} now"], "Authorization": REDACTED}
    assert credential_formats_in("-----BEGIN RSA PRIVATE KEY-----") is True
    assert credential_formats_in("ordinary text about tokens") is False


def test_provenance_captures_reproducibility_metadata(registry):
    create(registry, subsystem={"repository": "r", "component": "c",
                                "paths": ["james_library/experiments/evaluate.py", "missing.py"]})
    record = run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    prov = record["provenance"]
    assert prov["source"] == "local_run"
    assert re.fullmatch(r"[0-9a-f]{40}", prov["git"]["commit"])
    assert isinstance(prov["git"]["dirty"], bool)
    assert set(prov["environment"]) == {"python", "python_implementation", "os", "os_release", "machine",
                                        "cpu_count"}
    assert prov["dependencies"]["pytest"] == pytest.__version__
    subject = {row["path"]: row for row in prov["subject_files"]}
    assert re.fullmatch(r"[0-9a-f]{64}", subject["james_library/experiments/evaluate.py"]["sha256"])
    assert subject["missing.py"]["note"] == "missing"
    assert prov["runner"]["source"] == "tests/test_experiment_registry.py"
    assert str(Path.home()) not in json.dumps(record)
    assert record["definition_sha256"] and record["definition"]["experiment_id"] == "V3D-EXP-0001"


# ── verification ───────────────────────────────────────────────────────

def _run_path(registry, run="RUN-0001"):
    return registry.experiment_dir("V3D-EXP-0001") / "runs" / run / "result.json"


def _tamper(registry, change):
    path = _run_path(registry)
    record = json.loads(path.read_text())
    change(record)
    path.write_text(json.dumps(record))


@pytest.fixture
def verified(registry):
    create(registry, parameters={"accuracy": 0.95, "trials": 30,
                                 "artifacts": [{"name": "trace.txt", "content": "ok"}]})
    run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    assert verify(registry)["valid"]
    return registry


@pytest.mark.parametrize("change, message", [
    (lambda r: r["measurements"].update(accuracy=0.5), "evaluate to failed"),
    (lambda r: r.update(status="failed", hypothesis_verdict="not_supported"), "evaluate to passed"),
    (lambda r: r["series"]["latency_ms"].append(99.0), "statistics"),
    (lambda r: r["definition"]["criteria"]["success"][0].update(value=0.1), "definition snapshot"),
    (lambda r: r.update(run_id="V3D-EXP-0002-RUN-0001"), "run_id"),
    (lambda r: r.update(status="error"), "error"),
    (lambda r: r["observations"].append(PLANTED_VALUE), "credential"),
])
def test_verify_detects_tampered_records(verified, change, message):
    _tamper(verified, change)
    report = verify(verified)
    assert not report["valid"] and any(message in p for p in report["problems"]), report["problems"]


def test_verify_detects_artifact_tampering_and_untracked_files(verified):
    artifacts = _run_path(verified).parent / "artifacts"
    (artifacts / "trace.txt").write_text("changed")
    (artifacts / "extra.bin").write_bytes(b"x")
    problems = verify(verified)["problems"]
    assert any("does not match its recorded SHA-256" in p for p in problems)
    assert any("untracked file" in p for p in problems)


def test_verify_requires_version_bump_when_definition_changes(verified):
    path = verified.experiment_dir("V3D-EXP-0001") / "experiment.json"
    definition = json.loads(path.read_text())
    definition["hypothesis"] = "A quietly different claim."
    path.write_text(json.dumps(definition))
    assert any("without bumping" in p for p in verify(verified)["problems"])
    definition["experiment_version"] = 2
    path.write_text(json.dumps(definition))
    assert verify(verified)["valid"]


def test_verify_reports_unledgered_experiment_and_running_runs(verified):
    ledger = json.loads(verified.ledger_path.read_text())
    ledger["allocated"] = []
    verified.ledger_path.write_text(json.dumps(ledger))
    assert any("not in registry.json" in p for p in verify(verified)["problems"])
    _tamper(verified, lambda r: r.update(status="running"))
    assert any("still marked running" in w for w in verify(verified)["warnings"])


# ── external submissions ───────────────────────────────────────────────

def external(registry):
    return create(registry, runner={"kind": "external", "repository": "R.A.I.N._project/simulator",
                                    "adapter": "report_run"},
                  subsystem={"repository": "R.A.I.N._project/simulator", "component": "agent", "paths": []})


def submission(**overrides):
    body = {
        "schema_version": "rain-experiment-submission/v1",
        "experiment_id": "V3D-EXP-0001", "experiment_version": 1, "evidence_class": "measured",
        "started_at": "2026-09-29T10:00:00Z", "finished_at": "2026-09-29T10:05:00Z", "seed": 3,
        "parameters": {"mode": "calibrated"}, "inputs": {"level": "fixture"},
        "measurements": {"accuracy": 0.93, "trials": 25, "latency_ms": 310.0},
        "series": {"latency_ms": [300.0, 320.0, 310.0]}, "observations": ["fixture"], "limitations": [],
        "artifacts": [{"name": "replay.bin", "sha256": "a" * 64, "bytes": 10, "kind": "replay",
                       "uri": "file:///never/opened"}],
        "models": [{"role": "agent", "name": "fixture-agent", "provider": "fixture", "calls": 3,
                    "latency_ms": [100.0, 110.0], "validation": {"passed": 3, "failed": 0}}],
        "provenance": {"producer": "R.A.I.N._service", "repository": "R.A.I.N._project/simulator",
                       "commit": "abcdef1234567", "dirty": False},
    }
    body.update(overrides)
    return body


def test_external_submission_is_evaluated_by_the_host(registry):
    external(registry)
    record = record_submission(registry, "V3D-EXP-0001", submission())
    assert record["kind"] == "external" and record["status"] == "passed"
    assert record["duration_ms"] == 300000.0
    assert record["artifacts"][0]["stored"] is False and "never fetched" in record["artifacts"][0]["note"]
    assert record["provenance"]["producer"]["commit"] == "abcdef1234567"
    assert verify(registry)["valid"]


def test_producer_cannot_declare_its_own_status(registry):
    external(registry)
    for field, value in (("status", "passed"), ("hypothesis_verdict", "supported")):
        with pytest.raises(ExperimentError, match="Additional properties"):
            record_submission(registry, "V3D-EXP-0001", submission(**{field: value}))
    assert registry.runs("V3D-EXP-0001") == []


@pytest.mark.parametrize("overrides, message", [
    ({"experiment_version": 2}, "Re-run against"),
    ({"experiment_id": "V3D-EXP-0002"}, "not V3D-EXP-0001"),
    ({"evidence_class": "simulated"}, "evidence class"),
    ({"finished_at": "2026-09-29T09:00:00Z"}, "precedes"),
    ({"started_at": "2026-09-29T10:00:00.000000"}, "timezone"),
    ({"measurements": {"accuracy": "high"}}, "measurements"),
    ({"provenance": {"producer": "x"}}, "provenance"),
])
def test_invalid_submissions_are_rejected(registry, overrides, message):
    external(registry)
    with pytest.raises(ExperimentError, match=message):
        record_submission(registry, "V3D-EXP-0001", submission(**overrides))


def test_builtin_experiments_refuse_submissions(registry):
    create(registry)
    with pytest.raises(ExperimentError, match="builtin"):
        record_submission(registry, "V3D-EXP-0001", submission())


def test_external_error_and_model_interpretation_stay_separate(registry):
    external(registry)
    failed = record_submission(registry, "V3D-EXP-0001", submission(
        measurements={"accuracy": 0.2, "trials": 25},
        model_interpretation={"model": "fixture-agent", "text": "Clearly a success."}))
    assert failed["status"] == "failed"  # the model's opinion does not move the status
    assert failed["interpretation"]["model"]["origin"] == "MODEL_INFERRED"
    crashed = record_submission(registry, "V3D-EXP-0001", submission(
        error={"stage": "launch", "type": "Timeout", "message": f"auth {PLANTED_VALUE} failed"}))
    assert (crashed["status"], crashed["hypothesis_verdict"]) == ("error", "not_evaluated")
    assert PLANTED_VALUE not in json.dumps(crashed)
    assert verify(registry)["valid"]


# ── statistics, views, comparison ──────────────────────────────────────

def test_summary_statistics():
    s = summarize([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert (s["n"], s["mean"], s["median"], s["min"], s["max"]) == (8, 5.0, 4.5, 2.0, 9.0)
    assert s["variance"] == pytest.approx(32 / 7) and s["stdev"] == pytest.approx(math.sqrt(32 / 7))
    assert "too small for inference" in s["note"]
    assert summarize([3.0])["stdev"] is None and "undefined" in summarize([3.0])["note"]
    assert summarize([])["n"] == 0 and summarize([])["mean"] is None
    assert summarize([float(i) for i in range(20)])["note"] is None
    assert percent_change(50.0, 75.0) == 50.0 and percent_change(-4.0, -2.0) == 50.0
    assert percent_change(0.0, 1.0) is None and percent_change(None, 1.0) is None


def test_compare_separates_observed_evaluated_and_model_sections(registry):
    external(registry)
    record_submission(registry, "V3D-EXP-0001", submission(measurements={"accuracy": 0.8, "trials": 25}))
    record_submission(registry, "V3D-EXP-0001", submission(
        measurements={"accuracy": 0.92, "trials": 25},
        model_interpretation={"model": "fixture-agent", "text": "Calibration helped."}))
    runs = registry.runs("V3D-EXP-0001")
    data = compare_data(runs)
    assert data["metrics"]["accuracy"]["percent_change_first_to_last"] == pytest.approx(15.0)
    assert data["metrics"]["trials"]["identical"] is True
    text = render_compare(runs)
    observed, rest = text.split("DETERMINISTIC EVALUATION")
    evaluated, model = rest.split("OPTIONAL MODEL INTERPRETATION")
    assert "Calibration helped" in model and "Calibration helped" not in observed + evaluated
    assert "no significance test" in evaluated


def test_results_markdown_is_deterministic_and_surfaces_negatives(registry):
    create(registry, title="Supported probe")
    create(registry, title="Refuted probe", parameters={"accuracy": 0.3, "trials": 30})
    create(registry, title="Planned probe")
    run_experiment(registry, "V3D-EXP-0001", RUNNERS)
    run_experiment(registry, "V3D-EXP-0002", RUNNERS)
    text = render_results(registry)
    assert text == render_results(registry)
    assert "**3 experiments · 2 runs** — 1 passed · 1 failed · 1 planned" in text
    negatives = text.split("## Negative and inconclusive results")[1].split("## V3D-EXP-0001")[0]
    assert "V3D-EXP-0002 — FAILED" in negatives and "Supported probe" not in negatives
    planned = text.split("## V3D-EXP-0003")[1]
    assert "Pre-registered criteria" in planned and "F1: accuracy < 0.7" in planned
    show = render_show(registry.load_definition("V3D-EXP-0001"), registry.runs("V3D-EXP-0001"))
    assert "OBSERVED DATA" in show and "PROVENANCE" in show and "reproduce V3D-EXP-0001" in show


def test_evidence_levels_do_not_blur(registry):
    from james_library.experiments.results import experiment_summary
    create(registry)
    create(registry, runner={"kind": "builtin", "name": "fake-sim"}, evidence_class="simulated")
    create(registry, evidence_class="model_inferred", runner={"kind": "builtin", "name": "inferred"})
    runners = {**RUNNERS, "inferred": RunnerSpec("inferred", "1", "model_inferred", fake_runner)}
    levels = lambda i: experiment_summary(registry.load_definition(i), registry.runs(i))["evidence_level"]  # noqa: E731
    assert levels("V3D-EXP-0001") == "proposed"
    source = run_experiment(registry, "V3D-EXP-0001", runners)
    assert levels("V3D-EXP-0001") == "measured"
    run_experiment(registry, "V3D-EXP-0001", runners, reproduces=source["run_id"])
    assert levels("V3D-EXP-0001") == "reproduced"
    sim = run_experiment(registry, "V3D-EXP-0002", runners)
    run_experiment(registry, "V3D-EXP-0002", runners, reproduces=sim["run_id"])
    assert levels("V3D-EXP-0002") == "simulated"
    run_experiment(registry, "V3D-EXP-0003", runners)
    assert levels("V3D-EXP-0003") == "inferred"


# ── CLI and launcher ───────────────────────────────────────────────────

def test_cli_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "BUILTIN_RUNNERS", RUNNERS)
    reg = ["--registry", str(tmp_path / "experiments")]
    assert cli.main(["create", "--title", "Probe", "--question", "Does it work?", "--hypothesis", "It works.",
                     "--runner", "builtin:fake", "--seed", "4", "--metric", "accuracy:ratio",
                     "--metric", "latency_ms:ms:timing", "--guard", "trials>=20", "--success", "accuracy>=0.9",
                     "--failure", "accuracy<0.7", *reg]) == 0
    definition = json.loads((tmp_path / "experiments/V3D-EXP-0001/experiment.json").read_text())
    assert definition["runner"] == {"kind": "builtin", "name": "fake"} and definition["parameters"] == {}
    assert {m["name"]: m["deterministic"] for m in definition["metrics"]} == {
        "accuracy": True, "latency_ms": False, "trials": True}
    assert cli.main(["run", "V3D-EXP-0001", *reg]) == 0  # fake runner: no parameters → accuracy missing
    assert cli.main(["reproduce", "V3D-EXP-0001", *reg]) == 0
    assert cli.main(["list", *reg]) == 0
    assert cli.main(["show", "V3D-EXP-0001", *reg]) == 0
    assert cli.main(["compare", "V3D-EXP-0001", *reg]) == 0
    assert cli.main(["compare", "V3D-EXP-0001-RUN-0001", "V3D-EXP-0001-RUN-0002", "--json", *reg]) == 0
    assert cli.main(["verify", *reg]) == 0
    assert cli.main(["results", "--check", *reg]) == 0
    out = capsys.readouterr().out
    assert "V3D-EXP-0001" in out and "INCONCLUSIVE" in out
    (tmp_path / "RESULTS.md").write_text("# edited by hand\n")
    assert cli.main(["results", "--check", *reg]) == 1
    assert cli.main(["verify", *reg]) == 1
    assert cli.main(["show", "V3D-EXP-9999", *reg]) == 2
    assert cli.main(["compare", "V3D-EXP-0001-RUN-0001", *reg]) == 2
    assert cli.main(["create", "--title", "x", "--question", "q", "--hypothesis", "h",
                     "--success", "accuracy >= high", *reg]) == 2


def test_cli_run_error_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "BUILTIN_RUNNERS", RUNNERS)
    registry = Registry(tmp_path / "experiments")
    create(registry, parameters={"raise": True})
    assert cli.main(["run", "V3D-EXP-0001", "--registry", str(registry.root)]) == 3


def test_create_from_draft_rejects_reserved_fields(tmp_path):
    path = tmp_path / "draft.json"
    path.write_text(json.dumps({**draft(), "experiment_id": "V3D-EXP-0042"}))
    assert cli.main(["create", "--from", str(path), "--registry", str(tmp_path / "experiments")]) == 2
    path.write_text(json.dumps(draft()))
    assert cli.main(["create", "--from", str(path), "--registry", str(tmp_path / "experiments")]) == 0


def test_launcher_routes_registry_verbs_and_keeps_legacy_flags(tmp_path, monkeypatch):
    from james_library.launcher import rain_lab
    assert rain_lab.main(["experiment", "list", "--registry", str(tmp_path / "experiments")]) == 0
    calls = []
    import james_library.services.experiment_protocol.cli as legacy
    monkeypatch.setattr(legacy, "main", lambda argv: calls.append(argv) or 0)
    assert rain_lab.main(["experiment", "--fixture", "positive"]) == 0
    assert calls == [["--fixture", "positive"]]


# ── the committed registry and builtin runners ─────────────────────────

def test_committed_registry_verifies_and_results_are_current():
    registry = Registry()
    report = verify(registry)
    assert report["valid"], report["problems"]
    assert registry.results_path.read_text(encoding="utf-8") == render_results(registry)


def test_every_committed_builtin_experiment_names_a_registered_runner():
    registry = Registry()
    for experiment_id in registry.experiment_ids():
        definition = registry.load_definition(experiment_id)
        if definition["runner"]["kind"] == "builtin":
            spec = BUILTIN_RUNNERS[definition["runner"]["name"]]
            assert spec.evidence_class == definition["evidence_class"]


def _deterministic(record):
    return {k: v for k, v in record["measurements"].items() if "latency" not in k}


@pytest.mark.parametrize("runner, parameters", [
    ("citation-discrimination", {"corpus_dir": "papers", "quotes": 3, "min_words": 8, "max_words": 10}),
    ("citation-typography", {"corpus_dir": "papers", "quotes": 3, "min_words": 8, "max_words": 10}),
    ("circle-error-rates", {"trials_per_condition": 3, "sample_count": 20, "baseline_mean": 100.0,
                            "noise_std": 1.2, "phantom_effect": 0.1, "true_effect_ohms": -6.5,
                            "minimum_effect_ohms": 5.0}),
])
def test_builtin_runners_replay_deterministically(registry, runner, parameters):
    spec = BUILTIN_RUNNERS[runner]
    create(registry, runner={"kind": "builtin", "name": runner}, evidence_class=spec.evidence_class,
           parameters=parameters, seed=123)
    first = run_experiment(registry, "V3D-EXP-0001", BUILTIN_RUNNERS)
    second = run_experiment(registry, "V3D-EXP-0001", BUILTIN_RUNNERS, reproduces=first["run_id"])
    assert first["error"] is None and second["error"] is None
    assert _deterministic(first) == _deterministic(second)
    assert len(first["measurements"]) > 3


def test_citation_runner_rejects_corpus_outside_repository(registry):
    create(registry, runner={"kind": "builtin", "name": "citation-discrimination"},
           parameters={"corpus_dir": "../..", "quotes": 2, "min_words": 8, "max_words": 10})
    record = run_experiment(registry, "V3D-EXP-0001", BUILTIN_RUNNERS)
    assert record["status"] == "error" and "inside the repository" in record["error"]["message"]
