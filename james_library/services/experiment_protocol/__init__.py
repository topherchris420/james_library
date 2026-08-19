"""RAIN ↔ CIRCLE Experiment Protocol.

A versioned, reproducible interoperability layer between R.A.I.N. Lab and CIRCLE.
"""

from .analysis import (
    compute_cohens_d,
    compute_confidence_interval,
    compute_mean,
    compute_p_value_two_sample,
    compute_std_dev,
    compute_variance,
    run_deterministic_analysis,
)
from .bundle import (
    build_provenance_trace,
    save_experiment_bundle,
    verify_bundle_integrity,
)
from .executor import (
    CircleExperimentExecutor,
    PhysicalCircleExecutor,
    SimulatedCircleExecutor,
)
from .fixtures import (
    run_artifact_only_fixture,
    run_insufficient_sample_fixture,
    run_negative_control_fixture,
    run_positive_control_fixture,
    run_protocol_modification_fixture,
)
from .manifest import (
    PROTOCOL_VERSION,
    calculate_sha256,
    canonical_json_bytes,
    canonical_json_str,
    generate_blinding_token,
    generate_execution_id,
    generate_experiment_id,
    generate_randomization_id,
    generate_trial_id,
    validate_manifest,
    verify_manifest_hash,
)
from .provenance import (
    CIRCLE_PROVENANCE_VALUES,
    Provenance,
    enforce_executor_provenance,
    validate_provenance,
    validate_record_provenance_lineage,
)
from .reasoning import (
    assemble_experiment_analysis,
    design_experiment,
    generate_initial_interpretation,
    perform_adversarial_critique,
    propose_next_experiment,
)

__all__ = [
    "PROTOCOL_VERSION",
    "CIRCLE_PROVENANCE_VALUES",
    "Provenance",
    "validate_provenance",
    "enforce_executor_provenance",
    "validate_record_provenance_lineage",
    "generate_experiment_id",
    "generate_trial_id",
    "generate_execution_id",
    "generate_randomization_id",
    "generate_blinding_token",
    "canonical_json_bytes",
    "canonical_json_str",
    "calculate_sha256",
    "validate_manifest",
    "verify_manifest_hash",
    "CircleExperimentExecutor",
    "SimulatedCircleExecutor",
    "PhysicalCircleExecutor",
    "compute_mean",
    "compute_variance",
    "compute_std_dev",
    "compute_cohens_d",
    "compute_p_value_two_sample",
    "compute_confidence_interval",
    "run_deterministic_analysis",
    "design_experiment",
    "generate_initial_interpretation",
    "perform_adversarial_critique",
    "propose_next_experiment",
    "assemble_experiment_analysis",
    "build_provenance_trace",
    "save_experiment_bundle",
    "verify_bundle_integrity",
    "run_positive_control_fixture",
    "run_negative_control_fixture",
    "run_artifact_only_fixture",
    "run_insufficient_sample_fixture",
    "run_protocol_modification_fixture",
]
