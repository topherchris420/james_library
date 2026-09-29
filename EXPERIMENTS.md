# R.A.I.N. Experiments

**Claim → Run → Measure → Record → Publish → Repeat.**

An experiment turns a claim into something R.A.I.N. can run. The claim, its metrics, and
the thresholds that count as success *and* failure are registered before anything runs.
Host code measures, applies those criteria, records provenance, and publishes every
outcome to [RESULTS.md](RESULTS.md). That includes failed and inconclusive results.

- Theory may propose experiments. It does not replace them.
- A model can never declare a result. Status is computed from recorded measurements.
- A failed hypothesis is a result. An execution error is a different outcome, recorded separately.

## The whole loop in five commands

```bash
python rain_lab.py experiment list                     # what is registered, and its empirical status
python rain_lab.py experiment run V3D-EXP-0001         # execute, measure, evaluate, record RUN-000N
python rain_lab.py experiment show V3D-EXP-0001        # measurements, evaluation, provenance, artifacts
python rain_lab.py experiment reproduce V3D-EXP-0001   # re-run with the recorded seed and parameters, then compare
python rain_lab.py experiment verify                   # re-derive every stored result from stored data
```

`python -m james_library.experiments <command>` is equivalent. Every command accepts
`--registry PATH` to work on a scratch registry instead of `experiments/`.
Without a command, `python rain_lab.py experiment` still runs the older CIRCLE simulation CLI.

## Vocabulary

| Run status | Meaning |
| --- | --- |
| `planned` | Registered, never run (experiment-level only). |
| `running` | In progress, or interrupted before completion. |
| `passed` | Every success criterion held and no failure criterion held. **Hypothesis supported.** |
| `failed` | A failure criterion held. **Hypothesis not supported.** Failure outranks success. |
| `inconclusive` | An evidence guard was not met, a metric was missing, or neither side was decided. **Insufficient evidence.** |
| `error` | The run did not complete. **Hypothesis not evaluated.** This is not a failed hypothesis. |

| Evidence level | Meaning |
| --- | --- |
| `proposed` | Nothing has been measured yet. |
| `inferred` | Values came from model output (`model_inferred`). This is not empirical evidence. |
| `simulated` | Values came from a simulator. They describe the simulator and pipeline, not the world. |
| `measured` | Measured on real code, data, or instruments. |
| `reproduced` | Measured, and every `reproduce` matched the source run's outcome and deterministic metrics. For external runs: two or more separately reported executions (distinct start times, distinct submissions) agree; their independence is attested by the producer, not verified by the host. |

The evidence class is declared by the experiment and checked against the runner. A simulated
runner can never be relabelled as producing measured evidence.

## Create an experiment

Say what would count as failure before you run. `create` refuses an experiment without at
least one success criterion and one failure criterion.

```bash
python rain_lab.py experiment create \
  --title "Retrieval returns the source paper for its own abstract" \
  --question "Does the corpus retriever rank a paper first when queried with its own abstract?" \
  --hypothesis "Top-1 self-retrieval accuracy is at least 0.9 over at least 15 papers." \
  --runner builtin:self-retrieval \
  --seed 1 \
  --metric top1_accuracy:ratio --metric papers:count --metric query_latency_ms:ms:timing \
  --guard "papers>=15" \
  --success "top1_accuracy>=0.9" \
  --failure "top1_accuracy<0.6" \
  --path james_library/utilities/citation_corpus.py \
  --limitation "Abstract-as-query is an easy case; paraphrased queries are not tested."
```

This allocates the next `V3D-EXP-NNNN` and writes `experiments/V3D-EXP-NNNN/experiment.json`
with status `planned`. IDs are never reused. `experiments/registry.json` remembers every ID
ever issued, even if its directory is deleted.

For full control, write every field in a JSON draft and use `create --from draft.json`.
Copy the structure from [`experiments/V3D-EXP-0001/experiment.json`](experiments/V3D-EXP-0001/experiment.json)
and omit `schema_version`, `experiment_id`, `experiment_version` and `created_at`; the
registry assigns them. The contract is
[`experiment.schema.json`](james_library/contracts/experiments/experiment.schema.json).

### Choosing metrics and criteria

- **Metrics** are named numbers (`snake_case`). Mark a metric as timing (`name:unit:timing`)
  when its value varies between identical runs. Reproduction does not compare timing metrics.
- **Guards** (`G1`, `G2`, ...) are evidence-sufficiency checks, such as a minimum sample size.
  If a guard is not met, the run is `inconclusive`, whatever the other numbers say.
- **Success** (`S…`): all must hold for `passed`.
- **Failure** (`F…`): any one holding means `failed`. Leave a gap between the success and
  failure thresholds; results that land in the gap are honestly `inconclusive`.
- Operators are `>=`, `>`, `<=`, `<`. Thresholds must be finite.

Commit the definition **before** the first run. Then git history shows the criteria were not
tuned to the outcome.

### Changing an experiment

`experiment.json` is write-once through the CLI. To change the method, edit it and increment
`experiment_version`. `verify` fails if a definition changes without a version bump while
runs exist. Each run embeds the exact definition it was evaluated against, so old runs keep
their meaning.

## Make it runnable

A builtin runner is a function that measures and returns numbers. It never returns a status.

```python
# james_library/experiments/runners/self_retrieval.py
from ..runner import RunContext, RunOutput


def run_self_retrieval(ctx: RunContext) -> RunOutput:
    hits, latencies = 0, []
    papers = load_papers()                      # your measurement code
    for name, text in papers.items():
        ranked, ms = timed_search(abstract_of(text))
        hits += ranked[0] == name
        latencies.append(ms)
    ctx.add_artifact("rankings.json", {"hits": hits}, "table")   # optional
    return RunOutput(
        measurements={"top1_accuracy": hits / len(papers), "papers": len(papers),
                      "query_latency_ms": sorted(latencies)[len(latencies) // 2]},
        series={"query_latency_ms": latencies},  # the host computes n/mean/median/min/max/stdev
        inputs={"corpus_files": len(papers)},
    )
```

Register it under a stable lowercase key in
[`runners/__init__.py`](james_library/experiments/runners/__init__.py):

```python
RunnerSpec("self-retrieval", "1", "measured", run_self_retrieval),
```

Registry files name a runner key. They never contain code, commands or import paths.
Use `ctx.seed` for every random choice, so `reproduce` can replay the run.
If the runner raises an exception, the run is recorded as `error`, with a redacted message.

The existing runners are worked examples:
[`citation.py`](james_library/experiments/runners/citation.py) (measured) and
[`circle_controls.py`](james_library/experiments/runners/circle_controls.py) (simulated).

## Run, inspect, reproduce, compare

```bash
python rain_lab.py experiment run V3D-EXP-0005                  # add --seed N to vary the seed (recorded)
python rain_lab.py experiment show V3D-EXP-0005 --json           # full definition, summary and runs
python rain_lab.py experiment reproduce V3D-EXP-0005             # latest completed run
python rain_lab.py experiment reproduce V3D-EXP-0005-RUN-0001    # a specific run
python rain_lab.py experiment compare V3D-EXP-0005               # all runs of one experiment
python rain_lab.py experiment compare V3D-EXP-0005-RUN-0001 V3D-EXP-0005-RUN-0007
```

`compare` prints three separate sections: **OBSERVED DATA**, **DETERMINISTIC EVALUATION**
(with n, mean, median, min, max, stdev, variance and first-to-last percent change for each
metric) and **OPTIONAL MODEL INTERPRETATION**. No significance test is computed. Samples
under 10 are labelled descriptive-only.

Exit codes: `0` for a recorded result, including failed and inconclusive; `1` for
verification problems or a stale RESULTS.md; `2` for a refused request; `3` for a run
recorded with status `error`.

Each run is preserved in `experiments/V3D-EXP-NNNN/runs/RUN-NNNN/result.json`
(schema [`run.schema.json`](james_library/contracts/experiments/run.schema.json)). A run
record contains:

- the definition snapshot and its SHA-256, with the seed and parameters
- inputs, measurements, series and host-computed statistics
- the criterion-by-criterion evaluation, the deterministic interpretation, limitations and artifacts
- provenance: git commit, branch and dirty state (registry files excluded); Python, OS and
  machine; declared dependency versions; SHA-256 of the files under test and of the runner's
  source; timestamps
- the reproduction comparison, if the run is a reproduction, and the error, if the run failed to execute

Final records are never overwritten.

## Artifacts, privacy and secrets

- `ctx.add_artifact(name, content, kind)` hashes every artifact. Its content is stored under
  `runs/RUN-NNNN/artifacts/` only when the data policy allows storage and the content is
  under 5 MB.
- Set `"data_policy": {"classification": "sensitive", ...}` or `--hash-only` for raw data
  that must not enter git, such as biosignals, human-participant data or private text.
  Only the SHA-256 and size are recorded.
- Artifact content that matches a credential pattern is withheld automatically.
- Parameters, inputs, model configuration and error messages are redacted: strings under
  secret-like keys, and values that look like API keys, tokens or private keys.
- A definition that contains a credential is refused outright. Pass credentials through
  the environment at run time.
- Provenance never records environment variables, hostnames, user names or absolute home paths.
- Use a role label such as `R.A.I.N.Operator` for `created_by`. Values with spaces or `@` are rejected,
  which blocks full names and email addresses.

## Connect another repository

An external experiment runs elsewhere and reports its measurements here. The producer
needs no R.A.I.N. code. It writes one JSON document that follows
[`submission.schema.json`](james_library/contracts/experiments/submission.schema.json).

1. Register the experiment with `"runner": {"kind": "external", "repository": "owner/repo"}`.
   See [V3D-EXP-0004](experiments/V3D-EXP-0004/experiment.json).
2. The other repository runs the experiment and emits a submission per run.
3. Admit it with `python rain_lab.py experiment record V3D-EXP-0004 submission.json`.

The submission deliberately has **no status or verdict field**. Adding one is rejected, and
the host evaluates the pre-registered criteria itself. Artifacts are referenced only by
SHA-256; any `uri` is kept for people to follow and is never opened. A submission against
an outdated `experiment_version` is refused. A submission with an `error` object is
recorded as `error`, not `failed`. `model_interpretation` is stored in its own labelled
field and never affects evaluation. Admission checks internal consistency; it does not
authenticate the producer.

### First flagship: Satellite Vision Scape + Jev (V3D-EXP-0004, planned)

The question: under the same controls, physics, perception limits and weapon mechanics
as a human, does repeated calibration measurably improve Jev? The draft pre-registration
compares four groups: human baseline, Jev baseline, calibrated Jev and human-assisted Jev.
Review its thresholds before the first run. After runs exist, a change requires a version bump.

On the `topherchris420/satellite-vision-scape` side, the adapter should:

1. Run each group on the same build, map seed and input-rate limits. Keep per-shot and
   per-decision logs, replays and Jev decision traces **locally**.
2. Aggregate per group: shot accuracy, shots fired, hits, misses, reaction latency, target
   acquisition time, mission completion time, deaths, damage taken, path efficiency, control
   corrections, decision latency and run-to-run variance. Report the metrics that
   V3D-EXP-0004 declares. Send extra metrics too; they are recorded and shown, and do not
   affect evaluation.
3. Emit the submission. The values below are placeholders. They are strings on purpose,
   so this example fails validation if someone submits it unchanged.

```json
{
  "schema_version": "rain-experiment-submission/v1",
  "experiment_id": "V3D-EXP-0004",
  "experiment_version": 1,
  "evidence_class": "measured",
  "started_at": "<ISO-8601 with timezone>",
  "finished_at": "<ISO-8601 with timezone>",
  "seed": "<map/episode seed or null>",
  "parameters": {"calibration_cycle": "<n>", "build": "<game build id>"},
  "inputs": {"map": "<map id>", "groups": ["human_baseline", "jev_baseline", "jev_calibrated", "jev_human_assisted"]},
  "measurements": {
    "runs_per_group_min": "<int>",
    "human_baseline_accuracy": "<0..1>", "jev_baseline_accuracy": "<0..1>",
    "jev_calibrated_accuracy": "<0..1>", "jev_assisted_accuracy": "<0..1>",
    "calibration_accuracy_gain_pp": "<percentage points>",
    "jev_baseline_deaths_per_run": "<mean>", "jev_calibrated_deaths_per_run": "<mean>",
    "deaths_per_run_change": "<calibrated minus baseline>",
    "jev_calibrated_median_decision_latency_ms": "<ms>", "human_median_reaction_latency_ms": "<ms>"
  },
  "series": {"jev_calibrated_decision_latency_ms": ["<ms per decision>"]},
  "observations": ["<free text, no personal data>"],
  "limitations": ["<what this run cannot show>"],
  "artifacts": [{"name": "jev_calibrated_replays.tar", "sha256": "<64 hex>", "bytes": "<int>", "kind": "replay"}],
  "models": [{
    "role": "agent", "name": "jev", "provider": "<provider>", "version": "<model version>",
    "request_config": {"temperature": "<float>", "max_tokens": "<int>"},
    "calls": "<int>", "latency_ms": ["<ms per call>"],
    "validation": {"passed": "<int>", "failed": "<int>"},
    "decision_trace_sha256": "<64 hex>"
  }],
  "provenance": {"producer": "R.A.I.N._service", "repository": "topherchris420/satellite-vision-scape",
                 "commit": "<git sha>", "dirty": "<bool>", "environment": {"engine": "<version>", "gpu": "<model>"}}
}
```

Producer-side sketch, with no R.A.I.N. import:

```python
import hashlib, json, pathlib
def sha256(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
submission["artifacts"] = [{"name": p.name, "sha256": sha256(p), "bytes": p.stat().st_size, "kind": "replay"}
                           for p in replay_files]
pathlib.Path("submission.json").write_text(json.dumps(submission, indent=2))
```

Human-baseline behaviour is personal data. Submit only aggregates and hashes. Keep
V3D-EXP-0004's `store_artifacts: false`.

Other projects follow the same pattern. Examples include dynamic-resonance-rooting,
lop-nur-twin, biosignal and resonant-feedback systems, simulators and agent benchmarks.
Register the experiment as external and emit submissions. For simulators, use
`evidence_class: simulated`. For raw biosignals, use `classification: sensitive`.

## Publish

Every `create`, `run`, `reproduce` and `record` regenerates [RESULTS.md](RESULTS.md) (pass `--no-results` to skip).
It is a pure function of the registry. `experiment results` rewrites it, and
`experiment results --check` or `experiment verify` fails if it is stale or edited by hand.
The Python test suite runs `verify` over the committed registry, so CI rejects tampered
records or a stale RESULTS.md.

Suggested practice:

1. Commit the pre-registration.
2. Run from a clean checkout of committed code.
3. Commit the run records and RESULTS.md.

Parallel branches:

- **`RESULTS.md` conflicts.** It is generated, so resolve a conflict by running
  `python rain_lab.py experiment results`.
- **Run collisions.** Two branches that add runs to the same experiment can both create
  `RUN-000N`. Git reports an add/add conflict, and nothing is silently merged. Keep one side,
  then re-run the other side's experiment after merging so it gets the next number.
- **Experiment ID collisions.** Two branches can also pre-register the same next ID. Git
  surfaces this too. The branch that merges second re-creates its experiment under a new ID
  with `create --from`, then runs it again, because run records embed their IDs.
- **Prevention.** Pre-register on the main line first, or in a small dedicated PR, and run
  experiments afterwards.

Registry files are excluded from the dirty check, so recording one run does not make the
next one look dirty. A squash merge can drop the recorded commit SHA from `main`. The per-run
SHA-256 of the files under test and of the runner source still identifies the exact code.

## What this does not establish

- `passed` means the pre-registered criteria held for this code, data and environment. It
  does not mean a theory is true. Read each experiment's limitations.
- SHA-256 detects inconsistent edits. It is not a signature. Someone who can rewrite both
  records and hashes can forge them; git history is the tamper-evidence layer.
- External admission checks structure and consistency. It does not authenticate the producer
  or prove that its runs happened as reported.
- Seeded replay reproduces deterministic metrics within a compatible Python runtime. The
  registry does not reinstall old environments or check out old commits for you.
- This registry is separate from the [reviewed CIRCLE simulation workflow](docs/research-workflow.md),
  which adds explicit human authorization of an exact plan. It is also separate from chat
  session artifacts.
