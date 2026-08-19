"""CIRCLE Execution Adapters.

Enforces execution safety boundaries:
- V1 provides ONLY SimulatedCircleExecutor.
- Provenance is strictly 'SIMULATED'.
- PhysicalCircleExecutor is a disabled stub enforcing ENGINEERING REVIEW ONLY.
"""

from __future__ import annotations

import abc
import hashlib
import json
import math
import random
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import calculate_sha256, canonical_json_str, generate_execution_id, validate_manifest
from .provenance import Provenance, enforce_executor_provenance


def compute_crc32c_hex(data: bytes | str) -> str:
    """Compute 8-character uppercase hex CRC32 checksum (used in CIRCLE session records)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    # Standard Python zlib.crc32 gives an unsigned 32-bit integer
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return f"{crc:08X}"


class CircleExperimentExecutor(abc.ABC):
    """Abstract interface for CIRCLE experiment execution."""

    @abc.abstractmethod
    def prepare_experiment(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Validate manifest and initialize execution environment."""
        pass

    @abc.abstractmethod
    def run_trial(
        self,
        manifest: dict[str, Any],
        manifest_sha256: str,
        artifacts_dir: Path | None = None,
        custom_scenario: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a single trial and return an ExperimentResult record."""
        pass


class PhysicalCircleExecutor(CircleExperimentExecutor):
    """Physical CIRCLE Hardware Executor.

    SAFETY GATE: Prohibited in V1. Physical hardware is for ENGINEERING REVIEW ONLY.
    """

    def prepare_experiment(self, manifest: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(
            "SAFETY INTERLOCK: Physical hardware execution is DISABLED in V1. "
            "CIRCLE hardware remains ENGINEERING REVIEW ONLY (not for fabrication or human connection)."
        )

    def run_trial(
        self,
        manifest: dict[str, Any],
        manifest_sha256: str,
        artifacts_dir: Path | None = None,
        custom_scenario: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise RuntimeError(
            "SAFETY INTERLOCK: Physical hardware execution is DISABLED in V1. "
            "No powered electrodes, no human connection."
        )


class SimulatedCircleExecutor(CircleExperimentExecutor):
    """Simulated CIRCLE adapter emitting deterministic synthetic records with provenance='SIMULATED'."""

    def __init__(self, seed: int | None = 42) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.executor_type = "SIMULATED"

    def prepare_experiment(self, manifest: dict[str, Any]) -> dict[str, Any]:
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError(f"Manifest validation failed before execution: {'; '.join(errors)}")
        return {
            "status": "PREPARED",
            "executor": self.executor_type,
            "manifest_experiment_id": manifest["experiment_id"],
        }

    def run_trial(
        self,
        manifest: dict[str, Any],
        manifest_sha256: str,
        artifacts_dir: Path | None = None,
        custom_scenario: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a simulated trial emitting CIRCLE-compatible records and ExperimentResult."""
        scenario = custom_scenario or {}
        # Ensure provenance cannot be spoofed
        emitted_provenance = scenario.get("force_provenance", Provenance.SIMULATED.value)
        enforce_executor_provenance(self.executor_type, emitted_provenance)

        execution_id = generate_execution_id()
        experiment_id = manifest["experiment_id"]
        trial_id = manifest["trial_id"]

        now_utc = datetime.now(timezone.utc).isoformat()
        start_time_us = 1_000_000
        duration_us = scenario.get("duration_us", 5_000_000)
        end_time_us = start_time_us + duration_us

        # Generate CIRCLE session records
        session_id = f"SESS-{manifest['trial_id'][4:]}-01"
        intervention_id = f"INTV-{manifest['trial_id'][4:]}-01"
        decision_id = f"DEC-{manifest['trial_id'][4:]}-01"

        # Generate simulated measurement series
        n_samples = scenario.get("sample_count", 30)
        baseline_mean = scenario.get("baseline_mean", 100.0)
        active_effect = scenario.get("active_effect", 0.0)
        noise_std = scenario.get("noise_std", 2.0)
        phantom_effect = scenario.get("phantom_effect", 0.0)

        # Control and active measurements
        control_series: list[float] = []
        active_series: list[float] = []
        phantom_series: list[float] = []

        # Use seeded RNG for reproducible data points
        for i in range(n_samples):
            ctrl_val = round(self.rng.gauss(baseline_mean, noise_std), 4)
            act_val = round(self.rng.gauss(baseline_mean + active_effect, noise_std), 4)
            phantom_val = round(self.rng.gauss(baseline_mean + phantom_effect, noise_std * 0.5), 4)
            control_series.append(ctrl_val)
            active_series.append(act_val)
            phantom_series.append(phantom_val)

        # Create session record object conforming to session-record.schema.json
        session_header_payload = {
            "schema_version": "1.0.0",
            "record_type": "SESSION_HEADER",
            "provenance": emitted_provenance,
            "device_time_start_us": start_time_us,
            "device_time_end_us": start_time_us + 1000,
            "status_flags": ["SIMULATED_HEADER", "CLOCK_LOCKED"],
            "crc32c": compute_crc32c_hex(f"{session_id}-header"),
        }

        intervention_record = {
            "schema_version": "1.0.0",
            "intervention_id": intervention_id,
            "session_id": session_id,
            "decision_id": decision_id,
            "stimulus_type": "ACOUSTIC_RESONANCE",
            "waveform_parameters": {
                "frequency_hz": manifest.get("intervention_description", {}).get("parameters", {}).get("frequency_hz", 40.0),
                "amplitude_normalized": 0.5,
                "duration_ms": 1000.0,
            },
            "target_channels": manifest.get("required_sensor_channels", ["CH_RESONANCE_0"]),
            "safety_gate_verifications": ["SAFETY_GATE_SIMULATED_VERIFIED"],
            "provenance": emitted_provenance,
            "timestamp_us": start_time_us + 2_000_000,
            "crc32c": compute_crc32c_hex(f"{intervention_id}-intv"),
        }

        # Build raw artifact data
        raw_artifacts = []
        checksums = {}

        data_payload = {
            "session_id": session_id,
            "experiment_id": experiment_id,
            "trial_id": trial_id,
            "execution_id": execution_id,
            "provenance": emitted_provenance,
            "measurements": {
                "control": control_series,
                "active": active_series,
                "phantom": phantom_series,
            },
            "circle_session_header": session_header_payload,
            "circle_intervention": intervention_record,
        }

        data_bytes = canonical_json_str(data_payload).encode("utf-8")
        data_sha256 = hashlib.sha256(data_bytes).hexdigest()

        if artifacts_dir is not None:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            data_file = artifacts_dir / "simulated_measurements.json"
            data_file.write_bytes(data_bytes)
            raw_artifacts.append({
                "path": "simulated_measurements.json",
                "sha256": data_sha256,
                "type": "SIMULATED_TIME_SERIES",
            })
            checksums["simulated_measurements.json"] = data_sha256
        else:
            raw_artifacts.append({
                "path": "memory://simulated_measurements.json",
                "sha256": data_sha256,
                "type": "SIMULATED_TIME_SERIES",
            })
            checksums["memory://simulated_measurements.json"] = data_sha256

        # Check for scenario-injected quality flags or deviations
        quality_flags = ["SIMULATED_DATA_OK"]
        if scenario.get("sensor_failed"):
            quality_flags.append("SENSOR_DROPOUT_DETECTED")
        if scenario.get("sync_failed"):
            quality_flags.append("CLOCK_SYNC_DEGRADED")

        deviations = scenario.get("deviations", [])
        failed_measurements = scenario.get("failed_measurements", [])

        # Build final ExperimentResult
        result: dict[str, Any] = {
            "protocol_version": "1.0.0",
            "experiment_id": experiment_id,
            "trial_id": trial_id,
            "execution_id": execution_id,
            "started_at": now_utc,
            "ended_at": now_utc,
            "executor_type": "SIMULATED",
            "instrument_identity": "CIRCLE-SIMULATOR-V1-VIRTUAL",
            "hardware_revision": "REV_A_SIMULATED",
            "firmware_version": "0.0.0-sim",
            "software_version": "1.0.0",
            "circle_session_references": [session_id],
            "circle_intervention_references": [intervention_id],
            "raw_artifact_references": raw_artifacts,
            "quality_flags": quality_flags,
            "calibration_status": scenario.get("calibration_status", "SIMULATED_IDEAL"),
            "synchronization_status": scenario.get("synchronization_status", "SIMULATED_PERFECT"),
            "environmental_metadata": {
                "temperature_c": 22.5,
                "relative_humidity_pct": 45.0,
                "simulation_noise_floor_uv": 1.2,
            },
            "deviations_from_protocol": deviations,
            "failed_measurements": failed_measurements,
            "manifest_sha256": manifest_sha256,
            "provenance": emitted_provenance,
            "checksums": checksums,
            "_embedded_data": data_payload,  # Transient payload for in-process analysis
        }

        return result
