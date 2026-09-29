"""Descriptive statistics only. No inferential test is computed here.

Significance tests need assumptions (independence, distribution, a
pre-registered test) that a generic registry cannot check, so none is
offered. Small samples are labelled rather than dressed up.
"""

from __future__ import annotations

import statistics
from typing import Any

# Below this many observations the summary is labelled descriptive-only.
SMALL_SAMPLE = 10


def summarize(values: list[float]) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None,
                "stdev": None, "variance": None, "note": "no observations"}
    spread = n >= 2
    note = None
    if n < 2:
        note = "single observation: spread undefined"
    elif n < SMALL_SAMPLE:
        note = f"n={n} < {SMALL_SAMPLE}: descriptive only, too small for inference"
    return {
        "n": n,
        "mean": _round(statistics.fmean(values)),
        "median": _round(statistics.median(values)),
        "min": _round(min(values)),
        "max": _round(max(values)),
        "stdev": _round(statistics.stdev(values)) if spread else None,
        "variance": _round(statistics.variance(values)) if spread else None,
        "note": note,
    }


def percent_change(before: float | None, after: float | None) -> float | None:
    """Relative change in percent; undefined (None) when the baseline is zero or missing."""
    if before is None or after is None or before == 0:
        return None
    return _round((after - before) / abs(before) * 100.0)


def _round(value: float) -> float:
    # Fixed precision keeps records and RESULTS.md byte-stable across platforms.
    return round(float(value), 9)
