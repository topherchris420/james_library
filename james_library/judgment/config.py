"""Explicit routing configuration; defaults do not construct either provider."""

import os
import sys

from .calibration import load_profiles
from .routing import DecisionRouter


def enabled(name):
    value = os.getenv(name, "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def create_decision_router():
    mode = os.getenv("RAIN_DECISION_MODE", "off").strip().lower()
    if mode == "off":
        return DecisionRouter()
    if mode not in {"laya", "jev", "cascade"}:
        raise ValueError("unsupported decision mode")
    timeout = float(os.getenv("RAIN_DECISION_TIMEOUT", "30"))
    minimum = int(os.getenv("RAIN_DECISION_MINIMUM_SAMPLES", "100"))
    profiles = load_profiles(os.getenv("RAIN_DECISION_CALIBRATION", ""))
    laya = jev = None
    if mode in {"laya", "cascade"}:
        from .laya import LayaJudgmentProvider
        laya = LayaJudgmentProvider(os.getenv("RAIN_LAYA_CHECKPOINT", ""),
                                    device=os.getenv("RAIN_LAYA_DEVICE", "cpu"), timeout=timeout,
                                    python=os.getenv("RAIN_LAYA_PYTHON", sys.executable))
    if mode in {"jev", "cascade"}:
        from .typesafe import TypeSafeJudgmentProvider
        jev = TypeSafeJudgmentProvider(os.getenv("TYPESAFE_API_KEY"), os.getenv("TYPESAFE_MODEL", "jev-latest"))
    return DecisionRouter(mode=mode, laya=laya, jev=jev, profiles=profiles,
                          minimum_samples=minimum, timeout=timeout, compare=enabled("RAIN_DECISION_COMPARE"))
