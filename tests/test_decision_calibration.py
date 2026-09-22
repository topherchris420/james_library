"""Calibration is selected on fit data and independently checked on held-out data."""

from dataclasses import asdict, replace
import json

import pytest

from james_library.judgment.calibration import CalibrationSample, fit_profile, load_profiles, metrics
from tests.test_decision_routing import profile, request


def samples(prefix, correct=True, count=200):
    return tuple(CalibrationSample(f"{prefix}-{i}", "CONTINUE", "CONTINUE" if correct else "VERIFY", .99, .98)
                 for i in range(count))


def fit(**overrides):
    args = dict(engine="laya", model="laya-fixture", decision_class="continue_stop",
                question_hash=request().question_hash, fit_samples=samples("fit"), heldout_samples=samples("heldout"))
    args.update(overrides)
    return fit_profile(**args)


def test_fit_profile_validates_independent_data_and_reports_metrics(tmp_path):
    p = fit()
    assert p.supports(100)
    report = p.report()
    assert report["heldout"]["accuracy"] == 1
    assert report["heldout"]["accepted_count"] == 200
    assert report["threshold"] == .99
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([asdict(p)]))
    assert load_profiles(path) == (p,)


def test_heldout_failure_does_not_retune_to_make_it_pass():
    with pytest.raises(ValueError, match="held-out validation"):
        fit(heldout_samples=samples("heldout", correct=False))


def test_small_or_overlapping_datasets_do_not_calibrate():
    with pytest.raises(ValueError, match="insufficient fit"):
        fit(fit_samples=samples("fit", count=10))
    with pytest.raises(ValueError, match="unique and disjoint"):
        fit(heldout_samples=samples("fit"))


def test_changed_model_and_expired_profile_require_new_evidence():
    p = replace(profile("laya"), expires_at="2020-01-01T00:00:00+00:00")
    assert not p.supports(100)


def test_metrics_use_one_vs_rest_denominators_and_separate_abstention():
    rows = (CalibrationSample("a", "A", "B", .9, .8), CalibrationSample("b", "B", "B", .9, .8),
            CalibrationSample("c", "A", "A", .6, .2))
    report = metrics(rows, .8)
    assert report["accuracy"] == .5
    assert report["per_choice"]["B"]["false_positive_rate"] == 1
    assert report["per_choice"]["A"]["false_negative_rate"] == 1
    assert report["abstention_rate"] == pytest.approx(1/3)


@pytest.mark.parametrize("payload", ['[{"engine":"laya","engine":"typesafe"}]', '[NaN]', '{}'])
def test_invalid_calibration_files_fail_closed(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(payload)
    with pytest.raises(ValueError, match="invalid calibration file"):
        load_profiles(path)


def test_calibration_cli_checks_locked_accuracy_and_coverage_drift(tmp_path):
    from james_library.judgment.benchmark import calibration_main
    p = fit()
    identity = {key: getattr(p, key) for key in ("engine", "model", "decision_class", "question_hash")}
    fit_path, heldout_path = tmp_path / "fit.json", tmp_path / "heldout.json"
    fit_path.write_text(json.dumps([{**identity, **asdict(s)} for s in p.fit_samples]))
    heldout_path.write_text(json.dumps([{**identity, **asdict(s)} for s in p.heldout_samples]))
    output = tmp_path / "profiles.json"
    base_args = ["--fit", str(fit_path), "--heldout", str(heldout_path), "--output", str(output)]
    assert calibration_main(base_args) == 0
    check_args = base_args[:-1] + [str(tmp_path / "drift.json"), "--check", str(output)]
    assert calibration_main(check_args) == 0
    # Still 100 correct accepted samples (enough for the Wilson bound), but
    # half the coverage. Re-fitting would conceal this regression.
    rows = [{**identity, **asdict(replace(s, probability=.5, margin=0) if i < 100 else s)}
            for i, s in enumerate(p.heldout_samples)]
    heldout_path.write_text(json.dumps(rows))
    assert calibration_main(check_args) == 1
    assert json.loads((tmp_path / "drift.json").read_text())["coverage_change"] == -.5
