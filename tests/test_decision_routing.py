"""Bounded decisions never confer authority or suppress deterministic refusals."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from james_library.judgment.calibration import CalibrationProfile, CalibrationSample
from james_library.judgment.contracts import JudgmentAnswer, JudgmentResult, QuestionType
from james_library.judgment.routing import DecisionRequest, DecisionRouter


def request(**kwargs):
    return replace(DecisionRequest("continue_stop", "A bounded step remains unfinished.", "Choose a next step.",
                                   (("CONTINUE", "Continue analysis."), ("VERIFY", "Verify evidence.")),
                                   consequence="low", remote_allowed=True), **kwargs)


class Provider:
    def __init__(self, engine="laya", *, choice="CONTINUE", probability=.99, error=None):
        self.engine, self.choice, self.probability, self.error = engine, choice, probability, error
        self.calls = 0

    def evaluate(self, state, questions):
        self.calls += 1
        keys = dict(questions.questions[0].choices)
        answer = JudgmentAnswer("next_action", QuestionType.CHOICE, self.choice,
                                tuple((key, self.probability if key == self.choice else 1-self.probability)
                                      for key in keys), self.probability)
        return JudgmentResult(self.engine, self.engine + "-fixture", (answer,), state.state_hash,
                              questions.version, error_code=self.error)


def profile(engine, req=None):
    req = req or request()
    samples = tuple(CalibrationSample(str(i), "CONTINUE", "CONTINUE", .99, .98) for i in range(400))
    return CalibrationProfile(engine, engine + "-fixture", req.decision_class, req.question_hash,
                              .9, .15, .95, samples[:200], samples[200:],
                              (datetime.now(timezone.utc)+timedelta(days=1)).isoformat())


def router(**kwargs):
    defaults = dict(mode="cascade", laya=Provider(), jev=Provider("typesafe"),
                    profiles=(profile("laya"), profile("typesafe")))
    defaults.update(kwargs)
    return DecisionRouter(**defaults)


def allow(req, selected):
    return selected is None or selected in dict(req.choices)


def test_local_fast_path_avoids_jev_and_checks_before_and_after():
    calls = []
    r = router()
    result = r.decide(request(), validator=lambda req, choice: calls.append(choice) is None)
    assert calls == [None, "CONTINUE"]
    assert result.selected == "CONTINUE"
    assert result.validator_result and result.destination == "proposal"
    assert r.laya.calls == 1 and r.jev.calls == 0
    assert result.to_dict()["final_action"] is None


@pytest.mark.parametrize("laya", [None, Provider(error="provider_not_configured"),
                                    Provider(probability=.55), Provider(error="provider_timeout")])
def test_laya_failure_or_uncertainty_escalates_to_jev(laya):
    r = router(laya=laya)
    result = r.decide(request(), validator=allow)
    assert result.destination == "proposal" and result.attempts[-1].engine == "typesafe"
    assert r.jev.calls == 1


@pytest.mark.parametrize("kwargs,reason", [
    ({"laya": None, "jev": None}, "MODEL_UNAVAILABLE"),
    ({"laya": Provider(probability=.55), "jev": Provider("typesafe", probability=.55)}, "LOW_CONFIDENCE"),
    ({"profiles": ()}, "INSUFFICIENT_CALIBRATION"),
])
def test_unresolved_returns_to_rain_without_action(kwargs, reason):
    result = router(**kwargs).decide(request(), validator=allow)
    assert result.destination == "rain" and result.selected is None
    assert result.reason == reason


@pytest.mark.parametrize("kwargs,reason", [
    ({"consequence": "high"}, "HIGH_CONSEQUENCE"),
    ({"requires_evidence": True}, "EVIDENCE_REQUIRED"),
    ({"requires_review": True}, "POLICY_REQUIRES_REVIEW"),
    ({"out_of_distribution": True}, "OUT_OF_DISTRIBUTION"),
])
def test_policy_precedes_any_model(kwargs, reason):
    r = router()
    result = r.decide(request(**kwargs), validator=allow)
    assert result.reason == reason
    assert r.laya.calls == r.jev.calls == 0


def test_high_confidence_cannot_override_post_validation():
    r = router()
    result = r.decide(request(), validator=lambda req, choice: choice is None)
    assert result.selected is None and result.destination == "rejected"
    assert result.reason == "VALIDATION_FAILED"
    assert result.attempts[0].confidence == .99


def test_precheck_refusal_does_not_construct_model_result():
    r = router()
    result = r.decide(request(), validator=lambda *args: False)
    assert result.attempts == () and r.laya.calls == r.jev.calls == 0


def test_validator_exception_and_truthy_nonboolean_fail_closed():
    assert router().decide(request(), validator=lambda *args: "yes").destination == "rejected"
    def broken(*args):
        raise RuntimeError("private detail")
    assert router().decide(request(), validator=broken).destination == "rejected"


def test_disagreement_is_not_a_confidence_contest():
    r = router(compare=True, jev=Provider("typesafe", choice="VERIFY", probability=.95))
    result = r.decide(request(), validator=allow)
    assert result.reason == "ENGINE_DISAGREEMENT" and result.selected is None
    assert [a.selected for a in result.attempts] == ["CONTINUE", "VERIFY"]


def test_comparison_requires_both_engines_available_and_calibrated():
    result = router(compare=True, jev=None).decide(request(), validator=allow)
    assert result.destination == "rain"
    result = router(compare=True, profiles=(profile("typesafe"),)).decide(request(), validator=allow)
    assert result.destination == "rain" and result.reason == "INSUFFICIENT_CALIBRATION"


def test_no_remote_request_without_explicit_request_consent():
    r = router(laya=None)
    result = r.decide(request(remote_allowed=False), validator=allow)
    assert result.reason == "POLICY_REQUIRES_REVIEW" and r.jev.calls == 0


@pytest.mark.parametrize("mode", ["jev", "laya", "off"])
def test_modes_are_selective(mode):
    r = router(mode=mode)
    result = r.decide(request(), validator=allow)
    assert r.laya.calls == (1 if mode == "laya" else 0)
    assert r.jev.calls == (1 if mode == "jev" else 0)
    assert result.destination == ("rain" if mode == "off" else "proposal")


def test_deterministic_resolution_skips_models_but_not_policy_or_validator():
    r = router()
    result = r.decide(request(deterministic_choice="VERIFY"), validator=allow)
    assert result.selected == "VERIFY" and not result.attempts
    assert r.laya.calls == r.jev.calls == 0
    result = r.decide(request(deterministic_choice="VERIFY", consequence="high"), validator=allow)
    assert result.reason == "HIGH_CONSEQUENCE"


def test_question_or_model_drift_and_expiry_abstain():
    r = router(mode="laya")
    assert r.decide(request(instructions="Changed semantics"), validator=allow).reason == "INSUFFICIENT_CALIBRATION"
    r.profiles = (replace(profile("laya"), model="different-model"),)
    assert r.decide(request(), validator=allow).reason == "INSUFFICIENT_CALIBRATION"
    r.profiles = (replace(profile("laya"), expires_at="2020-01-01T00:00:00+00:00"),)
    assert r.decide(request(), validator=allow).reason == "INSUFFICIENT_CALIBRATION"


def test_small_margin_escalates_even_with_high_top_probability():
    r = router(mode="laya", laya=Provider(probability=.91), profiles=(replace(profile("laya"), margin=.9),))
    assert r.decide(request(), validator=allow).reason == "MARGIN_TOO_SMALL"


def test_timed_out_provider_is_bounded_to_one_inflight_call():
    entered, release = Event(), Event()
    class Slow(Provider):
        def evaluate(self, state, questions):
            self.calls += 1
            entered.set()
            release.wait(2)
            return None
    slow = Slow()
    r = router(mode="laya", laya=slow, timeout=.02)
    try:
        assert r.decide(request(), validator=allow).reason == "TIMEOUT"
        assert entered.is_set()
        assert r.decide(request(), validator=allow).reason == "TIMEOUT"
        assert slow.calls == 1
    finally:
        release.set()


@pytest.mark.parametrize("mutation", [
    lambda r: replace(r, state_hash="wrong"),
    lambda r: replace(r, question_set_version="wrong"),
    lambda r: replace(r, provider="typesafe"),
    lambda r: replace(r, model="private details with spaces"),
    lambda r: replace(r, answers=(replace(r.answers[0], value="OUTSIDE"),)),
    lambda r: replace(r, answers=(replace(r.answers[0], probabilities=(("CONTINUE", float("nan")),)),)),
    lambda r: {"selected": "CONTINUE"},
])
def test_malformed_results_are_rejected(mutation):
    class Bad(Provider):
        def evaluate(self, state, questions):
            return mutation(super().evaluate(state, questions))
    result = router(mode="laya", laya=Bad()).decide(request(), validator=allow)
    assert result.reason == "INVALID_OUTPUT" and not result.selected


def test_secrets_never_reach_providers_or_artifacts(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-secret-value")
    r = router()
    result = r.decide(request(state="fixture-secret-value"), validator=allow)
    assert result.reason == "SENSITIVE_INPUT" and not result.attempts
    assert "fixture-secret-value" not in str(result.to_dict())


@pytest.mark.parametrize("kwargs", [{"consequence": "unknown"}, {"remote_allowed": "false"},
                                    {"choices": (("A", "a"), ("A", "b"))}, {"state": "x"*24001}])
def test_invalid_requests_fail_before_inference(kwargs):
    with pytest.raises(ValueError):
        request(**kwargs)
