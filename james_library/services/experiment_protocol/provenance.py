"""CIRCLE-native provenance vocabulary and validation rules.

Maintains a strict epistemic boundary across:
1. RAW_MEASURED
2. DERIVED
3. MODEL_INFERRED
4. SIMULATED
5. TEST
6. INTERVENTION
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Provenance(str, Enum):
    """Standard CIRCLE provenance vocabulary."""

    RAW_MEASURED = "RAW_MEASURED"
    DERIVED = "DERIVED"
    MODEL_INFERRED = "MODEL_INFERRED"
    SIMULATED = "SIMULATED"
    TEST = "TEST"
    INTERVENTION = "INTERVENTION"


CIRCLE_PROVENANCE_VALUES = tuple(p.value for p in Provenance)


def validate_provenance(value: str) -> str:
    """Validate that a provenance string belongs to the approved CIRCLE vocabulary."""
    if not isinstance(value, str):
        raise TypeError(f"Provenance must be a string, got {type(value).__name__}")
    if value not in CIRCLE_PROVENANCE_VALUES:
        raise ValueError(
            f"Invalid provenance '{value}'. Must be one of: {', '.join(CIRCLE_PROVENANCE_VALUES)}"
        )
    return value


def enforce_executor_provenance(executor_type: str, emitted_provenance: str) -> None:
    """Enforce that SIMULATED executors cannot emit RAW_MEASURED data.

    Raises:
        ValueError: If a simulated or test executor attempts to emit RAW_MEASURED records.
    """
    validate_provenance(emitted_provenance)
    exec_type = (executor_type or "").upper()

    if exec_type in {"SIMULATED", "SIMULATION", "TEST", "SYNTHETIC"}:
        if emitted_provenance == Provenance.RAW_MEASURED.value:
            raise ValueError(
                f"Epistemic violation: Executor '{executor_type}' cannot emit "
                f"'{Provenance.RAW_MEASURED.value}' records. Simulated data must be "
                f"tagged '{Provenance.SIMULATED.value}' or '{Provenance.TEST.value}'."
            )


def validate_record_provenance_lineage(record: dict[str, Any]) -> None:
    """Validate model lineage or intervention requirements according to CIRCLE schema rules."""
    prov = record.get("provenance")
    if not prov:
        raise ValueError("Record missing required 'provenance' field.")
    validate_provenance(prov)

    if prov == Provenance.MODEL_INFERRED.value:
        for field in ("source_stream_ids", "source_sequence_ranges", "model"):
            if field not in record:
                raise ValueError(
                    f"Provenance 'MODEL_INFERRED' requires field '{field}' for lineage audit."
                )

    if prov == Provenance.INTERVENTION.value:
        for field in ("decision_id", "actuation_evidence_ids"):
            if field not in record:
                raise ValueError(
                    f"Provenance 'INTERVENTION' requires field '{field}' for decision audit."
                )
