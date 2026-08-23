"""Experiment Manifest creation, deterministic serialization, hashing, and validation."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

from .provenance import CIRCLE_PROVENANCE_VALUES

PROTOCOL_VERSION = "1.0.0"

_EXP_ID_REGEX = re.compile(r"^EXP-[0-9A-Fa-f]{8,}$")
_TRL_ID_REGEX = re.compile(r"^TRL-[0-9A-Fa-f]{8,}$")
_EXEC_ID_REGEX = re.compile(r"^EXEC-[0-9A-Fa-f]{8,}$")
_SHA256_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")


def generate_experiment_id() -> str:
    """Generate a stable opaque experiment identifier (e.g., EXP-A1B2C3D4)."""
    return f"EXP-{secrets.token_hex(4).upper()}"


def generate_trial_id() -> str:
    """Generate a stable opaque trial identifier (e.g., TRL-E5F67890).

    Does NOT encode experimental condition or blinding state into the trial ID.
    """
    return f"TRL-{secrets.token_hex(4).upper()}"


def generate_execution_id() -> str:
    """Generate a stable opaque execution identifier (e.g., EXEC-11223344)."""
    return f"EXEC-{secrets.token_hex(4).upper()}"


def generate_randomization_id() -> str:
    """Generate an opaque randomization identifier."""
    return f"RND-{secrets.token_hex(4).upper()}"


def generate_blinding_token() -> str:
    """Generate an opaque blinding token."""
    return f"BLIND-{secrets.token_hex(6).upper()}"


def canonical_json_bytes(data: Any) -> bytes:
    """Deterministically serialize data to canonical JSON UTF-8 bytes.

    Uses sorted keys, no extraneous whitespace separators, and ensure_ascii=False.
    """
    json_str = json.dumps(
        data,
        sort_keys=True,
        indent=None,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return json_str.encode("utf-8")


def canonical_json_str(data: Any) -> str:
    """Deterministically serialize data to formatted canonical JSON string."""
    return json.dumps(
        data,
        sort_keys=True,
        indent=2,
        separators=(",", ": "),
        ensure_ascii=False,
    )


def calculate_sha256(data: Any) -> str:
    """Calculate the SHA-256 hex digest of canonically serialized data."""
    if isinstance(data, (bytes, bytearray)):
        payload = bytes(data)
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        payload = canonical_json_bytes(data)
    return hashlib.sha256(payload).hexdigest()


def validate_manifest(manifest: Any) -> list[str]:
    """Validate that a candidate manifest dictionary conforms to the preregistered schema.

    Returns:
        list[str]: A list of validation error descriptions (empty if valid).
    """
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["Manifest must be a JSON object"]

    required_fields = [
        "protocol_version",
        "experiment_id",
        "trial_id",
        "created_at",
        "created_by",
        "research_question",
        "hypothesis",
        "null_hypothesis",
        "alternative_hypothesis",
        "experimental_design",
        "independent_variables",
        "dependent_variables",
        "control_conditions",
        "sham_conditions",
        "confounders",
        "exclusion_criteria",
        "stopping_rules",
        "preregistered_analysis",
        "expected_measurements",
        "required_sensor_channels",
        "intervention_description",
        "randomization",
        "blinding",
        "provenance_requirements",
        "safety_requirements",
        "software_versions",
        "hardware_versions",
        "requires_human_review",
    ]

    for field in required_fields:
        if field not in manifest:
            errors.append(f"Missing required manifest field: '{field}'")

    if errors:
        return errors

    # Check ID patterns
    if not _EXP_ID_REGEX.match(manifest.get("experiment_id", "")):
        errors.append(f"Invalid experiment_id format: '{manifest.get('experiment_id')}' (must match EXP-XXXXXXXX)")
    if not _TRL_ID_REGEX.match(manifest.get("trial_id", "")):
        errors.append(f"Invalid trial_id format: '{manifest.get('trial_id')}' (must match TRL-XXXXXXXX)")

    # Check strings
    for str_field in (
        "research_question",
        "hypothesis",
        "null_hypothesis",
        "alternative_hypothesis",
        "experimental_design",
        "created_by",
    ):
        val = manifest.get(str_field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"Field '{str_field}' must be a non-empty string")

    # Check preregistered analysis
    pa = manifest.get("preregistered_analysis")
    if not isinstance(pa, dict):
        errors.append("Field 'preregistered_analysis' must be an object")
    else:
        for pa_field in (
            "statistical_test",
            "alpha_threshold",
            "min_sample_size",
            "effect_size_threshold",
            "falsification_criteria",
            "artifact_rejection_rules",
        ):
            if pa_field not in pa:
                errors.append(f"Missing preregistered_analysis field: '{pa_field}'")

        alpha = pa.get("alpha_threshold")
        if not isinstance(alpha, (int, float)) or alpha <= 0 or alpha > 1:
            errors.append(f"alpha_threshold must be a float in (0, 1], got {alpha}")

        min_n = pa.get("min_sample_size")
        if not isinstance(min_n, int) or min_n < 1:
            errors.append(f"min_sample_size must be a positive integer, got {min_n}")

    # Check provenance requirements
    prov_reqs = manifest.get("provenance_requirements")
    if not isinstance(prov_reqs, list) or not prov_reqs:
        errors.append("provenance_requirements must be a non-empty array")
    else:
        for p in prov_reqs:
            if p not in CIRCLE_PROVENANCE_VALUES:
                errors.append(f"Invalid provenance in provenance_requirements: '{p}'")

    # Check arrays
    for arr_field in (
        "independent_variables",
        "dependent_variables",
        "control_conditions",
        "sham_conditions",
        "confounders",
        "exclusion_criteria",
        "stopping_rules",
        "expected_measurements",
        "required_sensor_channels",
        "safety_requirements",
    ):
        val = manifest.get(arr_field)
        if not isinstance(val, list):
            errors.append(f"Field '{arr_field}' must be an array")

    # Check boolean
    if not isinstance(manifest.get("requires_human_review"), bool):
        errors.append("Field 'requires_human_review' must be a boolean")

    return errors


def verify_manifest_hash(manifest_obj: Any, expected_sha256: str) -> bool:
    """Verify that a manifest matches its preregistered SHA-256 hash."""
    actual_hash = calculate_sha256(manifest_obj)
    return actual_hash.lower() == expected_sha256.lower()
