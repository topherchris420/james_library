"""Error rates of the CIRCLE pre-registered analysis on seeded simulated controls.

Wraps the existing ``experiment_protocol`` simulator and deterministic
analysis without changing them. The data are simulated, so the run record is
``simulated`` evidence: it characterizes the analysis pipeline's detection
and false-support rates, not any physical or biological effect.
"""

from __future__ import annotations

import math
from typing import Any

from james_library.services.experiment_protocol import (
    SimulatedCircleExecutor,
    calculate_sha256,
    design_experiment,
    run_deterministic_analysis,
)

from ..runner import RunContext, RunOutput
from ..schema import ExperimentError


def _number(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExperimentError(f"parameter {key!r} must be a finite number")
    return float(value)


def run_circle_error_rates(ctx: RunContext) -> RunOutput:
    params = ctx.parameters
    trials = params.get("trials_per_condition")
    samples = params.get("sample_count")
    for key, value, high in (("trials_per_condition", trials, 5000), ("sample_count", samples, 10_000)):
        if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= high:
            raise ExperimentError(f"parameter {key!r} must be an integer in [2, {high}]")
    if ctx.seed is None:
        raise ExperimentError("this experiment needs a seed")
    minimum_effect = _number(params, "minimum_effect_ohms")
    scenario = {"sample_count": samples, "baseline_mean": _number(params, "baseline_mean"),
                "noise_std": _number(params, "noise_std"), "phantom_effect": _number(params, "phantom_effect")}
    manifest = design_experiment(
        research_question="Registry calibration: CIRCLE analysis error rates on simulated controls",
        hypothesis=f"The active condition lowers impedance by at least {minimum_effect} ohms.",
        min_sample_size=20, alpha_threshold=0.05, effect_size_threshold=0.5,
        minimum_effect_ohms=minimum_effect, expected_direction="decrease",
    )
    manifest_sha = calculate_sha256(manifest)

    conclusions: dict[str, dict[str, int]] = {}
    differences: dict[str, list[float]] = {}
    for condition, effect, offset in (("effect", _number(params, "true_effect_ohms"), 0),
                                      ("null", 0.0, 1_000_000)):
        counts = {"SUPPORTS": 0, "REFUTES": 0, "INCONCLUSIVE": 0}
        diffs = []
        for trial in range(trials):
            executor = SimulatedCircleExecutor(seed=ctx.seed + offset + trial)
            result = executor.run_trial(manifest, manifest_sha, custom_scenario={**scenario, "active_effect": effect})
            stats = run_deterministic_analysis(manifest, result, manifest_sha)
            counts[stats["conclusion"]] = counts.get(stats["conclusion"], 0) + 1
            diffs.append(round(stats["effect_sizes"]["mean_difference"], 6))
        conclusions[condition] = counts
        differences[condition] = diffs

    def rate(condition: str, label: str) -> float:
        return round(conclusions[condition].get(label, 0) / trials, 9)

    return RunOutput(
        measurements={
            "trials_per_condition": trials,
            "detection_rate": rate("effect", "SUPPORTS"),
            "effect_inconclusive_rate": rate("effect", "INCONCLUSIVE"),
            "effect_refutes_rate": rate("effect", "REFUTES"),
            "false_supports_rate": rate("null", "SUPPORTS"),
            "null_refutes_rate": rate("null", "REFUTES"),
            "null_inconclusive_rate": rate("null", "INCONCLUSIVE"),
        },
        series={"effect_mean_difference_ohms": differences["effect"],
                "null_mean_difference_ohms": differences["null"]},
        inputs={"manifest_preregistered_analysis": manifest["preregistered_analysis"], "scenario": scenario,
                "conclusion_counts": conclusions},
        observations=[f"{2 * trials} simulated trials analysed with the unchanged CIRCLE analysis."],
    )
