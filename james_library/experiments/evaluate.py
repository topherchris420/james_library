"""Deterministic evaluation of pre-registered criteria against recorded measurements.

This is the only code path that assigns ``passed``/``failed``/``inconclusive``.
Runners and external producers supply measurements, never a status, and a
model interpretation is never consulted.

Rule (``rain-criteria/v1``), applied in order:

1. Any guard that does not hold, or cannot be evaluated → ``inconclusive``
   (insufficient evidence). A small sample supports no conclusion either way.
2. Any failure criterion that holds → ``failed`` (hypothesis not supported).
   Failure dominates success.
3. Every success criterion holds → ``passed`` (hypothesis supported).
4. Otherwise → ``inconclusive`` (insufficient evidence).
"""

from __future__ import annotations

import math
import operator
from typing import Any

RULE_VERSION = "rain-criteria/v1"

_OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}


def check_criterion(criterion: dict[str, Any], measurements: dict[str, Any]) -> dict[str, Any]:
    observed = measurements.get(criterion["metric"])
    usable = isinstance(observed, (int, float)) and not isinstance(observed, bool) and math.isfinite(observed)
    holds = _OPS[criterion["op"]](observed, criterion["value"]) if usable else None
    return {
        "id": criterion["id"],
        "metric": criterion["metric"],
        "op": criterion["op"],
        "value": criterion["value"],
        "observed": observed if usable else None,
        "holds": holds,
    }


def evaluate(definition: dict[str, Any], measurements: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Return ``(status, hypothesis_verdict, evaluation)`` for completed measurements."""
    criteria = definition["criteria"]
    guards = [check_criterion(c, measurements) for c in criteria["guards"]]
    success = [check_criterion(c, measurements) for c in criteria["success"]]
    failure = [check_criterion(c, measurements) for c in criteria["failure"]]

    unmet_guards = [g["id"] for g in guards if g["holds"] is not True]
    triggered = [f["id"] for f in failure if f["holds"] is True]
    met = [s["id"] for s in success if s["holds"] is True]
    unevaluable = [c["id"] for c in success + failure if c["holds"] is None]

    if unmet_guards:
        status, verdict = "inconclusive", "insufficient_evidence"
        summary = f"Evidence-sufficiency guard(s) not met: {', '.join(unmet_guards)}. No conclusion drawn."
    elif triggered:
        status, verdict = "failed", "not_supported"
        summary = f"Failure criterion triggered: {', '.join(triggered)}. The hypothesis is not supported."
    elif len(met) == len(success):
        status, verdict = "passed", "supported"
        summary = f"All {len(success)} success criteria held and no failure criterion triggered."
    else:
        status, verdict = "inconclusive", "insufficient_evidence"
        missing = [s["id"] for s in success if s["holds"] is not True]
        summary = f"Success criteria not all met ({', '.join(missing)}) and no failure criterion triggered."
        if unevaluable:
            summary += f" Not evaluable (missing measurement): {', '.join(unevaluable)}."

    evaluation = {
        "rule": RULE_VERSION,
        "guards": guards,
        "success": success,
        "failure": failure,
        "summary": summary,
    }
    return status, verdict, evaluation
