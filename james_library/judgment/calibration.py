"""Held-out threshold fitting for bounded Choice decisions; no model calls."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import sqrt
from pathlib import Path
import re

from .contracts import bounded_number


def digest_json(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path, limit=2_000_000):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON input too large")
    return json.loads(raw, object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


@dataclass(frozen=True)
class CalibrationSample:
    sample_id: str
    expected: str
    selected: str
    probability: float
    margin: float

    def __post_init__(self):
        if (not all(isinstance(v, str) and v for v in (self.sample_id, self.expected, self.selected))
                or not bounded_number(self.probability, 0, 1) or not bounded_number(self.margin, 0, 1)):
            raise ValueError("invalid calibration sample")


def metrics(samples, threshold=0.0, margin=0.0):
    accepted = [s for s in samples if s.probability >= threshold and s.margin >= margin]
    accuracy = sum(s.selected == s.expected for s in accepted) / len(accepted) if accepted else None
    ece = 0.0
    for index in range(10):
        bucket = [s for s in samples if min(9, int(s.probability * 10)) == index]
        if bucket:
            correct = sum(s.selected == s.expected for s in bucket) / len(bucket)
            confidence = sum(s.probability for s in bucket) / len(bucket)
            ece += len(bucket) / len(samples) * abs(correct - confidence)
    per_choice = {}
    for label in sorted({s.expected for s in samples} | {s.selected for s in samples}):
        negatives = [s for s in accepted if s.expected != label]
        positives = [s for s in accepted if s.expected == label]
        per_choice[label] = {
            "false_positive_rate": sum(s.selected == label for s in negatives) / len(negatives) if negatives else None,
            "false_negative_rate": sum(s.selected != label for s in positives) / len(positives) if positives else None,
        }
    return {"sample_count": len(samples), "accepted_count": len(accepted), "accuracy": accuracy,
            "abstention_rate": 1 - len(accepted) / len(samples) if samples else None,
            "escalation_rate": 1 - len(accepted) / len(samples) if samples else None,
            "calibration_error": ece if samples else None, "per_choice": per_choice}


def wilson_lower(correct, count):
    if not count:
        return 0.0
    p, z = correct / count, 1.96
    return (p + z*z/(2*count) - z*sqrt(p*(1-p)/count + z*z/(4*count*count))) / (1 + z*z/count)


@dataclass(frozen=True)
class CalibrationProfile:
    engine: str
    model: str
    decision_class: str
    question_hash: str
    threshold: float
    margin: float
    target_accuracy: float
    fit_samples: tuple[CalibrationSample, ...]
    heldout_samples: tuple[CalibrationSample, ...]
    expires_at: str
    schema_version: str = "rain-decision-calibration/v1"

    def __post_init__(self):
        if self.schema_version != "rain-decision-calibration/v1":
            raise ValueError("unsupported calibration schema")
        if self.engine not in {"laya", "typesafe"}:
            raise ValueError("invalid calibration engine")
        for label in (self.model, self.decision_class):
            if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", label):
                raise ValueError("invalid calibration identity")
        if not re.fullmatch(r"[0-9a-f]{64}", self.question_hash):
            raise ValueError("invalid question hash")
        if not all(bounded_number(v, 0, 1) for v in (self.threshold, self.margin, self.target_accuracy)):
            raise ValueError("invalid calibration threshold")
        if self.target_accuracy < .5:
            raise ValueError("calibration target must be at least 0.5")
        expiry = datetime.fromisoformat(self.expires_at)
        if expiry.tzinfo is None:
            raise ValueError("calibration expiry must have a timezone")
        if not isinstance(self.fit_samples, tuple) or not isinstance(self.heldout_samples, tuple):
            raise ValueError("calibration splits must be immutable tuples")
        samples = self.fit_samples + self.heldout_samples
        if not all(isinstance(s, CalibrationSample) for s in samples):
            raise ValueError("invalid calibration samples")
        if len({s.sample_id for s in samples}) != len(samples):
            raise ValueError("fit and held-out sample IDs must be unique and disjoint")

    @property
    def profile_id(self):
        return digest_json(asdict(self))

    def supports(self, minimum, now=None):
        now = now or datetime.now(timezone.utc)
        if now >= datetime.fromisoformat(self.expires_at):
            return False
        for samples in (self.fit_samples, self.heldout_samples):
            accepted = [s for s in samples if s.probability >= self.threshold and s.margin >= self.margin]
            if len(accepted) < minimum:
                return False
            if wilson_lower(sum(s.selected == s.expected for s in accepted), len(accepted)) < self.target_accuracy:
                return False
        return True

    def report(self):
        return {"profile_id": self.profile_id, "engine": self.engine, "model": self.model,
                "decision_class": self.decision_class, "question_hash": self.question_hash,
                "threshold": self.threshold, "margin": self.margin, "target_accuracy": self.target_accuracy,
                "expires_at": self.expires_at,
                "fit": metrics(self.fit_samples, self.threshold, self.margin),
                "heldout": metrics(self.heldout_samples, self.threshold, self.margin)}

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        for key in ("fit_samples", "heldout_samples"):
            value[key] = tuple(CalibrationSample(**sample) for sample in value[key])
        return cls(**value)


def fit_profile(*, engine, model, decision_class, question_hash, fit_samples, heldout_samples,
                target_accuracy=.95, minimum_samples=100, validity_days=30):
    """Choose on fit only; held-out failures never trigger threshold retuning."""
    if type(minimum_samples) is not int or minimum_samples < 1 or not 1 <= validity_days <= 365:
        raise ValueError("invalid calibration sample/validity policy")
    candidates = []
    for threshold in sorted({s.probability for s in fit_samples}):
        for margin in sorted({0.0} | {s.margin for s in fit_samples}):
            kept = [s for s in fit_samples if s.probability >= threshold and s.margin >= margin]
            if len(kept) >= minimum_samples and wilson_lower(
                sum(s.selected == s.expected for s in kept), len(kept)
            ) >= target_accuracy:
                candidates.append((len(kept), -threshold, -margin))
    if not candidates:
        raise ValueError("insufficient fit evidence")
    _, neg_threshold, neg_margin = max(candidates)
    profile = CalibrationProfile(
        engine, model, decision_class, question_hash, -neg_threshold, -neg_margin, target_accuracy,
        tuple(fit_samples), tuple(heldout_samples),
        (datetime.now(timezone.utc) + timedelta(days=validity_days)).isoformat(),
    )
    if not profile.supports(minimum_samples):
        raise ValueError("held-out validation failed; collect new evidence")
    return profile


def load_profiles(path):
    if not path:
        return ()
    try:
        payload = read_json(path)
        if not isinstance(payload, list) or len(payload) > 100:
            raise ValueError
        profiles = tuple(CalibrationProfile.from_dict(item) for item in payload)
        keys = [(p.engine, p.model, p.decision_class, p.question_hash) for p in profiles]
        if len(set(keys)) != len(keys):
            raise ValueError
        return profiles
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError("invalid calibration file") from exc
