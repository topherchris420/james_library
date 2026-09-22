"""Deterministic Statistical Analysis and Artifact Discrimination Engine.

Enforces strict boundaries:
- Pure-Python deterministic calculations (no LLM-invented statistics).
- Tri-state conclusions: SUPPORTS, REFUTES, INCONCLUSIVE.
- SUPPORTS does NOT mean proven.
- Absence of significance does NOT mean REFUTES (mandatory INCONCLUSIVE unless falsification criterion met).
- Artifact phantom checks downgrade biological conclusions.
- Protocol hash mismatches yield PROTOCOL_CHANGED and force INCONCLUSIVE.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from .manifest import calculate_sha256
from .provenance import Provenance


def compute_mean(values: list[float]) -> float:
    """Compute arithmetic mean."""
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def compute_variance(values: list[float], ddof: int = 1) -> float:
    """Compute sample variance with specified degrees of freedom."""
    n = len(values)
    if n <= ddof:
        return 0.0
    mean = compute_mean(values)
    return float(sum((x - mean) ** 2 for x in values) / (n - ddof))


def compute_std_dev(values: list[float], ddof: int = 1) -> float:
    """Compute standard deviation."""
    return float(math.sqrt(max(0.0, compute_variance(values, ddof))))


def compute_cohens_d(group1: list[float], group2: list[float]) -> float:
    """Compute Cohen's d effect size between group1 (control) and group2 (active)."""
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        return 0.0
    m1, m2 = compute_mean(group1), compute_mean(group2)
    v1, v2 = compute_variance(group1, 1), compute_variance(group2, 1)
    pooled_var = ((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)
    pooled_sd = math.sqrt(max(1e-12, pooled_var))
    return float((m2 - m1) / pooled_sd)


def _beta_fraction(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta function."""
    tiny = 1e-300
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 501):
        m2 = 2 * m
        aa = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 2e-14:
            return h
    raise ArithmeticError("incomplete beta did not converge")


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    prefactor = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        value = prefactor * _beta_fraction(a, b, x) / a
    else:
        value = 1.0 - prefactor * _beta_fraction(b, a, 1.0 - x) / b
    return max(0.0, min(1.0, value))


def _two_sided_t_tail(t_statistic: float, degrees_of_freedom: float) -> float:
    x = degrees_of_freedom / (degrees_of_freedom + t_statistic**2)
    return _regularized_beta(x, degrees_of_freedom / 2.0, 0.5)


def _t_critical(confidence_level: float, degrees_of_freedom: float) -> float:
    target_tail = 1.0 - confidence_level
    lo, hi = 0.0, 1.0
    while _two_sided_t_tail(hi, degrees_of_freedom) > target_tail:
        hi *= 2.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _two_sided_t_tail(mid, degrees_of_freedom) > target_tail:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def compute_p_value_two_sample(group1: list[float], group2: list[float]) -> tuple[float, float, float]:
    """Compute Welch's t-statistic, two-tailed p-value, and degrees of freedom."""
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        return 0.0, 1.0, 0.0

    m1, m2 = compute_mean(group1), compute_mean(group2)
    v1, v2 = compute_variance(group1, 1), compute_variance(group2, 1)

    component1, component2 = v1 / n1, v2 / n2
    se_squared = component1 + component2
    if se_squared <= 0.0:
        return 0.0, 1.0, 0.0  # A zero-variance contrast cannot support inference.
    t_stat = (m2 - m1) / math.sqrt(se_squared)

    # Welch-Satterthwaite degrees of freedom
    weight1, weight2 = component1 / se_squared, component2 / se_squared
    df = 1.0 / (weight1**2 / (n1 - 1) + weight2**2 / (n2 - 1))
    return t_stat, _two_sided_t_tail(t_stat, df), df


def compute_confidence_interval(
    mean_diff: float, se: float, confidence_level: float = 0.95,
    degrees_of_freedom: float | None = None,
) -> tuple[float, float]:
    """Mean-difference interval; provide Welch degrees of freedom for inference."""
    if not 0.0 < confidence_level < 1.0 or not math.isfinite(se) or se < 0.0:
        raise ValueError("invalid confidence interval parameters")
    if degrees_of_freedom is not None and degrees_of_freedom <= 0:
        raise ValueError("degrees of freedom must be positive")
    critical = (
        NormalDist().inv_cdf((1.0 + confidence_level) / 2.0)
        if degrees_of_freedom is None
        else _t_critical(confidence_level, degrees_of_freedom)
    )
    margin = critical * se
    return float(mean_diff - margin), float(mean_diff + margin)


def run_deterministic_analysis(
    manifest: dict[str, Any],
    result: dict[str, Any],
    original_manifest_sha256: str,
) -> dict[str, Any]:
    """Perform deterministic statistical analysis and assign tri-state conclusion.

    Returns a structured dictionary conforming to experiment-analysis.schema.json.
    """
    protocol_status = "PREREGISTERED_VALID"
    result_manifest_sha = result.get("manifest_sha256", "")
    manifest_actual_sha = calculate_sha256(manifest)

    # Immutability Check: protocol tampering detection
    if (
        result_manifest_sha.lower() != original_manifest_sha256.lower()
        or manifest_actual_sha.lower() != original_manifest_sha256.lower()
    ):
        protocol_status = "PROTOCOL_CHANGED"

    pa = manifest.get("preregistered_analysis", {})
    alpha = float(pa.get("alpha_threshold", 0.05))
    min_n = int(pa.get("min_sample_size", 10))
    effect_threshold = float(pa.get("effect_size_threshold", 0.5))
    minimum_effect_percent = float(pa.get("minimum_effect_percent", 0.0))
    if not math.isfinite(alpha) or not 0 < alpha < 0.5 or 1.0 - 2.0 * alpha >= 1.0:
        raise ValueError("alpha_threshold cannot define a valid equivalence interval")
    if (not math.isfinite(effect_threshold) or effect_threshold < 0
            or not math.isfinite(minimum_effect_percent) or minimum_effect_percent < 0
            or min_n < 2):
        raise ValueError("invalid preregistered effect or sample threshold")
    direction = pa.get("expected_direction")
    equivalence_margin = pa.get("equivalence_margin_ohms")
    if equivalence_margin is not None and (
        isinstance(equivalence_margin, bool) or not isinstance(equivalence_margin, (int, float))
        or not math.isfinite(equivalence_margin) or equivalence_margin <= 0
    ):
        raise ValueError("invalid preregistered equivalence margin")

    # Extract measurements from result payload
    embedded = result.get("_embedded_data", {})
    measurements = embedded.get("measurements", {})
    control_vals = measurements.get("control", [])
    active_vals = measurements.get("active", [])
    phantom_vals = measurements.get("phantom", [])
    for values in (control_vals, active_vals, phantom_vals):
        if not isinstance(values, list) or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in values
        ):
            raise ValueError("measurements must be finite numeric arrays")

    n_ctrl, n_act = len(control_vals), len(active_vals)
    effective_n = min(n_ctrl, n_act)

    # Calculate statistics
    m_ctrl = compute_mean(control_vals)
    m_act = compute_mean(active_vals)
    v_ctrl = compute_variance(control_vals)
    v_act = compute_variance(active_vals)
    if not all(math.isfinite(value) for value in (m_ctrl, m_act, v_ctrl, v_act)):
        raise ValueError("measurement summary is not finite")
    sd_ctrl = compute_std_dev(control_vals)
    sd_act = compute_std_dev(active_vals)

    mean_diff = float(m_act - m_ctrl)
    mean_diff_pct = float((mean_diff / m_ctrl * 100.0) if abs(m_ctrl) > 1e-9 else 0.0)
    cohens_d = compute_cohens_d(control_vals, active_vals)
    t_stat, p_val, df = compute_p_value_two_sample(control_vals, active_vals)
    if not all(math.isfinite(value) for value in (mean_diff, mean_diff_pct, cohens_d, t_stat, p_val, df)):
        raise ValueError("inferential statistics are not finite")

    se_diff = math.sqrt(v_ctrl / max(1, n_ctrl) + v_act / max(1, n_act))
    ci_lower, ci_upper = (
        compute_confidence_interval(mean_diff, se_diff, 0.95, df) if df > 0 else (None, None)
    )
    # TOST at alpha: equivalence holds only when the (1 - 2*alpha) interval
    # lies wholly inside the margin fixed before measurements were collected.
    equivalence_interval = (
        compute_confidence_interval(mean_diff, se_diff, 1.0 - 2.0 * alpha, df)
        if df > 0 and 0.0 < alpha < 0.5 and isinstance(equivalence_margin, (int, float))
        and not isinstance(equivalence_margin, bool) and math.isfinite(equivalence_margin)
        and equivalence_margin > 0 else None
    )
    equivalent = (
        equivalence_interval is not None
        and -equivalence_margin < equivalence_interval[0]
        and equivalence_interval[1] < equivalence_margin
    )
    direction_matches = (
        direction == "two_sided"
        or direction == "increase" and mean_diff > 0
        or direction == "decrease" and mean_diff < 0
    )
    supports = (
        p_val < alpha and abs(cohens_d) >= effect_threshold
        and abs(mean_diff_pct) >= minimum_effect_percent and direction_matches
    )

    # Artifact Analysis
    m_phantom = compute_mean(phantom_vals)
    phantom_diff = float(m_phantom - m_ctrl)
    if not math.isfinite(phantom_diff):
        raise ValueError("phantom contrast is not finite")
    phantom_tested = len(phantom_vals) > 0
    phantom_signal_detected = False
    artifact_flags: list[str] = []

    # Ratios against a near-zero active contrast exaggerate phantom noise.
    # The artifact rule applies when there is a material active signal to explain.
    if phantom_tested and df > 0 and p_val < alpha and abs(cohens_d) >= effect_threshold:
        phantom_ratio = abs(phantom_diff) / abs(mean_diff)
        if phantom_ratio >= 0.40:
            phantom_signal_detected = True
            artifact_flags.append("POTENTIAL_INSTRUMENTATION_ARTIFACT")

    # Quality Assessment
    quality_flags = list(result.get("quality_flags", []))
    deviations = list(result.get("deviations_from_protocol", []))
    failed_measurements = list(result.get("failed_measurements", []))

    critical_failure = False
    if "SENSOR_DROPOUT_DETECTED" in quality_flags or "CLOCK_SYNC_DEGRADED" in quality_flags:
        critical_failure = True
    if any(d.get("severity") == "CRITICAL" for d in deviations if isinstance(d, dict)):
        critical_failure = True
    if failed_measurements:
        critical_failure = True

    # Conclusion State Machine
    conclusion: str
    conclusion_confidence: float
    evidence_summary: str
    falsification_criteria_met = False

    if protocol_status == "PROTOCOL_CHANGED":
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.0
        evidence_summary = (
            "PROTOCOL_CHANGED: Manifest SHA-256 hash mismatch between preregistration and execution. "
            "Analysis cannot be verified as preregistered."
        )
    elif critical_failure:
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.0
        evidence_summary = (
            f"INCONCLUSIVE: Critical measurement/quality failure detected in trial execution. "
            f"Quality flags: {', '.join(quality_flags)}."
        )
    elif effective_n < max(2, min_n):
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.0
        evidence_summary = (
            f"INCONCLUSIVE: Inadequate sample size (n={effective_n} < min_sample_size={min_n}). "
            f"Statistical power is insufficient for preregistered hypothesis testing."
        )
    elif phantom_signal_detected:
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.2
        evidence_summary = (
            f"INCONCLUSIVE: POTENTIAL_INSTRUMENTATION_ARTIFACT detected. The observed signal "
            f"(diff={mean_diff:.3f}) was also detected in the electronic phantom control "
            f"(phantom_diff={phantom_diff:.3f}). Biological causation cannot be established."
        )
    elif df <= 0:
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.0
        evidence_summary = "INCONCLUSIVE: Variance is not estimable; Welch inference cannot be performed."
    elif not isinstance(direction, str) or direction not in {"increase", "decrease", "two_sided"}:
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.0
        evidence_summary = "INCONCLUSIVE: Preregistered expected_direction is missing or invalid."
    elif supports and equivalent:
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.0
        evidence_summary = (
            "INCONCLUSIVE: Both significance and equivalence criteria passed. "
            "The preregistered effect threshold overlaps the equivalence margin."
        )
    elif supports:
        conclusion = "SUPPORTS"
        conclusion_confidence = 0.0  # No calibrated probability that a scientific claim is true.
        evidence_summary = (
            f"SUPPORTS: Preregistered statistical criteria satisfied (p={p_val:.4g} < alpha={alpha}, "
            f"|Cohen's d|={abs(cohens_d):.3f} >= threshold={effect_threshold}, "
            f"|change|={abs(mean_diff_pct):.2f}% >= {minimum_effect_percent:g}%, "
            f"direction={direction}). "
            f"Evidence favors alternative hypothesis. (Does NOT imply absolute proof)."
        )
    elif equivalent:
        falsification_criteria_met = True
        conclusion = "REFUTES"
        conclusion_confidence = 0.0
        evidence_summary = (
            f"REFUTES: The {100 * (1 - 2 * alpha):.0f}% Welch interval "
            f"[{equivalence_interval[0]:.3f}, {equivalence_interval[1]:.3f}] ohms "
            f"is within the preregistered +/-{equivalence_margin:g} ohm equivalence margin. "
            "This rules out effects of that magnitude in this simulated protocol, not all possible effects."
        )
    else:
        conclusion = "INCONCLUSIVE"
        conclusion_confidence = 0.0
        evidence_summary = (
            f"INCONCLUSIVE: Support criteria were not met (p={p_val:.4g}, "
            f"d={cohens_d:.3f}, expected direction={direction}). "
            "Equivalence was not established; non-significance alone cannot refute a claim."
        )

    statistical_results = {
        "method": "welch_t_equivalence_v2",
        "sample_size": effective_n,
        "mean_control": round(m_ctrl, 4),
        "mean_active": round(m_act, 4),
        "variance_control": round(v_ctrl, 4),
        "variance_active": round(v_act, 4),
        "std_dev_control": round(sd_ctrl, 4),
        "std_dev_active": round(sd_act, 4),
        "t_statistic": t_stat,
        "p_value": p_val,
        "degrees_of_freedom": df,
        "equivalence_test": {
            "margin_ohms": equivalence_margin,
            "confidence_level": 1.0 - 2.0 * alpha,
            "lower_bound": equivalence_interval[0] if equivalence_interval else None,
            "upper_bound": equivalence_interval[1] if equivalence_interval else None,
            "established": equivalent,
        },
    }

    effect_sizes = {
        "cohens_d": round(cohens_d, 4),
        "mean_difference": round(mean_diff, 4),
        "mean_difference_percent": round(mean_diff_pct, 4),
    }

    confidence_intervals = {
        "confidence_level": 0.95,
        "lower_bound": ci_lower,
        "upper_bound": ci_upper,
    }

    quality_assessment = {
        "data_quality_score": (
            1.0 if not critical_failure and not artifact_flags else (0.2 if critical_failure else 0.5)
        ),
        "quality_flags": quality_flags + artifact_flags,
        "is_acceptable": not critical_failure,
    }

    artifact_analysis = {
        "phantom_tested": phantom_tested,
        "phantom_signal_detected": phantom_signal_detected,
        "artifact_explanation_plausible": phantom_signal_detected,
        "artifact_flags": artifact_flags,
    }

    observed_effects = {
        "control_mean": round(m_ctrl, 4),
        "active_mean": round(m_act, 4),
        "measured_difference": round(mean_diff, 4),
    }

    return {
        "protocol_version": "1.0.0",
        "experiment_id": manifest["experiment_id"],
        "trial_id": manifest["trial_id"],
        "execution_id": result["execution_id"],
        "manifest_sha256": original_manifest_sha256,
        "result_sha256": calculate_sha256(result),
        "protocol_status": protocol_status,
        "hypothesis": manifest["hypothesis"],
        "null_hypothesis": manifest["null_hypothesis"],
        "preregistered_analysis": pa,
        "observed_effects": observed_effects,
        "statistical_results": statistical_results,
        "effect_sizes": effect_sizes,
        "confidence_intervals": confidence_intervals,
        "quality_assessment": quality_assessment,
        "protocol_deviations": deviations,
        "artifact_analysis": artifact_analysis,
        "alternative_explanations": [
            "Thermal drift in measurement electrodes",
            "Electronic phantom coupling artifact",
            "Random measurement fluctuation",
        ],
        "evidence_summary": evidence_summary,
        "conclusion": conclusion,
        "conclusion_confidence": conclusion_confidence,
        "falsification_criteria_met": falsification_criteria_met,
        "provenance": Provenance.DERIVED.value,
        "post_hoc_analysis": {
            "unregistered_exploratory_notes": "None performed. Strict preregistration maintained."
        },
    }
