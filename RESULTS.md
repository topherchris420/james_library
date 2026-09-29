# Experimental Results

<!-- Generated from experiments/ by `python rain_lab.py experiment results`. Do not edit by hand. -->

What R.A.I.N. actually ran, and what happened. Each status is computed by host code
from recorded measurements against criteria registered *before* the run; no model
decides it. Failed and inconclusive results stay on the record.
How to add one: [EXPERIMENTS.md](EXPERIMENTS.md). Raw records: [`experiments/`](experiments/).

**4 experiments · 6 runs** — 2 passed · 1 failed · 1 planned

Evidence: 2 reproduced · 1 simulated · 1 proposed

| ID | Experiment | Result | Key measurement | Evidence | Runs |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0001](#v3d-exp-0001) | Citation gate rejects fabricated quotes and accepts verbatim ones | **PASSED** | verbatim_acceptance_rate = 1 (needs ≥ 0.99) | reproduced | 2 |
| [V3D-EXP-0002](#v3d-exp-0002) | Citation gate tolerates typographic normalization of genuine quotes | **FAILED** | typographic_variant_acceptance_rate = 0 (needs ≥ 0.95) | reproduced | 2 |
| [V3D-EXP-0003](#v3d-exp-0003) | CIRCLE analysis error rates on seeded simulated controls | **PASSED** | detection_rate = 0.99 (needs ≥ 0.8) | simulated | 2 |
| [V3D-EXP-0004](#v3d-exp-0004) | Satellite Vision Scape: does calibration improve Jev under human-equivalent constraints? | **PLANNED** | calibration_accuracy_gain_pp: — (needs ≥ 10) | proposed | 0 |

## Negative and inconclusive results

- **V3D-EXP-0002 — FAILED**: Citation gate tolerates typographic normalization of genuine quotes. Failure criterion met: F1: typographic_variant_acceptance_rate < 0.5 (observed 0).

## V3D-EXP-0001

### Citation gate rejects fabricated quotes and accepts verbatim ones

**Result: PASSED** — hypothesis supported · evidence: reproduced · runs: 2 (2 passed)

**Question:** Does verify_quote, the quote-grounding gate used by chat, the offline demo and the MCP server, accept verbatim corpus quotes and reject minimally corrupted ones?

**Hypothesis:** On seeded 8-20 word windows from papers/, verify_quote accepts at least 99% of verbatim and case/whitespace-reformatted quotes and at most 1% of fabricated variants (one word substituted, two adjacent words swapped, or halves spliced from two papers); fragments shorter than three words are never accepted.

Measurements from V3D-EXP-0001-RUN-0002:

| Metric | Value | Criteria |
| --- | --- | --- |
| `verbatim_cases` | 60 | G1: verbatim_cases ≥ 50 (holds) |
| `verbatim_acceptance_rate` | 1 | S1: verbatim_acceptance_rate ≥ 0.99 (holds); F2: verbatim_acceptance_rate < 0.95 (does not hold) |
| `reformatted_acceptance_rate` | 1 | S2: reformatted_acceptance_rate ≥ 0.99 (holds) |
| `fabricated_cases` | 180 | G2: fabricated_cases ≥ 150 (holds) |
| `fabricated_acceptance_rate` | 0 | S3: fabricated_acceptance_rate ≤ 0.01 (holds); F1: fabricated_acceptance_rate > 0.05 (does not hold) |
| `substituted_acceptance_rate` | 0 | — |
| `swapped_acceptance_rate` | 0 | — |
| `spliced_acceptance_rate` | 0 | — |
| `short_fragment_acceptance_rate` | 0 | F3: short_fragment_acceptance_rate > 0 (does not hold) |
| `relabeled_cases` | 0 | — |
| `oracle_disagreements` | 0 | — |
| `source_attribution_rate` | 1 | — |
| `median_verify_latency_ms` *(timing; varies)* | 40.627 ms | — |

**Evaluation:** All 3 success criteria held and no failure criterion triggered.

**Reproduction:** 1 of 1 reproduction(s) matched the source run.

| Run | Kind | Status | Commit | Seed | Finished |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0001-RUN-0001](experiments/V3D-EXP-0001/runs/RUN-0001/result.json) | run | passed | `c704cf2bdd` | 20260929 | 2026-09-29 01:59:05 |
| [V3D-EXP-0001-RUN-0002](experiments/V3D-EXP-0001/runs/RUN-0002/result.json) | reproduce | passed | `c704cf2bdd` | 20260929 | 2026-09-29 01:59:35 |

**Artifacts:** [cases.json](experiments/V3D-EXP-0001/runs/RUN-0002/artifacts/cases.json)

**Limitations:**

- Measures exact-span grounding only. Semantic support (whether the passage supports the claim) is not tested.
- Fabrications are minimal synthetic perturbations of real text, not quotes written by a model.
- The corpus is the repository's papers/ snapshot; results may differ on other corpora.
- The oracle encodes the documented contract; agreement shows conformance to that contract, not that the contract is the right one.

**Reproduce:** `python rain_lab.py experiment reproduce V3D-EXP-0001`

## V3D-EXP-0002

### Citation gate tolerates typographic normalization of genuine quotes

**Result: FAILED** — hypothesis not supported · evidence: reproduced · runs: 2 (2 failed)

**Question:** Does verify_quote still accept a genuine quote when only its typography differs from the source, as happens when a model straightens curly quotes or writes hyphens for dashes?

**Hypothesis:** At least 95% of genuine 8-20 word quotes containing curly quotes/apostrophes or en/em dashes still verify after those characters are folded to ASCII (' " -).

Measurements from V3D-EXP-0002-RUN-0002:

| Metric | Value | Criteria |
| --- | --- | --- |
| `typographic_cases` | 50 | G1: typographic_cases ≥ 40 (holds) |
| `control_acceptance_rate` | 1 | G2: control_acceptance_rate ≥ 0.99 (holds) |
| `typographic_variant_acceptance_rate` | 0 | S1: typographic_variant_acceptance_rate ≥ 0.95 (does not hold); F1: typographic_variant_acceptance_rate < 0.5 (holds) |
| `quote_mark_variant_acceptance_rate` | 0 | — |
| `quote_mark_cases` | 26 | — |
| `dash_variant_acceptance_rate` | 0 | — |
| `dash_cases` | 36 | — |
| `excluded_ascii_form_present` | 0 | — |
| `median_verify_latency_ms` *(timing; varies)* | 40.058 ms | — |

**Evaluation:** Failure criterion met: F1: typographic_variant_acceptance_rate < 0.5 (observed 0).

**Reproduction:** 1 of 1 reproduction(s) matched the source run.

| Run | Kind | Status | Commit | Seed | Finished |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0002-RUN-0001](experiments/V3D-EXP-0002/runs/RUN-0001/result.json) | run | failed | `c704cf2bdd` | 20260929 | 2026-09-29 01:59:16 |
| [V3D-EXP-0002-RUN-0002](experiments/V3D-EXP-0002/runs/RUN-0002/result.json) | reproduce | failed | `c704cf2bdd` | 20260929 | 2026-09-29 01:59:41 |

**Artifacts:** [cases.json](experiments/V3D-EXP-0002/runs/RUN-0002/artifacts/cases.json)

**Limitations:**

- Only quote-mark and dash folding is tested; ellipses, ligatures, non-breaking spaces and Unicode normalization forms are not.
- Whether the gate should tolerate typography is a product decision; this measures behaviour, it does not decide policy.
- The corpus is the repository's papers/ snapshot.

**Reproduce:** `python rain_lab.py experiment reproduce V3D-EXP-0002`

## V3D-EXP-0003

### CIRCLE analysis error rates on seeded simulated controls

**Result: PASSED** — hypothesis supported · evidence: simulated · runs: 2 (2 passed)

**Question:** How often does the pre-registered CIRCLE analysis conclude SUPPORTS when a simulated effect beyond the minimum is present, versus when there is no effect at all?

**Hypothesis:** Across 200 seeded simulated trials per condition (n=30 per arm, noise SD 1.2 ohms, minimum effect 5 ohms), the analysis concludes SUPPORTS in at least 80% of trials with a true -6.5 ohm effect and in at most 5% of null trials.

Measurements from V3D-EXP-0003-RUN-0002:

| Metric | Value | Criteria |
| --- | --- | --- |
| `trials_per_condition` | 200 | G1: trials_per_condition ≥ 100 (holds) |
| `detection_rate` | 0.99 | S1: detection_rate ≥ 0.8 (holds); F1: detection_rate < 0.5 (does not hold) |
| `effect_inconclusive_rate` | 0.01 | — |
| `effect_refutes_rate` | 0 | — |
| `false_supports_rate` | 0 | S2: false_supports_rate ≤ 0.05 (holds); F2: false_supports_rate > 0.1 (does not hold) |
| `null_refutes_rate` | 0.87 | — |
| `null_inconclusive_rate` | 0.13 | — |

**Evaluation:** All 2 success criteria held and no failure criterion triggered.

**Reproduction:** 1 of 1 reproduction(s) matched the source run.

| Run | Kind | Status | Commit | Seed | Finished |
| --- | --- | --- | --- | --- | --- |
| [V3D-EXP-0003-RUN-0001](experiments/V3D-EXP-0003/runs/RUN-0001/result.json) | run | passed | `c704cf2bdd` | 7000 | 2026-09-29 01:59:17 |
| [V3D-EXP-0003-RUN-0002](experiments/V3D-EXP-0003/runs/RUN-0002/result.json) | reproduce | passed | `c704cf2bdd` | 7000 | 2026-09-29 01:59:42 |

**Limitations:**

- Simulated Gaussian data: this characterizes the analysis pipeline, not any physical, acoustic or biological effect.
- One effect size, one noise level and one sample size; error rates at other operating points are unmeasured.
- Seeds are consecutive integers; the simulator's RNG quality bounds independence between trials.

**Reproduce:** `python rain_lab.py experiment reproduce V3D-EXP-0003`

## V3D-EXP-0004

### Satellite Vision Scape: does calibration improve Jev under human-equivalent constraints?

**Result: PLANNED** — no runs yet · evidence: proposed · runs: 0 (none completed)

**Question:** Can an AI agent operating under the same controls, physics, perception constraints and weapon mechanics as a human improve measurable performance through repeated calibrated runs?

**Hypothesis:** Across at least 20 runs per group, calibrated Jev improves shot accuracy over the Jev baseline by at least 10 percentage points without increasing deaths per run.

**Pre-registered criteria** (nothing measured yet):

- Guard G1: runs_per_group_min ≥ 20
- Success S1: calibration_accuracy_gain_pp ≥ 10
- Success S2: deaths_per_run_change ≤ 0
- Failure F1: calibration_accuracy_gain_pp < 2
- Failure F2: deaths_per_run_change > 0.5

**Next step:** run it — `topherchris420/satellite-vision-scape` via `experiment record`.
