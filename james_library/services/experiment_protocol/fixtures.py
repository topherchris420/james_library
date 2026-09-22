"""Standard Simulated Control Fixtures for Protocol Verification.

Includes:
A. Positive-control fixture (satisfies alternative hypothesis -> SUPPORTS)
B. Negative/null-control fixture (favors null hypothesis under adequate power -> REFUTES)
C. Artifact-only fixture (signal present in electronic phantom -> POTENTIAL_INSTRUMENTATION_ARTIFACT -> INCONCLUSIVE)
D. Insufficient-sample fixture (n < min_sample_size -> INCONCLUSIVE)
E. Protocol-modification fixture (modified post-hashing -> PROTOCOL_CHANGED -> INCONCLUSIVE)
"""

from __future__ import annotations

from typing import Any

from .analysis import run_deterministic_analysis
from .executor import SimulatedCircleExecutor
from .manifest import calculate_sha256
from .reasoning import assemble_experiment_analysis, design_experiment


def run_positive_control_fixture(seed: int = 101) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run A. Positive-control fixture."""
    manifest = design_experiment(
        research_question="Does 40Hz acoustic stimulation alter baseline impedance?",
        hypothesis="40Hz stimulation induces a >= 5 ohm impedance decrease relative to unpowered sham.",
        frequency_hz=40.0,
        min_sample_size=20,
        alpha_threshold=0.05,
        effect_size_threshold=0.5,
        minimum_effect_ohms=5.0,
        expected_direction="decrease",
    )
    manifest_sha = calculate_sha256(manifest)
    executor = SimulatedCircleExecutor(seed=seed)

    scenario = {
        "sample_count": 30,
        "baseline_mean": 100.0,
        "active_effect": -8.5,  # Preregistered decrease
        "noise_std": 1.2,
        "phantom_effect": 0.1,  # Clean phantom (no artifact)
    }

    result = executor.run_trial(manifest, manifest_sha, custom_scenario=scenario)
    stats = run_deterministic_analysis(manifest, result, manifest_sha)
    analysis = assemble_experiment_analysis(manifest, result, stats)
    return manifest, result, analysis


def run_negative_control_fixture(seed: int = 102) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run B. Negative/null-control fixture."""
    manifest = design_experiment(
        research_question="Does 40Hz acoustic stimulation alter baseline impedance?",
        hypothesis="40Hz stimulation induces a >= 5 ohm impedance decrease relative to unpowered sham.",
        frequency_hz=40.0,
        min_sample_size=20,
        alpha_threshold=0.05,
        effect_size_threshold=0.5,
        minimum_effect_ohms=5.0,
        expected_direction="decrease",
    )
    manifest_sha = calculate_sha256(manifest)
    executor = SimulatedCircleExecutor(seed=seed)

    scenario = {
        "sample_count": 50,  # Adequate power
        "baseline_mean": 100.0,
        "active_effect": 0.02,  # Negligible effect (< 1.0%)
        "noise_std": 1.5,
        "phantom_effect": 0.01,
    }

    result = executor.run_trial(manifest, manifest_sha, custom_scenario=scenario)
    stats = run_deterministic_analysis(manifest, result, manifest_sha)
    analysis = assemble_experiment_analysis(manifest, result, stats)
    return manifest, result, analysis


def run_artifact_only_fixture(seed: int = 103) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run C. Artifact-only fixture (signal present in phantom)."""
    manifest = design_experiment(
        research_question="Does 40Hz acoustic stimulation alter baseline impedance?",
        hypothesis="40Hz stimulation induces a >= 5 ohm impedance decrease relative to unpowered sham.",
        frequency_hz=40.0,
        min_sample_size=20,
        alpha_threshold=0.05,
        effect_size_threshold=0.5,
        minimum_effect_ohms=5.0,
        expected_direction="decrease",
    )
    manifest_sha = calculate_sha256(manifest)
    executor = SimulatedCircleExecutor(seed=seed)

    scenario = {
        "sample_count": 30,
        "baseline_mean": 100.0,
        "active_effect": -8.0,
        "noise_std": 1.0,
        "phantom_effect": -7.8,  # Signal also appears in electronic phantom!
    }

    result = executor.run_trial(manifest, manifest_sha, custom_scenario=scenario)
    stats = run_deterministic_analysis(manifest, result, manifest_sha)
    analysis = assemble_experiment_analysis(manifest, result, stats)
    return manifest, result, analysis


def run_insufficient_sample_fixture(seed: int = 104) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run D. Insufficient-sample fixture (n=3 < min_sample_size=20)."""
    manifest = design_experiment(
        research_question="Does 40Hz acoustic stimulation alter baseline impedance?",
        hypothesis="40Hz stimulation induces a >= 5 ohm impedance decrease relative to unpowered sham.",
        frequency_hz=40.0,
        min_sample_size=20,
        alpha_threshold=0.05,
        effect_size_threshold=0.5,
        minimum_effect_ohms=5.0,
        expected_direction="decrease",
    )
    manifest_sha = calculate_sha256(manifest)
    executor = SimulatedCircleExecutor(seed=seed)

    scenario = {
        "sample_count": 3,  # Too few samples
        "baseline_mean": 100.0,
        "active_effect": 10.0,
        "noise_std": 1.0,
        "phantom_effect": 0.0,
    }

    result = executor.run_trial(manifest, manifest_sha, custom_scenario=scenario)
    stats = run_deterministic_analysis(manifest, result, manifest_sha)
    analysis = assemble_experiment_analysis(manifest, result, stats)
    return manifest, result, analysis


def run_protocol_modification_fixture(seed: int = 105) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run E. Protocol-modification fixture (manifest modified post-hashing)."""
    manifest = design_experiment(
        research_question="Does 40Hz acoustic stimulation alter baseline impedance?",
        hypothesis="40Hz stimulation induces a >= 5 ohm impedance decrease relative to unpowered sham.",
        frequency_hz=40.0,
        min_sample_size=20,
        alpha_threshold=0.05,
        effect_size_threshold=0.5,
        minimum_effect_ohms=5.0,
        expected_direction="decrease",
    )
    original_manifest_sha = calculate_sha256(manifest)
    executor = SimulatedCircleExecutor(seed=seed)

    # Modify the manifest post-hashing (e.g. shift alpha threshold or change hypothesis)
    modified_manifest = dict(manifest)
    modified_manifest["hypothesis"] = "Post-hoc modified hypothesis: 40Hz alters impedance by 1%."
    modified_manifest["preregistered_analysis"] = dict(manifest["preregistered_analysis"])
    modified_manifest["preregistered_analysis"]["alpha_threshold"] = 0.10

    scenario = {
        "sample_count": 30,
        "baseline_mean": 100.0,
        "active_effect": 8.0,
        "noise_std": 1.0,
        "phantom_effect": 0.0,
    }

    result = executor.run_trial(modified_manifest, original_manifest_sha, custom_scenario=scenario)
    stats = run_deterministic_analysis(modified_manifest, result, original_manifest_sha)
    analysis = assemble_experiment_analysis(modified_manifest, result, stats)
    return modified_manifest, result, analysis
