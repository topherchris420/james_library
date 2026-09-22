"""R.A.I.N. Reasoning, Experiment Design, and Adversarial Critique Boundary.

Enforces strict epistemic constraints:
- R.A.I.N. reasons, CIRCLE witnesses.
- R.A.I.N. receives ONLY validated metadata and deterministic statistical outputs.
- Initial interpretation and adversarial critique are both preserved (no silent history rewrites).
- Next-experiment proposals are proposals only (requires_human_review=True, never auto-executed).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .manifest import (
    PROTOCOL_VERSION,
    generate_blinding_token,
    generate_experiment_id,
    generate_randomization_id,
    generate_trial_id,
    validate_manifest,
)
from .provenance import Provenance


def design_experiment(
    research_question: str,
    hypothesis: str,
    null_hypothesis: str | None = None,
    alternative_hypothesis: str | None = None,
    frequency_hz: float = 40.0,
    min_sample_size: int = 20,
    alpha_threshold: float = 0.05,
    effect_size_threshold: float = 0.5,
    requires_human_review: bool = True,
    expected_direction: str = "decrease",
    equivalence_margin_ohms: float = 1.0,
    minimum_effect_percent: float = 0.0,
) -> dict[str, Any]:
    """Design a candidate preregistered ExperimentManifest."""
    now_iso = datetime.now(timezone.utc).isoformat()
    exp_id = generate_experiment_id()
    trial_id = generate_trial_id()
    rand_id = generate_randomization_id()
    blind_token = generate_blinding_token()

    if not null_hypothesis:
        null_hypothesis = (
            f"Application of {frequency_hz} Hz stimulus produces no measurable change in target channel response "
            f"relative to baseline."
        )
    if not alternative_hypothesis:
        alternative_hypothesis = (
            f"Application of {frequency_hz} Hz stimulus induces a statistically significant response change "
            f"(effect direction: {expected_direction}, |Cohen's d| >= {effect_size_threshold}, "
            f"|change| >= {minimum_effect_percent}%, alpha = {alpha_threshold})."
        )

    manifest: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "experiment_id": exp_id,
        "trial_id": trial_id,
        "created_at": now_iso,
        "created_by": "R.A.I.N. Experiment Designer v1",
        "research_question": research_question.strip(),
        "hypothesis": hypothesis.strip(),
        "null_hypothesis": null_hypothesis.strip(),
        "alternative_hypothesis": alternative_hypothesis.strip(),
        "experimental_design": "Randomized, sham-controlled, electronic-phantom-verified trial",
        "independent_variables": [
            "stimulus_frequency_hz",
            "condition_role (ACTIVE vs SHAM vs PHANTOM)",
        ],
        "dependent_variables": [
            "impedance_magnitude_ohms",
            "resonance_response_amplitude_uv",
        ],
        "control_conditions": ["UNPOWERED_SHAM", "ELECTRONIC_PHANTOM"],
        "sham_conditions": ["MATCHED_IMPEDANCE_PASSIVE_LOAD"],
        "confounders": [
            "Electrode-skin interface impedance drift",
            "Ambient thermal fluctuations",
            "Electromagnetic interference (EMI) coupling",
        ],
        "exclusion_criteria": [
            "Sensor signal-to-noise ratio < 12 dB",
            "Clock synchronization jitter > 500 us",
            "Electrode contact impedance > 50 kOhm",
        ],
        "stopping_rules": [
            "Immediate stop on sensor failure or buffer overrun",
            "Immediate stop on safety gate violation",
        ],
        "preregistered_analysis": {
            "statistical_test": "Welch's two-sample t-test and Cohen's d effect size",
            "alpha_threshold": alpha_threshold,
            "min_sample_size": min_sample_size,
            "effect_size_threshold": effect_size_threshold,
            "minimum_effect_percent": minimum_effect_percent,
            "expected_direction": expected_direction,
            "equivalence_margin_ohms": equivalence_margin_ohms,
            "falsification_criteria": [
                (
                    f"The (1 - 2*alpha) Welch confidence interval for active minus sham "
                    f"is strictly inside +/-{equivalence_margin_ohms} ohms (TOST equivalence)."
                ),
            ],
            "artifact_rejection_rules": [
                (
                    "If electronic phantom response amplitude >= 40% of active response amplitude, "
                    "flag POTENTIAL_INSTRUMENTATION_ARTIFACT and reject biological interpretation"
                ),
            ],
        },
        "expected_measurements": [
            "raw_time_series_voltage_uv",
            "impedance_magnitude_series",
            "phantom_calibration_series",
        ],
        "required_sensor_channels": [
            "CH_RESONANCE_0",
            "CH_PHANTOM_REF",
            "CH_ENVIRONMENTAL_TEMP",
        ],
        "intervention_description": {
            "type": "ACOUSTIC_RESONANCE",
            "parameters": {
                "frequency_hz": frequency_hz,
                "amplitude_normalized": 0.5,
                "duration_ms": 1000.0,
            },
        },
        "randomization": {
            "randomization_id": rand_id,
            "method": "block_randomization_permuted",
            "seed": 42,
        },
        "blinding": {
            "is_blinded": True,
            "blinding_token": blind_token,
            "condition_role": "UNKNOWN",
        },
        "provenance_requirements": [
            Provenance.SIMULATED.value,
            Provenance.TEST.value,
        ],
        "safety_requirements": [
            "ENGINEERING_REVIEW_ONLY",
            "NO_HUMAN_CONNECTION",
            "NO_POWERED_ELECTRODES",
            "SIMULATED_BACKEND_ONLY",
        ],
        "software_versions": {
            "rain_lab": "1.0.0",
            "circle_protocol": "1.0.0",
        },
        "hardware_versions": {
            "circle_board": "REV_A_SIMULATED",
        },
        "requires_human_review": requires_human_review,
    }

    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(f"Designed manifest failed internal validation: {'; '.join(errors)}")

    return manifest


def generate_initial_interpretation(
    manifest: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Generate initial R.A.I.N. interpretation bounded by deterministic statistical output."""
    conclusion = stats["conclusion"]
    p_val = stats["statistical_results"]["p_value"]
    d = stats["effect_sizes"]["cohens_d"]
    diff = stats["effect_sizes"]["mean_difference"]
    n = stats["statistical_results"]["sample_size"]

    if conclusion == "SUPPORTS":
        interpretation = (
            f"The deterministic analysis indicates a statistically significant difference "
            f"(mean difference = {diff:.3f}, Cohen's d = {d:.3f}, p = {p_val:.4g}, n = {n}). "
            f"The observed data satisfy the preregistered criteria for the alternative hypothesis. "
            f"However, this supports the hypothesis within the bounds of this protocol; "
            f"it does not constitute absolute proof."
        )
        rationale = (
            "Preregistered significance and effect size thresholds were achieved without artifact disqualification."
        )
    elif conclusion == "REFUTES":
        interpretation = (
            f"The deterministic equivalence test bounds the active-versus-sham contrast "
            f"within the preregistered margin (n = {n}, mean diff = {diff:.3f}). "
            f"This refutes effects at or beyond that margin in this simulated setup, not every effect."
        )
        rationale = "The preregistered Welch equivalence interval is inside the fixed margin."
    else:
        interpretation = (
            f"The deterministic analysis yielded an INCONCLUSIVE outcome: {stats['evidence_summary']} "
            f"(sample size n = {n}, p = {p_val:.4g}, d = {d:.3f}). "
            f"No biological or physical effect can be affirmed from this dataset."
        )
        rationale = (
            "Quality constraints, sample power, protocol matching, or artifact thresholds prevented a clean inference."
        )

    return {
        "interpretation": interpretation,
        "preliminary_conclusion": conclusion,
        "rationale": rationale,
    }


def perform_adversarial_critique(
    manifest: dict[str, Any],
    stats: dict[str, Any],
    initial_interpretation: dict[str, Any],
) -> dict[str, Any]:
    """Perform an adversarial critique evaluating artifacts, confounders, and alternative explanations."""
    conclusion = stats["conclusion"]
    artifact_analysis = stats["artifact_analysis"]
    deviations = stats["protocol_deviations"]
    flags = stats["quality_assessment"]["quality_flags"]

    supporting = []
    contradicting = []
    potential_artifacts = []
    confounders = list(manifest.get("confounders", []))
    missing_measurements = []

    if conclusion == "SUPPORTS":
        supporting.append(f"Statistically significant contrast (p={stats['statistical_results']['p_value']:.4g})")
        supporting.append(f"Effect size Cohen's d={stats['effect_sizes']['cohens_d']:.3f} >= threshold")
        if artifact_analysis.get("phantom_signal_detected"):
            contradicting.append("Signal detected in electronic phantom control at comparable magnitude")
            potential_artifacts.append("Instrumentation coupling into high-impedance channels")
    elif conclusion == "REFUTES":
        supporting.append("Welch equivalence interval lies inside the preregistered margin")
        contradicting.append("Alternative biological mechanisms with non-linear latency curves not tested")
    else:
        contradicting.append(f"Material limit: {stats['evidence_summary']}")

    if "POTENTIAL_INSTRUMENTATION_ARTIFACT" in flags:
        potential_artifacts.append("Capacitive or electromagnetic cross-talk between stimulator and sensor")

    epistemic_status = "adheres strictly to" if stats["protocol_status"] == "PREREGISTERED_VALID" else "violates"
    artifact_status = (
        "CRITICAL ARTIFACT PRESENT"
        if artifact_analysis.get("phantom_signal_detected")
        else "Phantom controls show no cross-talk artifact"
    )
    critique_text = (
        f"Adversarial Review of {conclusion} Assessment:\n"
        f"1. Epistemic Rigor: The analysis {epistemic_status} the preregistered manifest.\n"
        f"2. Artifact Vulnerability: {artifact_status}.\n"
        f"3. Uncontrolled Confounders: Electrode drift and ambient thermal gradients remain theoretical confounders.\n"
        f"4. Model Grounding: All statistics were calculated deterministically; no synthetic LLM metrics introduced."
    )

    return {
        "critique": critique_text,
        "supporting_evidence": supporting or ["None recorded"],
        "contradicting_evidence": contradicting or ["None recorded"],
        "potential_artifacts": potential_artifacts or ["None identified beyond baseline"],
        "uncontrolled_confounders": confounders,
        "missing_measurements": missing_measurements,
        "weakest_assumption": "Assumes linear response of sensor frontend under resonant stimulation",
        "falsification_criteria_met": stats.get("falsification_criteria_met", False),
        "adheres_to_preregistration": stats["protocol_status"] == "PREREGISTERED_VALID",
    }


def propose_next_experiment(
    manifest: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Generate a structured next-experiment proposal (NEVER automatically executed)."""
    conclusion = stats["conclusion"]
    freq = manifest.get("intervention_description", {}).get("parameters", {}).get("frequency_hz", 40.0)

    if conclusion == "SUPPORTS":
        reason = "Replicate supported finding with varied frequency sweep and independent phantom isolation."
        target_unc = "Frequency specificity of the observed resonance peak."
        hyp = (
            f"Resonance effect is maximal at {freq} Hz with a sharp Q-factor drop off at "
            f"{freq * 0.8:.1f} Hz and {freq * 1.2:.1f} Hz."
        )
        control = "Dual-phantom shielded reference with non-conductive sham load."
        meas = "Multi-channel spectral density and phase-lag across frequency steps."
        gain = "Quantifies bandwidth of the resonance effect."
    elif conclusion == "REFUTES":
        reason = "Investigate alternative non-linear harmonic frequencies given refutation of fundamental."
        target_unc = "Whether sub-harmonics or higher-order modes exhibit coupling."
        hyp = f"Second harmonic ({freq * 2.0:.1f} Hz) induces response where fundamental was refuted."
        control = "Unpowered sham and electronic phantom load."
        meas = "Harmonic distortion and phase coherence series."
        gain = "Determines if mode-hopping occurred."
    else:
        reason = "Resolve inconclusive trial by remediating sample size and phantom isolation."
        target_unc = "Elimination of potential instrumentation artifacts and sample power deficit."
        hyp = (
            f"Under adequate sample size (n=50) and active shielding, {freq} Hz response is distinguishable "
            f"from phantom baseline."
        )
        control = "Active ground shielded phantom and matched thermal control."
        meas = "Differential sensor voltage with active common-mode rejection."
        gain = "Provides decisive statistical power and artifact discrimination."

    return {
        "reason": reason,
        "targeted_uncertainty": target_unc,
        "hypothesis": hyp,
        "control": control,
        "measurement": meas,
        "expected_information_gain": gain,
        "requires_human_review": True,
    }


def assemble_experiment_analysis(
    manifest: dict[str, Any],
    result: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Assemble complete ExperimentAnalysis combining deterministic statistics and R.A.I.N. reasoning."""
    initial_analysis = generate_initial_interpretation(manifest, stats)
    adversarial_critique = perform_adversarial_critique(manifest, stats, initial_analysis)
    next_experiment = propose_next_experiment(manifest, stats)
    now_iso = datetime.now(timezone.utc).isoformat()

    analysis: dict[str, Any] = {
        **stats,
        "initial_analysis": initial_analysis,
        "adversarial_critique": adversarial_critique,
        "recommended_next_experiment": next_experiment,
        "model_identity": "R.A.I.N.-Reasoning-Engine",
        "model_version": "1.0.0",
        "analysis_timestamp": now_iso,
    }

    return analysis
