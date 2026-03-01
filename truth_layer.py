"""Grounding-first response envelope utilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Evidence:
    source: str
    quote: str
    span_start: int | None = None
    span_end: int | None = None


def build_grounded_response(
    answer: str,
    confidence: float,
    provenance: list[str],
    evidence: list[Evidence],
    repro_steps: list[str],
) -> dict[str, Any]:
    """Build a response object with explicit provenance and grounding checks."""
    bounded_confidence = max(0.0, min(1.0, float(confidence)))
    red_badge = len(evidence) == 0 or len(provenance) == 0
    return {
        "answer": answer,
        "confidence": bounded_confidence,
        "provenance": provenance,
        "evidence": [asdict(e) for e in evidence],
        "repro_steps": repro_steps,
        "grounded": not red_badge,
        "red_badge": red_badge,
    }


def assert_grounded(response: dict[str, Any]) -> None:
    """Raise ValueError if response is not properly grounded."""
    required = ["confidence", "provenance", "evidence", "repro_steps"]
    missing = [k for k in required if k not in response]
    if missing:
        raise ValueError(f"Missing grounding fields: {', '.join(missing)}")
    if not response.get("provenance") or not response.get("evidence"):
        raise ValueError("Ungrounded response: provenance and evidence are required")
