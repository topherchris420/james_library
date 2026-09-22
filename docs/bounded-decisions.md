# Calibrated bounded decisions

The optional Python routing layer uses **Laya for local proposals, Jev for bounded
judgment, and R.A.I.N. for unresolved research work**. Deterministic host code
retains authority. Confidence is neither permission nor scientific proof.

This extends the existing `JudgmentProvider.evaluate(state, questions)` contract;
it does not introduce a competing provider interface. `DecisionRequest` defines
one Choice question over explicit candidates; `DecisionEnvelope` records the
proposal, attempts, policy, calibration, and validator outcome.

## Boundaries and compatibility

- Default `RAIN_DECISION_MODE=off` and `RAIN_METACOGNITIVE_CONTROL=false` preserve
  the existing meeting loop. Optional providers are not constructed when off.
- The independent `judge --evidence` promotion command and its `JudgmentGate`
  remain unchanged. Existing Jev-only promotion policy is not retroactively
  described as empirically calibrated by this feature.
- `decide --request` produces a proposal or a handoff, never an executed action.
- The chat integration is separately opt-in. It uses only completed-turn counts,
  the existing turn budget, and the latest verified-citation count. It records
  the decision before translating a proposal to one of four fixed host-authored
  hints: continue, verify, challenge an assumption, or synthesize. It does not
  send transcripts, papers, private memory, or topics to the decision provider.
- James, Jasmine, Luca, and Elena still investigate, interpret evidence, and
  generate scientific substance. Existing recovery rules precede these hints;
  model proposals cannot alter turn budgets, tools, permissions, or promotion.
- `propose_next_step` also supports explicit host-supplied subsets of CONTINUE,
  VERIFY, SWITCH_EXPERT, SEARCH_EVIDENCE, CHALLENGE_ASSUMPTION, SYNTHESIZE,
  ESCALATE_TO_HUMAN, and STOP. A missing/uncertain engine returns `None`, allowing
  the host to continue normal research. STOP never means accepting a claim.
- This is a trusted host policy boundary, not a sandbox for malicious Python
  providers. Hosts must classify consequence and supply actual authorization
  checks; a model must never supply its own policy flags or validator.

## Selective escalation

1. Validate request schema, secret boundaries, and the host's deterministic
   precheck before invoking any provider.
2. High consequence, required evidence, explicit review, and host-identified
   out-of-distribution cases go directly to R.A.I.N. No confidence can waive them.
3. A trusted deterministic choice avoids inference but still receives final
   validation. The JSON CLI cannot submit such a choice.
4. In cascade mode, try Laya first. A valid, sufficiently calibrated local
   proposal avoids a Jev call. An unavailable engine, invalid output, timeout,
   insufficient/expired calibration, low top probability, or inadequate margin
   escalates to Jev **only if the request explicitly permits remote processing**.
5. If Jev cannot resolve the decision, return a structured R.A.I.N. handoff. The
   chat integration simply retains the normal research loop. The standalone CLI
   prints the handoff; it does not silently launch another generative service.
6. Run the host validator again after any learned proposal. A refusal returns
   `rejected` with no selected action, regardless of model confidence.

`RAIN_DECISION_COMPARE=true` in cascade mode requests both engines, even if Laya
could resolve the case. Different valid selected choices cause
`ENGINE_DISAGREEMENT`; larger confidence does not win. Comparison requires both
results to meet calibration policy. If either is unavailable or uncalibrated,
return to R.A.I.N. rather than treating lack of a comparison as agreement.

Reasons include `LOW_CONFIDENCE`, `MARGIN_TOO_SMALL`, `MODEL_UNAVAILABLE`,
`INVALID_OUTPUT`, `OUT_OF_DISTRIBUTION`, `POLICY_REQUIRES_REVIEW`,
`EVIDENCE_REQUIRED`, `HIGH_CONSEQUENCE`, `ENGINE_DISAGREEMENT`, `TIMEOUT`,
`INSUFFICIENT_CALIBRATION`, `VALIDATION_FAILED`, `SENSITIVE_INPUT`, and `DISABLED`.

The deadline is **per engine**, so a cascade may consume two deadlines. The local
worker is terminated on subprocess timeout. The router bounds third-party calls
with one in-flight daemon thread per engine/router; a timed-out transport may
finish in the background but its late result is discarded. No executor or
workflow state is passed to providers. The existing TypeSafe HTTP transport also
retains its connection/read limits. Reuse the router across a session.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `RAIN_DECISION_MODE` | `off` | `off`, `laya`, `jev`, `cascade` |
| `RAIN_LAYA_CHECKPOINT` | unset | Complete, explicitly provisioned local checkpoint directory |
| `RAIN_LAYA_DEVICE` | `cpu` | `cpu`, `cuda`, or `mps` |
| `RAIN_LAYA_PYTHON` | host Python | Optional separate inference environment's interpreter |
| `RAIN_DECISION_CALIBRATION` | unset | JSON array of validated calibration profiles |
| `RAIN_DECISION_MINIMUM_SAMPLES` | `100` | Minimum accepted examples **in each** fit and held-out split |
| `RAIN_DECISION_TIMEOUT` | `30` | Per-engine seconds, 0.01–300 |
| `RAIN_DECISION_COMPARE` | `false` | Require comparison in cascade mode |
| `RAIN_METACOGNITIVE_CONTROL` | `false` | Enable experimental research-process hints |
| `RAIN_DECISION_REMOTE_ALLOWED` | `false` | Permit remote processing of chat controller counters |
| `TYPESAFE_API_KEY` | unset | Existing explicit Jev credential |
| `TYPESAFE_MODEL` | `jev-latest` | Returned concrete model, not alias, binds calibration |

Boolean flags accept only `true` or `false`. Invalid configuration is surfaced;
chat reports a categorical diagnostic and continues its existing workflow.
Neither missing inference dependencies nor a missing checkpoint prevents startup.
A CLI packet separately declares `remote_allowed`; using `laya` mode never calls
Jev, regardless of that packet flag. No new telemetry is added.

Example (POSIX shell; use `set NAME=value` on Windows):

```bash
export RAIN_DECISION_MODE=cascade
export RAIN_LAYA_CHECKPOINT=/absolute/path/to/local/laya-checkpoint
export RAIN_DECISION_CALIBRATION=/absolute/path/to/profiles.json
# Configure TYPESAFE_API_KEY separately if remote evaluation is intended.
python rain_lab.py decide --request examples/bounded-decision.json
```

Jev-only workflow proposals: `RAIN_DECISION_MODE=jev`. Local-only proposals:
`RAIN_DECISION_MODE=laya`. These differ from existing discovery promotion's
`RAIN_JUDGMENT_PROVIDER=typesafe`; neither setting implicitly enables the other.

## Local Laya runtime

Install the optional adapter dependency into a dedicated environment if desired:

```bash
python -m venv .venv-laya
.venv-laya/bin/python -m pip install -r requirements-laya.txt
export RAIN_LAYA_PYTHON="$PWD/.venv-laya/bin/python"
```

Provision and review checkpoint weights **explicitly, outside this runtime**.
A directory must contain `rl_agent_config.json`, `model.safetensors`,
`tokenizer/tokenizer_config.json`, `tokenizer/tokenizer.json`, and
`encoder/config.json`. Missing components return `MODEL_UNAVAILABLE`.
A Hugging Face repository identifier is not a checkpoint path.

The worker uses Laya 0.3.5's actual `load(local_path, device=...)` / `predict`
contract. It strips inherited credentials, disables Hugging Face network and
telemetry, and blocks Python socket connections before importing Laya. It does
not use Laya's automatic multilingual/model-download router. This is offline
control for the inspected SDK, not OS sandboxing of arbitrary native code.

The checkpoint's weights, configuration, tokenizer, encoder files, installed
Laya/torch/transformers versions, and actual device contribute to its SHA-256
model identity. Calibration must match that identity. Laya may repair tokenizer
metadata during loading; the fingerprint uses the files after loading.
Its Noul confidence and action hints are discarded: the common Noul contract is
only a yes-probability. Choice/Score distributions receive strict validation.

The adapter rejects inputs if the inspected tokenizer would truncate the state,
question, or candidate descriptions. Such inputs escalate as
`OUT_OF_DISTRIBUTION`, rather than gaining confidence from incomplete evidence.
Other distribution shifts must be identified by host policy and evaluation;
this is not a semantic OOD detector.

**Current tradeoff:** each evaluation loads a cold model in a killable process
and hashes its files. It is not a persistent sub-40 ms inference service. Cold
start may exceed the default timeout on CPU. Benchmark on the actual hardware;
there is no demonstrated speed improvement yet. No weights are shipped.

## Calibration and drift

No production profile is bundled. Missing calibration means escalation.
Thresholds use the selected option's **top probability** and top-two margin,
not the provider's differently defined confidence field.

Collect labeled measurements for each decision class, question definition, and
concrete model. Keep fit and held-out sets disjoint, with unique sample IDs.
Labels should be independently reviewed; teacher labels are not ground truth.
Use representative languages and task distributions. Repeated copies of one
example do not establish real calibration even if they have different IDs.

Measurements have this shape (one JSON array per split):

```json
[{
  "engine": "typesafe",
  "model": "jev-concrete-version",
  "decision_class": "continue_stop",
  "question_hash": "<exact 64-character SHA-256 from decision records>",
  "sample_id": "heldout-case-001",
  "expected": "VERIFY",
  "selected": "VERIFY",
  "probability": 0.94,
  "margin": 0.88
}]
```

The example is a schema illustration, not sufficient calibration evidence.
The benchmark report's `samples` entries have this format; filter to one
engine/model/class/question before creating splits.

```bash
python -m james_library.judgment.calibrate \
  --fit fit.json --heldout heldout.json --output profiles.json
python -m james_library.judgment.calibrate \
  --fit fresh-fit.json --heldout fresh-heldout.json --check profiles.json \
  --output drift-report.json
```

Fit chooses thresholds on the fit set alone, maximizing retained coverage subject
to a 95% Wilson lower accuracy bound meeting the configured target (default .95).
The independently held-out split must meet the same bound and sample floor;
failure never triggers threshold tuning against that split. Profiles expire
(default 30 days). Runtime rechecks evidence counts, bounds, expiry, question
identity, and concrete model identity. Drift checks additionally fail on a
coverage drop greater than five percentage points against the locked profile.
Threshold search is offline; fit bounded datasets before deployment.

Reports include sample counts, accepted accuracy, calibration error (10-bin ECE),
abstention/escalation rates, and one-versus-rest false-positive/false-negative
rates among accepted samples. Undefined denominators are `null`, never zero.
Profiles are trusted host configuration, not signed certificates or proof of
future correctness. Expiry and drift checks do not replace ongoing monitoring.

## Provenance and replay

`SessionArtifactWriter.record_decision` atomically checkpoints a `decisions`
array alongside existing `judgments` and `turns`. Each decision records its ID,
timestamp, request/schema hashes, candidates, selected choice, attempts,
provider/model, distributions/confidence, calibration profile/threshold/margin,
latency, reason, destination, and validator result. Raw state is not retained.
`final_action=null` explicitly means this is a proposal record, not evidence of
execution. Chat records its accepted fixed hint as a SYSTEM turn linked to the decision ID
and then adds that hint to the meeting context.

```bash
python rain_lab.py decide --replay meeting_archives/session_artifacts/session_decision-ID.json
```

Replay verifies envelope digests without loading an engine. Existing artifacts
without decisions remain readable. Gold replay explicitly disables both routing
and metacognitive control. Digests detect modifications but are not signatures.
For independently reproducing inference, retain the curated inputs separately
under the host's privacy policy; hashes alone cannot reconstruct private inputs.

## Benchmark harness

```bash
python -m james_library.judgment.benchmark --fixture --output /tmp/routing-fixture.json
python -m james_library.judgment.benchmark --fixture --compare --output /tmp/comparison-fixture.json
```

These runs use explicitly synthetic providers, labels, and calibration for 16
routing/failure cases. Their accuracy and latency describe fixture behavior,
**not Laya/Jev quality**. Ordinary runtime factories never load fixture providers.
Focused tests additionally cover actual watchdog timeouts, malformed input,
post-inference refusal, disabled modes, calibration failure, and secret handling.

For measured model behavior, omit `--fixture`, explicitly configure the engines,
and supply an independently labeled `--cases` dataset. Requests without remote
consent never reach Jev. The harness compares local-only, Jev-only, cascade, and
R.A.I.N. handoff; it reports latency, selective accuracy, invalid outputs,
calibration, disagreement, and routing fractions. It does **not** generate or
score R.A.I.N. scientific answers; `rain_deliberation_accuracy` is `null`.

## Reference inspection and licensing

Inspected 2026-09-22. These informed boundary design; none were vendored wholesale.

| Reference | Inspected commit | Adopted idea / deliberately excluded |
| --- | --- | --- |
| [Laya](https://github.com/NandhaKishorM/laya) | `573e5b6` | Typed local API; exclude automatic downloads, silent truncation and direct confidence-to-action examples |
| [awesome-jev](https://github.com/yibie/awesome-jev) | `7f69478` | Ecosystem discovery; not an API specification |
| [JevLoop](https://github.com/zjunlp/JevLoop) | `c16b624` | Separate decisions from generation; do not import its agent loop or automatic rule-judge fallback |
| [jevcal](https://github.com/abhixhek/jevcal) | `ae8f314` | Independent held-out thresholds and drift checks; do not import teacher dependencies or auto-labeling |
| [r2r-jev](https://github.com/Thneoly/r2r-jev) | `3c04a05` | Judgment is evidence, not authorization; do not introduce another persistent governance kernel |
| [DataJev](https://github.com/zzz1YAO/DataJev) | `b42d67c` | Bounded process actions; do not replace R.A.I.N.'s scientific agents or import a code executor |
| [jev-engineering](https://github.com/eugeniughelbur/jev-engineering) | `3161dbf` | Deterministic-first checks and adversarial failures; do not import permissive error handling or permission hooks |

Laya, JevLoop, and r2r-jev use Apache-2.0; jevcal, DataJev, and jev-engineering
use MIT. Laya's repository advertises Apache-2.0 weights, but operators must
verify the selected checkpoint and encoder licenses before redistribution.
Jev remains an optional external TypeSafe service subject to its service terms.
Existing `requests` handles Jev; no additional base dependency is introduced.
Optional Laya brings torch, transformers, safetensors, huggingface_hub, and numpy.

The TypeSafe skill and live API/Choice/confidence docs were also inspected.
Provider-specific wire formats stay in adapters; router logic uses common typed
answers. Executable papers and MCP infrastructure remain separate: callers can
later supply bounded registry-search choices without changing either provider.

## Rollback

Set `RAIN_METACOGNITIVE_CONTROL=false` and `RAIN_DECISION_MODE=off`.
Existing chat and Jev discovery-promotion behavior remain available. This feature
makes no AGI, consciousness, truth, certification, or guaranteed-correctness claim.

## Implementation verification (2026-09-22)

- Full Python suite: 637 passed, including 67 added tests covering routing,
  calibration, adapter boundaries, replay, and the real offline meeting loop.
- Repository-wide Ruff and the configured mypy allowlist passed.
- Documentation locale-parity checks and all 16 added local links passed.
- The 16-case synthetic cascade run produced 8 proposals, 7 R.A.I.N. handoffs,
  and 1 deterministic rejection. Comparison mode explicitly escalated the
  disagreement fixture. These counts verify control flow, not model quality.
- No actual Laya weights or live Jev credentials were used. Real model accuracy,
  cold-start latency, language coverage, and substantive R.A.I.N. fallback
  quality remain unmeasured.
- Rust checks were unavailable because this environment has no Cargo. No Rust
  files or dependencies changed. The standard lychee link tool was unavailable;
  added relative links were checked directly against the checkout.
