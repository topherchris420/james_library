# Experimental Results

<!-- Generated from experiments/ by `python rain_lab.py experiment results`. Do not edit by hand. -->

What R.A.I.N. actually ran, and what happened. Each status is computed by host code
from recorded measurements against criteria registered *before* the run; no model
decides it. Failed and inconclusive results stay on the record.
How to add one: [EXPERIMENTS.md](EXPERIMENTS.md). Raw records: [`experiments/`](experiments/).

**4 experiments · 0 runs** — 0 passed · 0 failed · 4 planned

Evidence: 4 proposed

| ID | Experiment | Result | Evidence | Runs |
| --- | --- | --- | --- | --- |
| [V3D-EXP-0001](#v3d-exp-0001) | Citation gate rejects fabricated quotes and accepts verbatim ones | **PLANNED** | proposed | 0 |
| [V3D-EXP-0002](#v3d-exp-0002) | Citation gate tolerates typographic normalization of genuine quotes | **PLANNED** | proposed | 0 |
| [V3D-EXP-0003](#v3d-exp-0003) | CIRCLE analysis error rates on seeded simulated controls | **PLANNED** | proposed | 0 |
| [V3D-EXP-0004](#v3d-exp-0004) | Satellite Vision Scape: does calibration improve Jev under human-equivalent constraints? | **PLANNED** | proposed | 0 |

## Negative and inconclusive results

None recorded yet.

## V3D-EXP-0001

### Citation gate rejects fabricated quotes and accepts verbatim ones

**Result: PLANNED** — no runs yet · evidence: proposed · runs: 0 (none completed)

**Question:** Does verify_quote, the quote-grounding gate used by chat, the offline demo and the MCP server, accept verbatim corpus quotes and reject minimally corrupted ones?

**Hypothesis:** On seeded 8-20 word windows from papers/, verify_quote accepts at least 99% of verbatim and case/whitespace-reformatted quotes and at most 1% of fabricated variants (one word substituted, two adjacent words swapped, or halves spliced from two papers); fragments shorter than three words are never accepted.

**Pre-registered criteria** (nothing measured yet):

- Guard G1: verbatim_cases ≥ 50
- Guard G2: fabricated_cases ≥ 150
- Success S1: verbatim_acceptance_rate ≥ 0.99
- Success S2: reformatted_acceptance_rate ≥ 0.99
- Success S3: fabricated_acceptance_rate ≤ 0.01
- Failure F1: fabricated_acceptance_rate > 0.05
- Failure F2: verbatim_acceptance_rate < 0.95
- Failure F3: short_fragment_acceptance_rate > 0

**Next step:** run it — `python rain_lab.py experiment run V3D-EXP-0001`.

## V3D-EXP-0002

### Citation gate tolerates typographic normalization of genuine quotes

**Result: PLANNED** — no runs yet · evidence: proposed · runs: 0 (none completed)

**Question:** Does verify_quote still accept a genuine quote when only its typography differs from the source, as happens when a model straightens curly quotes or writes hyphens for dashes?

**Hypothesis:** At least 95% of genuine 8-20 word quotes containing curly quotes/apostrophes or en/em dashes still verify after those characters are folded to ASCII (' " -).

**Pre-registered criteria** (nothing measured yet):

- Guard G1: typographic_cases ≥ 40
- Guard G2: control_acceptance_rate ≥ 0.99
- Success S1: typographic_variant_acceptance_rate ≥ 0.95
- Failure F1: typographic_variant_acceptance_rate < 0.5

**Next step:** run it — `python rain_lab.py experiment run V3D-EXP-0002`.

## V3D-EXP-0003

### CIRCLE analysis error rates on seeded simulated controls

**Result: PLANNED** — no runs yet · evidence: proposed · runs: 0 (none completed)

**Question:** How often does the pre-registered CIRCLE analysis conclude SUPPORTS when a simulated effect beyond the minimum is present, versus when there is no effect at all?

**Hypothesis:** Across 200 seeded simulated trials per condition (n=30 per arm, noise SD 1.2 ohms, minimum effect 5 ohms), the analysis concludes SUPPORTS in at least 80% of trials with a true -6.5 ohm effect and in at most 5% of null trials.

**Pre-registered criteria** (nothing measured yet):

- Guard G1: trials_per_condition ≥ 100
- Success S1: detection_rate ≥ 0.8
- Success S2: false_supports_rate ≤ 0.05
- Failure F1: detection_rate < 0.5
- Failure F2: false_supports_rate > 0.1

**Next step:** run it — `python rain_lab.py experiment run V3D-EXP-0003`.

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
