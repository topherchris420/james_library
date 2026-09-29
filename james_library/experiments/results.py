"""Human-readable views of the registry: RESULTS.md, ``show`` and ``compare``.

Everything here is a pure function of the stored records, so regenerating
RESULTS.md from the same registry yields identical bytes (``results --check``).
Model-written interpretation is printed only in its own labelled section.
"""

from __future__ import annotations

import os
from typing import Any

from .registry import Registry
from .stats import percent_change, summarize

COMPLETED = ("passed", "failed", "inconclusive")
_OP_TEXT = {">=": "≥", ">": ">", "<=": "≤", "<": "<"}
_VERDICT_TEXT = {
    "supported": "hypothesis supported",
    "not_supported": "hypothesis not supported",
    "insufficient_evidence": "insufficient evidence",
    "not_evaluated": "not evaluated (execution error)",
}


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".6g")
    return str(value)


def criterion_text(criterion: dict[str, Any]) -> str:
    return f"{criterion['id']}: {criterion['metric']} {_OP_TEXT[criterion['op']]} {fmt(criterion['value'])}"


def short_commit(run: dict[str, Any]) -> str:
    prov = run["provenance"]
    git = prov.get("git") if prov.get("source") == "local_run" else prov.get("producer", {})
    commit = (git or {}).get("commit")
    if not commit:
        return "unknown"
    dirty = (git or {}).get("dirty")
    return commit[:10] + (" (dirty)" if dirty else "" if dirty is False else "")


def experiment_summary(definition: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [r for r in runs if r["status"] in COMPLETED]
    latest = runs[-1] if runs else None
    status = latest["status"] if latest else "planned"
    reproductions = [r for r in completed if r["kind"] == "reproduce" and r["reproduction"]]
    matched = [r for r in reproductions
               if r["reproduction"]["outcome_matches"] and r["reproduction"]["deterministic_metrics_match"]]
    external_agree = (definition["runner"]["kind"] == "external" and len(completed) >= 2
                      and len({r["status"] for r in completed}) == 1)
    evidence_class = definition["evidence_class"]
    if not completed:
        level = "proposed"
    elif evidence_class == "model_inferred":
        level = "inferred"
    elif evidence_class == "simulated":
        level = "simulated"
    elif matched and len(matched) == len(reproductions) or external_agree:
        level = "reproduced"
    else:
        level = "measured"
    if reproductions:
        reproduction = f"{len(matched)} of {len(reproductions)} reproduction(s) matched the source run"
    elif external_agree:
        reproduction = f"{len(completed)} independent external runs agree"
    else:
        reproduction = "not yet reproduced" if completed else "not run"
    counts = {s: sum(1 for r in runs if r["status"] == s) for s in ("passed", "failed", "inconclusive", "error")}
    return {
        "status": status,
        "verdict": latest["hypothesis_verdict"] if latest else None,
        "evidence_level": level,
        "reproduction": reproduction,
        "runs": len(runs),
        "counts": counts,
        "latest": latest,
        "latest_completed": completed[-1] if completed else None,
    }


def _criterion_result(c: dict[str, Any]) -> str:
    return f"{criterion_text(c)} (observed {fmt(c['observed'])})"


def outcome_reason(run: dict[str, Any]) -> str:
    """Why a run ended where it did, built from the structured evaluation."""
    if run["error"]:
        return f"Execution error at {run['error']['stage']} ({run['error']['type']}); hypothesis not evaluated."
    evaluation = run["evaluation"]
    if run["status"] == "failed":
        hits = [c for c in evaluation["failure"] if c["holds"] is True]
        return "Failure criterion met: " + "; ".join(_criterion_result(c) for c in hits) + "."
    if run["status"] == "inconclusive":
        guards = [c for c in evaluation["guards"] if c["holds"] is not True]
        if guards:
            return "Evidence guard not met: " + "; ".join(_criterion_result(c) for c in guards) + "."
        unmet = [c for c in evaluation["success"] if c["holds"] is not True]
        return "Success criteria not met: " + "; ".join(_criterion_result(c) for c in unmet) + "."
    return evaluation["summary"]


def key_measurement(definition: dict[str, Any], run: dict[str, Any] | None) -> str:
    """The first success criterion's metric: what was observed against what was required."""
    criterion = definition["criteria"]["success"][0]
    if run is None or run["evaluation"] is None:
        return f"{criterion['metric']}: — (needs {_OP_TEXT[criterion['op']]} {fmt(criterion['value'])})"
    observed = run["measurements"].get(criterion["metric"])
    return f"{criterion['metric']} = {fmt(observed)} (needs {_OP_TEXT[criterion['op']]} {fmt(criterion['value'])})"


def _unit(metric: dict[str, Any]) -> str:
    return f" {metric['unit']}" if metric["unit"] not in ("", "ratio", "count") else ""


def _run_counts(summary: dict[str, Any]) -> str:
    parts = [f"{n} {s}" for s, n in summary["counts"].items() if n]
    return ", ".join(parts) if parts else "none completed"


def _load_all(registry: Registry) -> list[tuple[dict, list[dict], dict]]:
    rows = []
    for experiment_id in registry.experiment_ids():
        definition = registry.load_definition(experiment_id)
        runs = registry.runs(experiment_id)
        rows.append((definition, runs, experiment_summary(definition, runs)))
    return rows


def render_results(registry: Registry) -> str:
    rows = _load_all(registry)
    base = os.path.relpath(registry.root, registry.results_path.parent).replace(os.sep, "/")
    total_runs = sum(s["runs"] for _, _, s in rows)
    status_counts = {s: sum(1 for _, _, x in rows if x["status"] == s)
                     for s in ("passed", "failed", "inconclusive", "error", "running", "planned")}
    levels = {lv: sum(1 for _, _, x in rows if x["evidence_level"] == lv)
              for lv in ("reproduced", "measured", "simulated", "inferred", "proposed")}

    out = [
        "# Experimental Results",
        "",
        f"<!-- Generated from {base}/ by `python rain_lab.py experiment results`. Do not edit by hand. -->",
        "",
        "What R.A.I.N. actually ran, and what happened. Each status is computed by host code",
        "from recorded measurements against criteria registered *before* the run; no model",
        "decides it. Failed and inconclusive results stay on the record.",
        f"How to add one: [EXPERIMENTS.md](EXPERIMENTS.md). Raw records: [`{base}/`]({base}/).",
        "",
        f"**{len(rows)} experiments · {total_runs} runs** — "
        + " · ".join(f"{n} {s}" for s, n in status_counts.items() if n or s in ("passed", "failed")),
        "",
        "Evidence: " + " · ".join(f"{n} {lv}" for lv, n in levels.items() if n) if rows else "Evidence: none yet",
        "",
        "| ID | Experiment | Result | Key measurement | Evidence | Runs |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for definition, _, summary in rows:
        eid = definition["experiment_id"]
        key = key_measurement(definition, summary["latest_completed"])
        out.append(f"| [{eid}](#{eid.lower()}) | {definition['title']} | **{summary['status'].upper()}** "
                   f"| {key} | {summary['evidence_level']} | {summary['runs']} |")
    out += ["", "## Negative and inconclusive results", ""]
    negatives = [(d, s) for d, _, s in rows if s["status"] in ("failed", "inconclusive", "error")]
    if not negatives:
        out.append("None recorded yet.")
    for definition, summary in negatives:
        out.append(f"- **{definition['experiment_id']} — {summary['status'].upper()}**: "
                   f"{definition['title']}. {outcome_reason(summary['latest'])}")

    for definition, runs, summary in rows:
        out += ["", *_render_experiment(definition, runs, summary, base)]
    return "\n".join(out).rstrip() + "\n"


def _render_experiment(definition: dict, runs: list[dict], summary: dict, base: str) -> list[str]:
    eid = definition["experiment_id"]
    out = [
        f"## {eid}",
        "",
        f"### {definition['title']}",
        "",
        f"**Result: {summary['status'].upper()}**"
        + (f" — {_VERDICT_TEXT[summary['verdict']]}" if summary["verdict"] else " — no runs yet")
        + f" · evidence: {summary['evidence_level']} · runs: {summary['runs']} ({_run_counts(summary)})",
        "",
        f"**Question:** {definition['question']}",
        "",
        f"**Hypothesis:** {definition['hypothesis']}",
        "",
    ]
    criteria = definition["criteria"]
    by_metric: dict[str, list[str]] = {}
    for group in ("guards", "success", "failure"):
        for criterion in criteria[group]:
            by_metric.setdefault(criterion["metric"], []).append(criterion_text(criterion))
    reference = summary["latest_completed"]
    if reference is None:
        out.append("**Pre-registered criteria** (nothing measured yet):")
        out.append("")
        for group, label in (("guards", "Guard"), ("success", "Success"), ("failure", "Failure")):
            for criterion in criteria[group]:
                out.append(f"- {label} {criterion_text(criterion)}")
        runner = definition["runner"]
        where = f"`{runner['repository']}` via `experiment record`" if runner["kind"] == "external" \
            else f"`python rain_lab.py experiment run {eid}`"
        out += ["", f"**Next step:** run it — {where}."]
        if runs:
            out += ["", f"Latest attempt: {runs[-1]['run_id']} — {runs[-1]['interpretation']['deterministic']}"]
        return out

    held = {c["id"]: c["holds"] for g in ("guards", "success", "failure") for c in reference["evaluation"][g]}
    out += [f"Measurements from {reference['run_id']}:", "", "| Metric | Value | Criteria |", "| --- | --- | --- |"]
    for metric in definition["metrics"]:
        name = metric["name"]
        marks = []
        for text in by_metric.get(name, []):
            cid = text.split(":", 1)[0]
            state = {True: "holds", False: "does not hold"}.get(held.get(cid), "n/a")
            marks.append(f"{text} ({state})")
        unit = _unit(metric)
        timing = "" if metric["deterministic"] else " *(timing; varies)*"
        value = fmt(reference["measurements"].get(name))
        out.append(f"| `{name}`{timing} | {value}{unit} | {'; '.join(marks) or '—'} |")
    out += ["", f"**Evaluation:** {outcome_reason(reference)}", "",
            f"**Reproduction:** {summary['reproduction']}.", ""]
    out += ["| Run | Kind | Status | Commit | Seed | Finished |", "| --- | --- | --- | --- | --- | --- |"]
    for run in runs:
        number = run["run_id"].rsplit("-", 1)[1]
        link = f"[{run['run_id']}]({base}/{eid}/runs/RUN-{number}/result.json)"
        out.append(f"| {link} | {run['kind']} | {run['status']} | `{short_commit(run)}` | {fmt(run['seed'])} "
                   f"| {(run['finished_at'] or '—')[:19].replace('T', ' ')} |")
    stored = [a for a in reference["artifacts"] if a["stored"]]
    if reference["artifacts"]:
        out += ["", "**Artifacts:** " + ", ".join(
            f"[{a['name']}]({base}/{eid}/runs/RUN-{reference['run_id'].rsplit('-', 1)[1]}/artifacts/{a['name']})"
            if a in stored else f"{a['name']} (hash only)" for a in reference["artifacts"])]
    out += ["", "**Limitations:**", ""] + [f"- {item}" for item in definition["limitations"]]
    out += ["", f"**Reproduce:** `python rain_lab.py experiment reproduce {eid}`"]
    return out


# ── show ───────────────────────────────────────────────────────────────

def render_show(definition: dict[str, Any], runs: list[dict[str, Any]]) -> str:
    summary = experiment_summary(definition, runs)
    eid = definition["experiment_id"]
    lines = [
        f"{eid} — {definition['title']}  (v{definition['experiment_version']})",
        f"Status: {summary['status'].upper()}   Evidence: {summary['evidence_level']}   "
        f"Runs: {summary['runs']} ({_run_counts(summary)})",
        f"Reproduction: {summary['reproduction']}",
        "",
        f"Question:   {definition['question']}",
        f"Hypothesis: {definition['hypothesis']}",
        f"Rationale:  {definition['rationale']}",
        f"Subsystem:  {definition['subsystem']['repository']} :: {definition['subsystem']['component']}",
        f"Runner:     {definition['runner']['kind']} "
        f"{definition['runner'].get('name') or definition['runner'].get('repository')}"
        f"   evidence class: {definition['evidence_class']}   seed: {fmt(definition['seed'])}",
        "",
        "Pre-registered criteria:",
    ]
    for group in ("guards", "success", "failure"):
        for criterion in definition["criteria"][group]:
            lines.append(f"  [{group}] {criterion_text(criterion)}")
    lines += ["", "Procedure:"] + [f"  {i}. {step}" for i, step in enumerate(definition["procedure"], 1)]
    latest = summary["latest"]
    if latest is None:
        lines += ["", "No runs recorded. Nothing has been measured yet."]
        return "\n".join(lines) + "\n"
    lines += ["", f"Latest run {latest['run_id']} ({latest['kind']}): {latest['status'].upper()} — "
              f"{_VERDICT_TEXT[latest['hypothesis_verdict']]}"]
    if latest["error"]:
        lines.append(f"  error at {latest['error']['stage']}: {latest['error']['type']}: {latest['error']['message']}")
    lines += ["", "  OBSERVED DATA"]
    for name, value in latest["measurements"].items():
        lines.append(f"    {name:<40} {fmt(value)}")
    for name, stats in latest["statistics"].items():
        lines.append(f"    {name:<40} n={stats['n']} mean={fmt(stats['mean'])} median={fmt(stats['median'])} "
                     f"min={fmt(stats['min'])} max={fmt(stats['max'])} stdev={fmt(stats['stdev'])}")
    if latest["evaluation"]:
        lines += ["", "  DETERMINISTIC EVALUATION"]
        for group in ("guards", "success", "failure"):
            for c in latest["evaluation"][group]:
                lines.append(f"    [{group}] {criterion_text(c)}  "
                             f"observed={fmt(c['observed'])}  holds={fmt(c['holds'])}")
        lines.append(f"    {latest['evaluation']['summary']}")
    if latest["reproduction"]:
        rep = latest["reproduction"]
        lines += ["", f"  REPRODUCTION of {rep['source_run']}: outcome matches={fmt(rep['outcome_matches'])}, "
                  f"deterministic metrics match={fmt(rep['deterministic_metrics_match'])}"]
        lines += [f"    mismatch: {m}" for m in rep["mismatches"]]
    prov = latest["provenance"]
    lines += ["", "  PROVENANCE"]
    if prov["source"] == "local_run":
        git, env = prov["git"], prov["environment"]
        lines += [
            f"    commit {git['commit'] or 'unknown'}  branch {git['branch'] or '?'}  dirty={fmt(git['dirty'])}",
            f"    python {env['python']} on {env['os']} {env['os_release']} ({env['machine']})",
            f"    runner {prov['runner']['name']} v{prov['runner']['version']}  "
            f"source sha256 {prov['runner']['source_sha256'][:16]}…",
        ]
        lines += [f"    dependency {k}=={v}" for k, v in prov["dependencies"].items()]
        lines += [f"    subject {f['path']}  sha256 {(f['sha256'] or f['note'])[:16]}" for f in prov["subject_files"]]
    else:
        producer = prov["producer"]
        lines.append(f"    external producer {producer.get('producer')} @ {producer.get('repository')} "
                     f"commit {producer.get('commit')}  submission sha256 {prov['submission_sha256'][:16]}…")
    lines.append(f"    seed {fmt(latest['seed'])}  started {latest['started_at']}  "
                 f"duration {fmt(latest['duration_ms'])} ms")
    for model in latest["models"]:
        lines.append(f"    model {model.get('role')}: {model.get('name')} ({model.get('provider', '?')}) "
                     f"calls={fmt(model.get('calls'))}")
    if latest["artifacts"]:
        lines += ["", "  ARTIFACTS"]
        for a in latest["artifacts"]:
            lines.append(f"    {a['name']:<32} {a['bytes']:>9} B  sha256 {a['sha256'][:16]}…  "
                         f"{'stored' if a['stored'] else 'hash only'}{'  (' + a['note'] + ')' if a['note'] else ''}")
    if latest["observations"]:
        lines += ["", "  OBSERVATIONS"] + [f"    - {o}" for o in latest["observations"]]
    lines += ["", "  LIMITATIONS"] + [f"    - {item}" for item in latest["limitations"]]
    lines += ["", f"Reproduce: python rain_lab.py experiment reproduce {eid}"]
    if prov["source"] == "local_run" and prov["git"]["commit"]:
        lines.append(f"Exact code: git checkout {prov['git']['commit']}  (then run the command above)")
    return "\n".join(lines) + "\n"


# ── compare ────────────────────────────────────────────────────────────

def compare_data(runs: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = sorted({name for run in runs for name in run["measurements"]})
    deterministic, timing = set(), set()
    for run in runs:
        deterministic |= {m["name"] for m in run["definition"]["metrics"] if m["deterministic"]}
        timing |= {m["name"] for m in run["definition"]["metrics"] if not m["deterministic"]}
    across = {}
    for name in metrics:
        values = [run["measurements"].get(name) for run in runs]
        present = [v for v in values if v is not None]
        across[name] = {
            "values": values,
            "summary": summarize(present),
            "percent_change_first_to_last": percent_change(values[0], values[-1]) if len(values) > 1 else None,
            "identical": len(set(present)) <= 1 and len(present) == len(values),
            "deterministic": name in deterministic,
            "timing": name in timing,
        }
    return {
        "runs": [{"run_id": r["run_id"], "status": r["status"], "verdict": r["hypothesis_verdict"],
                  "evidence_class": r["evidence_class"], "commit": short_commit(r), "seed": r["seed"],
                  "experiment_version": r["definition"]["experiment_version"],
                  "evaluation": r["evaluation"]["summary"] if r["evaluation"] else None,
                  "error": r["error"]} for r in runs],
        "metrics": across,
        "model_interpretations": [{"run_id": r["run_id"], **r["interpretation"]["model"]}
                                  for r in runs if r["interpretation"]["model"]],
        "note": "Descriptive comparison only; no significance test is computed.",
    }


def render_compare(runs: list[dict[str, Any]]) -> str:
    data = compare_data(runs)
    single = len({x["experiment_id"] for x in runs}) == 1
    ids = [r["run_id"].split("-RUN-")[1] if single else r["run_id"] for r in runs]
    ids = [f"RUN-{i}" if single else i for i in ids]
    rows = [(label, [fmt(r[key]) for r in data["runs"]]) for label, key in
            (("status", "status"), ("commit", "commit"), ("seed", "seed"), ("version", "experiment_version"))]
    rows += [(name + (" ~" if row["timing"] else ""), [fmt(v) for v in row["values"]])
             for name, row in data["metrics"].items()]
    width = max(len(cell) for cell in ids + [c for _, cells in rows for c in cells]) + 2
    label_width = max(40, *(len(label) + 1 for label, _ in rows))
    lines = ["OBSERVED DATA", ""]
    header = f"  {'metric':<{label_width}}" + "".join(f"{i:>{width}}" for i in ids)
    lines += [header, "  " + "-" * (len(header) - 2)]
    lines += [f"  {label:<{label_width}}" + "".join(f"{c:>{width}}" for c in cells) for label, cells in rows]
    lines += ["", "  (~ = timing metric; expected to vary between runs)", "", "DETERMINISTIC EVALUATION", ""]
    for run in data["runs"]:
        detail = run["evaluation"] or f"execution error: {run['error']['type']}"
        lines.append(f"  {run['run_id']}: {run['status'].upper()} ({_VERDICT_TEXT[run['verdict']]}). {detail}")
    lines += ["", "  Across runs:"]
    for name, row in data["metrics"].items():
        s = row["summary"]
        if row["identical"]:
            lines.append(f"    {name}: identical in all {s['n']} runs ({fmt(s['mean'])})")
            continue
        change = row["percent_change_first_to_last"]
        lines.append(f"    {name}: n={s['n']} mean={fmt(s['mean'])} median={fmt(s['median'])} min={fmt(s['min'])} "
                     f"max={fmt(s['max'])} stdev={fmt(s['stdev'])} variance={fmt(s['variance'])} "
                     f"change first→last={fmt(change)}{'%' if change is not None else ''}"
                     + (f"  [{s['note']}]" if s["note"] else ""))
        if row["deterministic"] and s["n"] > 1:
            lines.append(f"      ! declared deterministic, yet differs: check the commit, version and seed rows")
    lines += ["", f"  {data['note']}", "", "OPTIONAL MODEL INTERPRETATION", ""]
    if not data["model_interpretations"]:
        lines.append("  None recorded. No model was asked to interpret these runs.")
    for item in data["model_interpretations"]:
        lines.append(f"  [{item['origin']}] {item['run_id']} by {item['model']}: {item['text']}")
    return "\n".join(lines) + "\n"
