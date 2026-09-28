# From inference to an inspectable research record

R.A.I.N. is developing a research and decision layer for moving from AI-generated
inference to human-authorized experimentation and provenance-preserving evidence.
The Research Panel is its deliberation interface. The reviewed simulation below
is a separate, working evidence workflow. Chat does not automatically enter it.

**Inference is not evidence. Evidence is not permission. Confidence is not authority.**

## One offline example

Install the repository's pinned Python dependencies first. No model, account,
network request, hardware, or Rust runtime is used during this example.
`jsonschema`, already part of the MCP dependency stack, is explicitly declared
for validation against the existing repository contracts.

```bash
python -m james_library.services.experiment_protocol.research plan research-plan.json
```

Read the generated JSON before proceeding. It contains the existing experiment
manifest, the seed, all simulator parameters and a **scripted model stand-in**
that predicts an active-minus-control difference of **-20 ohms**. No model ran.
The actual generator uses a -16-ohm effect plus noise; the prediction is
intentionally inaccurate to demonstrate the distinction from observation.

The command prints the plan's SHA-256. Record the code revision with
`git rev-parse HEAD`. Run from a clean checkout if you want that revision to
identify the executed code. Replace the placeholders below with those values:

```bash
python -m james_library.services.experiment_protocol.research run research-plan.json --approve REVIEWED_PLAN_SHA256 --code-revision FULL_COMMIT_SHA --operator R.A.I.N.Operator --out-dir research-output
```

The host revalidates the entire plan, compares the approval to its digest,
validates the operator attestation and code-revision format, and only then
calls the existing simulator. Changing the manifest, seed, scenario or
prediction invalidates the approval. Setting `authorized: true` in model
output is rejected as an unknown plan field. A matching digest never overrides
a failed deterministic check.

The bundle path is printed after completion. Inspect it with:

```bash
python -m james_library.services.experiment_protocol.research inspect research-output/experiments/EXP-XXXXXXXX
```

Use the actual printed experiment ID. Inspection verifies the complete checksum
inventory, reloads the existing manifest/result contracts, recomputes the
statistics, checks the research record's bindings and reproduces the measurement
arrays using the recorded seed and scenario. It uses only the built-in simulator;
no command, URL, import path or code stored in a record is executed.

The reported observation is approximately **-16 ohms**, distinct from the -20-ohm
prediction. The exact observed value comes from the saved arrays. The result is
synthetic, even if the statistical label is `SUPPORTS`. It establishes neither a
physical resonance effect nor a biological effect.

## What each stage means

| Stage | Implemented representation | Boundary |
| --- | --- | --- |
| Question | `manifest.research_question` | Defines the investigation. |
| Claim / hypothesis | `manifest.hypothesis`, preregistered thresholds and falsification criteria | Text does not establish truth. The claim ID references this hypothesis. |
| Proposal | `research.json → plan.proposal` | A scripted stand-in in this example; never used as a measurement. |
| Deterministic checks | Repository manifest/result schemas, parameter bounds, identity/hash links, finite observations | Failure raises an error before admission or execution. |
| Authorization | Exact-plan digest, operator role, timestamp and local simulation scope | A caller-attested human decision, not model confidence. |
| Experiment | Existing `SimulatedCircleExecutor` | Synthetic data only; physical executor remains disabled. |
| Observation | `data/measurements.json`; derived difference in `research.json` | Observed simulator output is authoritative for this local record. |
| Evidence | Existing `result.json`, artifact digest and provenance | `SIMULATED` cannot become `RAW_MEASURED`. |
| Interpretation | Existing `analysis.json`, deterministic critique templates, limitations | Conclusion is bounded by the registered statistical criteria. |

The sequence is a host-controlled workflow, not a universal policy applied to
all R.A.I.N. modes. The older `experiment` CLI and fixtures remain available as
simulation tools without this approval flow. `decide` still returns proposals;
`judge` still evaluates supplied evidence. Neither grants this workflow approval.
The optional `rlm` runtime has separate execution policies.

## Files and reproducibility

A research bundle extends the existing experiment bundle with **one** companion
`research.json`. There is no second experiment/result schema or new database.

| File | Purpose |
| --- | --- |
| `manifest.json` | Existing preregistered hypothesis, assumptions, controls and method. |
| `manifest.sha256` | Hash of the saved manifest file bytes. |
| `result.json` | Existing v1 result, with identity and evidence references. |
| `data/measurements.json` | Saved simulated observations. |
| `analysis.json` | Deterministic statistics, template interpretation and critique. |
| `provenance.json` | Existing evidence trace. New template interpretations are tagged `DERIVED`. |
| `research.json` | Exact reviewed plan, approval, prediction, observation, claim link, limitations, Python version and caller-attested code commit. |
| `checksums.json` | Complete file inventory and SHA-256 digests. |

`result.manifest_sha256` hashes the canonical manifest object; `manifest.sha256`
hashes the formatted file. These are distinct encodings. The existing
`analysis.result_sha256` includes the transient `_embedded_data`; inspection
rehydrates it from the saved measurement file before recomputing analysis.
`memory://simulated_measurements.json` remains the original artifact reference;
its saved bytes are in `data/measurements.json` and ingress verifies their hash.

Seed replay reproduces measurement arrays within a compatible Python runtime.
Generated IDs, timestamps, and entire bundle bytes are not deterministic. The
record does not install old environments, check out a commit, or establish that
a caller-supplied commit matches a dirty working tree. An existing experiment
folder is never overwritten; generate a new plan for a new trial.

## External experiment interface

External producers can emit the existing
[manifest](../james_library/contracts/rain-circle/experiment-manifest.schema.json)
and [result](../james_library/contracts/rain-circle/experiment-result.schema.json)
JSON contracts without importing R.A.I.N. A host can admit them using:

```python
from james_library.services.experiment_protocol.ingestion import ingest_result
from james_library.services.experiment_protocol.analysis import run_deterministic_analysis
from james_library.services.experiment_protocol.manifest import calculate_sha256

# manifest, result and measurements are decoded, untrusted JSON objects.
validated = ingest_result(manifest, result, measurements)
stats = run_deterministic_analysis(manifest, validated, calculate_sha256(manifest))
```

This is deliberately narrow: protocol 1.0.0, `SIMULATED` executor/provenance,
one hashed time-series artifact, finite control/active/phantom arrays, matching
experiment/trial/execution IDs and ordered timezone-aware timestamps. Unsupported
versions, incomplete inputs, nonfinite values, unknown result fields and invalid
hashes fail closed. The caller supplies data bytes; referenced paths and URLs are
never fetched. The return value is an isolated copy for deterministic analysis.

Acceptance means internal consistency. It does **not** authenticate the producer,
prove its reported history, authorize an action, or establish that an external
execution was approved. External authorization cannot be manufactured by adding
fields to a result. Transport authentication, payload byte limits and human
approval for publishing/importing authoritative records belong to the host.
No HTTP endpoint or arbitrary experiment adapter is added here.

## Use it during development

Before changing an experimental method, write the observation, problem and
hypothesis in the reviewed plan's manifest. Define the falsification criterion
before running. Record the clean code commit and compare the resulting evidence
with the proposal using `inspect`. Decide **keep / revise / revert** in the code
review, referencing the experiment and claim IDs. Run a new plan after a revision
so the previous evidence remains intact.

This is a usable dogfooding path for the simulator and analysis pipeline; it does
not execute arbitrary development commands or automatically ingest test logs.
A passed unit test is software evidence, not a physical measurement. The tests in
`tests/test_research_workflow.py` exercise this same plan-to-evidence path.

## Trust, privacy and limitations

- Approval is an explicit local operator attestation. The process does not
  authenticate a human, enforce global single-use approval, or prevent a caller
  with Python access from calling the simulator directly. Keep the host UI and
  approval channel separate from model-generated data.
- SHA-256 detects inconsistent edits. A writer can replace both data and hashes;
  checksums are not signatures or access control. Treat externally supplied
  authorizations and metadata as assertions, not authenticated facts.
- Bundles reject missing inventories, unsafe checksum paths, symlinks and
  untracked files. They are write-once through the save API, not immutable storage.
- Ingress checks structure and consistency. It does not prove that every
  free-text quality assertion is true or that a source supports a conclusion.
- Store only necessary context. Plan text, evidence and operator attestations
  remain local but may contain private material. Review them before sharing.
- Laya and Jev are optional proposal/judgment components; this example calls
  neither. The interpretation and adversarial critique are deterministic templates.

## Implemented, partial, planned

| Capability | Status |
| --- | --- |
| Research Panel, grounded chat and session artifacts | Implemented as a separate workflow. |
| Bounded Laya/Jev routing and typed claim judgment | Implemented, optional, with their own validation/consent boundaries. |
| Reviewed simulated experiment, evidence bundle and observation replay | Implemented in this workflow. |
| External v1 simulated result admission | Implemented as a non-executing Python API. |
| Research Registry | Partial: linked file bundles and session artifacts; no unified cross-session index. |
| Claim support / contradiction queries | Partial: `inspect` exposes one bundle's deterministic critique and falsification criteria. |
| General external environments and authenticated authorization | Planned; current contracts still describe CIRCLE-style simulated experiments. |
| Executable papers, unified registry search and automatic environment recreation | Planned. No public research-query MCP is claimed. |

Rollback is a normal revert of this feature. Existing bundles remain data files;
older bundles have no `research.json` and use the legacy checksum verifier.
New inspection intentionally refuses to invent historical approvals for them.
