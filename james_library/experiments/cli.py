"""``python rain_lab.py experiment <command>`` — the experiment registry CLI.

Claim → Run → Measure → Record → Publish → Repeat.

Exit codes: 0 success (including a recorded failed or inconclusive
hypothesis — those are results), 1 verification problems or stale
RESULTS.md, 2 request refused (invalid input, unknown ID), 3 the run was
recorded with status ``error``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .registry import RUN_ID, Registry, check_experiment_id, read_json
from .results import COMPLETED, compare_data, experiment_summary, render_compare, render_results, render_show
from .runner import load_submission, record_submission, run_experiment
from .runners import BUILTIN_RUNNERS
from .schema import ExperimentError
from .verify import verify

COMMANDS = ("create", "list", "show", "run", "reproduce", "verify", "compare", "record", "results")
_CRITERION = re.compile(
    r"^\s*([a-z][a-z0-9_]{0,63})\s*(>=|<=|>|<)\s*(-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)\s*$"
)


def _out(text: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _parse_criteria(items: list[str], prefix: str) -> list[dict[str, Any]]:
    criteria = []
    for index, item in enumerate(items, 1):
        match = _CRITERION.match(item)
        if not match:
            raise ExperimentError(f"Cannot parse criterion {item!r}; use e.g. 'accuracy>=0.7'")
        criteria.append({"id": f"{prefix}{index}", "metric": match.group(1), "op": match.group(2),
                         "value": float(match.group(3))})
    return criteria


def _parse_metric(item: str) -> dict[str, Any]:
    parts = item.split(":")
    if not 1 <= len(parts) <= 3 or (len(parts) == 3 and parts[2] != "timing"):
        raise ExperimentError(f"Cannot parse metric {item!r}; use name[:unit[:timing]]")
    name = parts[0]
    return {"name": name, "unit": parts[1] if len(parts) > 1 else "", "description": name.replace("_", " "),
            "deterministic": len(parts) < 3}


def _fields_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.from_file:
        fields = read_json(Path(args.from_file))
        if not isinstance(fields, dict):
            raise ExperimentError("--from must contain a JSON object")
        for reserved in ("schema_version", "experiment_id", "experiment_version", "created_at"):
            if reserved in fields:
                raise ExperimentError(f"--from draft must not set {reserved!r}; the registry assigns it")
        return fields
    missing = [flag for flag in ("title", "question", "hypothesis") if not getattr(args, flag)]
    if missing:
        raise ExperimentError("create needs --" + ", --".join(missing) + " (or --from draft.json)")
    kind, _, target = args.runner.partition(":")
    if kind not in ("builtin", "external") or not target:
        raise ExperimentError("--runner must be builtin:<name> or external:<repository>")
    runner = {"kind": "builtin", "name": target} if kind == "builtin" else {"kind": "external", "repository": target}
    metrics = [_parse_metric(m) for m in args.metric]
    guards, success, failure = (_parse_criteria(args.guard, "G"), _parse_criteria(args.success, "S"),
                                _parse_criteria(args.failure, "F"))
    declared = {m["name"] for m in metrics}
    for criterion in guards + success + failure:  # criteria imply their metrics
        if criterion["metric"] not in declared:
            declared.add(criterion["metric"])
            metrics.append(_parse_metric(criterion["metric"]))
    return {
        "title": args.title, "question": args.question, "hypothesis": args.hypothesis,
        "rationale": args.rationale,
        "subsystem": {"repository": args.repository, "component": args.component, "paths": args.path},
        "created_by": args.created_by, "evidence_class": args.evidence_class, "runner": runner,
        "seed": args.seed, "parameters": {},
        "procedure": args.procedure or ["Execute the registered runner and record every declared metric."],
        "variables": {"independent": args.independent, "dependent": args.dependent or sorted(declared),
                      "controls": args.control},
        "metrics": metrics, "criteria": {"guards": guards, "success": success, "failure": failure},
        "dependencies": args.dependency,
        "data_policy": {"classification": args.classification, "store_artifacts": not args.hash_only},
        "limitations": args.limitation,
    }


def _publish(registry: Registry, args: argparse.Namespace) -> None:
    if not getattr(args, "no_results", False):
        registry.results_path.write_text(render_results(registry), encoding="utf-8", newline="\n")


def _print_run(record: dict[str, Any]) -> None:
    lines = [f"{record['run_id']}: {record['status'].upper()} ({record['hypothesis_verdict'].replace('_', ' ')})",
             f"  {record['interpretation']['deterministic']}"]
    for name, value in record["measurements"].items():
        lines.append(f"  {name} = {value}")
    if record["reproduction"]:
        rep = record["reproduction"]
        lines.append(f"  reproduces {rep['source_run']}: outcome matches={rep['outcome_matches']}, "
                     f"deterministic metrics match={rep['deterministic_metrics_match']}")
        lines += [f"    mismatch: {m}" for m in rep["mismatches"]]
    _out("\n".join(lines) + "\n")


def _cmd_create(registry: Registry, args: argparse.Namespace) -> int:
    definition = registry.create(_fields_from_args(args))
    _publish(registry, args)
    _out(f"Registered {definition['experiment_id']} (planned): {definition['title']}\n"
         f"  {registry.experiment_dir(definition['experiment_id']) / 'experiment.json'}\n")
    return 0


def _cmd_list(registry: Registry, args: argparse.Namespace) -> int:
    rows = []
    for experiment_id in registry.experiment_ids():
        definition = registry.load_definition(experiment_id)
        summary = experiment_summary(definition, registry.runs(experiment_id))
        rows.append({"experiment_id": experiment_id, "title": definition["title"], "status": summary["status"],
                     "evidence": summary["evidence_level"], "runs": summary["runs"]})
    if args.status:
        rows = [row for row in rows if row["status"] == args.status]
    if args.json:
        _out(json.dumps(rows, indent=2) + "\n")
        return 0
    if not rows:
        _out("No experiments registered. Start with: python rain_lab.py experiment create --help\n")
        return 0
    _out(f"{'ID':<14} {'STATUS':<13} {'EVIDENCE':<11} {'RUNS':>4}  TITLE\n")
    for row in rows:
        _out(f"{row['experiment_id']:<14} {row['status'].upper():<13} {row['evidence']:<11} {row['runs']:>4}  "
             f"{row['title']}\n")
    return 0


def _cmd_show(registry: Registry, args: argparse.Namespace) -> int:
    definition = registry.load_definition(check_experiment_id(args.experiment_id))
    runs = registry.runs(args.experiment_id)
    if args.json:
        _out(json.dumps({"definition": definition, "summary": {
            k: v for k, v in experiment_summary(definition, runs).items() if k not in ("latest", "latest_completed")
        }, "runs": runs}, indent=2, ensure_ascii=False) + "\n")
    else:
        _out(render_show(definition, runs))
    return 0


def _cmd_run(registry: Registry, args: argparse.Namespace) -> int:
    record = run_experiment(registry, check_experiment_id(args.experiment_id), BUILTIN_RUNNERS, seed=args.seed)
    _publish(registry, args)
    _print_run(record)
    return 3 if record["status"] == "error" else 0


def _cmd_reproduce(registry: Registry, args: argparse.Namespace) -> int:
    target = args.target
    if RUN_ID.match(target):
        experiment_id, source = RUN_ID.match(target).group(1), target
    else:
        experiment_id = check_experiment_id(target)
        completed = [r for r in registry.runs(experiment_id) if r["status"] in COMPLETED]
        if not completed:
            raise ExperimentError(f"{experiment_id} has no completed run to reproduce; use `experiment run` first")
        source = completed[-1]["run_id"]
    record = run_experiment(registry, experiment_id, BUILTIN_RUNNERS, reproduces=source)
    _publish(registry, args)
    _print_run(record)
    return 3 if record["status"] == "error" else 0


def _cmd_record(registry: Registry, args: argparse.Namespace) -> int:
    record = record_submission(registry, check_experiment_id(args.experiment_id),
                               load_submission(Path(args.submission)))
    _publish(registry, args)
    _print_run(record)
    return 3 if record["status"] == "error" else 0


def _cmd_verify(registry: Registry, args: argparse.Namespace) -> int:
    ids = [check_experiment_id(i) for i in args.experiment_ids] or None
    report = verify(registry, ids)
    problems = list(report["problems"])
    if ids is None and report["valid"]:
        current = registry.results_path.read_text(encoding="utf-8") if registry.results_path.is_file() else None
        if current != render_results(registry):
            problems.append(f"{registry.results_path.name} is stale; run `python rain_lab.py experiment results`")
    for warning in report["warnings"]:
        _out(f"warning: {warning}\n")
    for problem in problems:
        _out(f"PROBLEM: {problem}\n")
    _out(f"Checked {report['experiments']} experiment(s), {report['runs']} run(s): "
         f"{'OK' if not problems else f'{len(problems)} problem(s)'}\n")
    return 0 if not problems else 1


def _cmd_compare(registry: Registry, args: argparse.Namespace) -> int:
    targets = args.targets
    if len(targets) == 1 and not RUN_ID.match(targets[0]):
        runs = registry.runs(check_experiment_id(targets[0]))
    else:
        runs = [registry.resolve_run(t)[1] for t in targets]
    if len(runs) < 2:
        raise ExperimentError("compare needs at least two runs")
    _out(json.dumps(compare_data(runs), indent=2, ensure_ascii=False) + "\n" if args.json else render_compare(runs))
    return 0


def _cmd_results(registry: Registry, args: argparse.Namespace) -> int:
    text = render_results(registry)
    if args.check:
        current = registry.results_path.read_text(encoding="utf-8") if registry.results_path.is_file() else None
        if current != text:
            _out(f"{registry.results_path} is stale; run `python rain_lab.py experiment results`\n")
            return 1
        _out(f"{registry.results_path} is up to date\n")
        return 0
    registry.results_path.write_text(text, encoding="utf-8", newline="\n")
    _out(f"Wrote {registry.results_path}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--registry", default=None, help="Registry directory (default: <repo>/experiments)")
    parser = argparse.ArgumentParser(
        prog="rain_lab.py experiment",
        description="R.A.I.N. Experiments: Claim → Run → Measure → Record → Publish → Repeat. "
                    "(Without a command, `experiment` runs the legacy CIRCLE simulation CLI.)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", parents=[common], help="Pre-register a new experiment (status: planned)")
    create.add_argument("--from", dest="from_file", help="JSON draft with every definition field")
    create.add_argument("--title")
    create.add_argument("--question")
    create.add_argument("--hypothesis")
    create.add_argument("--rationale", default="Not stated at registration.")
    create.add_argument("--metric", action="append", default=[], help="name[:unit[:timing]] (repeatable)")
    create.add_argument("--guard", action="append", default=[], help="Evidence guard, e.g. 'trials>=20'")
    create.add_argument("--success", action="append", default=[], help="Success criterion, e.g. 'accuracy>=0.7'")
    create.add_argument("--failure", action="append", default=[], help="Failure criterion, e.g. 'accuracy<0.5'")
    create.add_argument("--runner", default="external:topherchris420/james_library",
                        help="builtin:<name> or external:<repository>")
    create.add_argument("--evidence-class", default="measured", choices=["measured", "simulated", "model_inferred"])
    create.add_argument("--seed", type=int, default=None)
    create.add_argument("--repository", default="topherchris420/james_library")
    create.add_argument("--component", default="unspecified")
    create.add_argument("--path", action="append", default=[], help="Repo file under test (hashed per run)")
    create.add_argument("--dependency", action="append", default=[], help="Python package whose version to record")
    create.add_argument("--procedure", action="append", default=[])
    create.add_argument("--independent", action="append", default=[])
    create.add_argument("--dependent", action="append", default=[])
    create.add_argument("--control", action="append", default=[])
    create.add_argument("--limitation", action="append", default=[])
    create.add_argument("--classification", default="internal", choices=["public", "internal", "sensitive"])
    create.add_argument("--hash-only", action="store_true", help="Never store artifact contents")
    create.add_argument("--created-by", default="R.A.I.N.Operator", help="Role label, not a personal name")
    create.add_argument("--no-results", action="store_true", help="Do not regenerate RESULTS.md")

    listing = sub.add_parser("list", parents=[common], help="List registered experiments")
    listing.add_argument("--status", choices=["planned", "running", "passed", "failed", "inconclusive", "error"])
    listing.add_argument("--json", action="store_true")

    show = sub.add_parser("show", parents=[common], help="Definition, latest measurements and provenance")
    show.add_argument("experiment_id")
    show.add_argument("--json", action="store_true")

    run = sub.add_parser("run", parents=[common], help="Execute a builtin experiment and record the run")
    run.add_argument("experiment_id")
    run.add_argument("--seed", type=int, default=None, help="Override the registered seed (recorded)")
    run.add_argument("--no-results", action="store_true")

    reproduce = sub.add_parser("reproduce", parents=[common],
                               help="Re-run with a recorded run's exact parameters and seed, then compare")
    reproduce.add_argument("target", help="Experiment ID (latest completed run) or a run ID")
    reproduce.add_argument("--no-results", action="store_true")

    verify_cmd = sub.add_parser("verify", parents=[common], help="Re-derive every recorded result from stored data")
    verify_cmd.add_argument("experiment_ids", nargs="*")

    compare = sub.add_parser("compare", parents=[common], help="Compare runs of one experiment or listed run IDs")
    compare.add_argument("targets", nargs="+")
    compare.add_argument("--json", action="store_true")

    record = sub.add_parser("record", parents=[common], help="Admit an external run submission (JSON)")
    record.add_argument("experiment_id")
    record.add_argument("submission")
    record.add_argument("--no-results", action="store_true")

    results = sub.add_parser("results", parents=[common], help="Regenerate RESULTS.md from the registry")
    results.add_argument("--check", action="store_true", help="Exit 1 if RESULTS.md is stale")
    return parser


_HANDLERS = {
    "create": _cmd_create, "list": _cmd_list, "show": _cmd_show, "run": _cmd_run, "reproduce": _cmd_reproduce,
    "verify": _cmd_verify, "compare": _cmd_compare, "record": _cmd_record, "results": _cmd_results,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = Registry(args.registry) if args.registry else Registry()
    try:
        return _HANDLERS[args.command](registry, args)
    except (ExperimentError, OSError) as exc:
        _out(f"Refused: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
