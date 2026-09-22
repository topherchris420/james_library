"""The documented HTTP contract is exercised using an injected offline transport."""

import json

import pytest
import requests

from james_library.judgment import (
    DEFAULT_QUESTION_SET, ClaimEvidence, GateDisposition, JudgmentService,
    TypeSafeJudgmentProvider, ValidationStatus, build_state,
)


def response_payload():
    return {"model": "jev-1", "answers": {
        "claim_support": {"type": "choice", "choice": "supported", "confidence": .91,
                          "probabilities": {"supported": .91, "mixed": .03,
                                            "unsupported": .03, "insufficient_evidence": .03}},
        "evidence_quality": {"type": "score", "score": 2.5, "confidence": .86,
                             "legend": {str(i): text for i, text in enumerate(
                                 DEFAULT_QUESTION_SET.to_dict()["evidence_quality"]["criteria"])},
                             "probabilities": {"0": .02, "1": .03, "2": .4, "3": .55}},
        "contradiction_present": {"type": "noul", "noul": .08},
        "scope_violation": {"type": "noul", "noul": .13},
        "human_review": {"type": "noul", "noul": .09},
    }, "usage": {"input_tokens": 100, "output_tokens": 25}}


class Response:
    def __init__(self, payload=None, status=200, raw=None):
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(payload or response_payload()).encode()

    def iter_content(self, chunk_size):
        yield self.raw

    def close(self):
        pass


class Transport:
    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def evaluate(transport):
    provider = TypeSafeJudgmentProvider("fixture-credential", transport=transport)
    return provider.evaluate(build_state(ClaimEvidence(claim="Bounded claim")), DEFAULT_QUESTION_SET)


def test_documented_request_and_typed_response_without_invented_noul_confidence():
    transport = Transport()
    result = evaluate(transport)
    assert result.error_code is None
    assert result.model == "jev-1"
    assert result.answers[1].value == 2.5
    assert result.answers[2].confidence is None
    assert result.answers[2].probabilities == ()
    url, request = transport.calls[0]
    assert url == "https://api.typesafe.ai/v1/systemone"
    assert request["json"]["model"] == "jev-latest"
    assert request["json"]["questions"] == DEFAULT_QUESTION_SET.to_dict()
    assert request["allow_redirects"] is False
    assert request["timeout"] == (5, 10)
    assert request["verify"] is True
    assert request["stream"] is True


@pytest.mark.parametrize("mutation", [
    lambda p: p["answers"].pop("human_review"),
    lambda p: p["answers"]["claim_support"].update(choice="invented"),
    lambda p: p["answers"]["claim_support"].pop("confidence"),
    lambda p: p["answers"]["evidence_quality"].update(score=True),
    lambda p: p["answers"]["evidence_quality"].update(score=float("nan")),
    lambda p: p["answers"]["evidence_quality"].update(legend={"0": "wrong"}),
    lambda p: p["answers"]["human_review"].update(noul=1.2),
    lambda p: p["answers"]["human_review"].update(type="choice"),
    lambda p: p["answers"]["claim_support"].update(probabilities={"supported": 1}),
    lambda p: p["answers"]["claim_support"]["probabilities"].update(supported=.2),
    lambda p: p["answers"]["claim_support"].update(
        choice="supported",
        probabilities={
            "supported": .01,
            "mixed": .01,
            "unsupported": .97,
            "insufficient_evidence": .01,
        },
    ),
    lambda p: p["answers"]["evidence_quality"].update(
        score=3.0,
        probabilities={"0": 1.0, "1": 0.0, "2": 0.0, "3": 0.0},
    ),
])
def test_malformed_response_is_rejected(mutation):
    payload = response_payload()
    mutation(payload)
    assert evaluate(Transport(Response(payload))).error_code == "provider_malformed_response"


@pytest.mark.parametrize("error,code", [
    (requests.Timeout("fixture-credential private content"), "provider_timeout"),
    (requests.ConnectionError("fixture-credential private content"), "provider_transport_error"),
])
def test_transport_errors_are_categorical_and_never_leak(error, code):
    result = evaluate(Transport(error=error))
    assert result.error_code == code
    assert "fixture-credential" not in repr(result)
    assert "private content" not in repr(result)


@pytest.mark.parametrize("status,code", [(401, "provider_authentication_error"),
                                         (403, "provider_authentication_error"),
                                         (429, "provider_rate_limited"),
                                         (529, "provider_overloaded"),
                                         (500, "provider_http_error"),
                                         (302, "provider_http_error")])
def test_http_failures_do_not_persist_response_body(status, code):
    result = evaluate(Transport(Response(status=status, raw=b"fixture-credential private content")))
    assert result.error_code == code
    assert result.error_status == status
    assert "fixture-credential" not in repr(result)


def test_bounded_response_and_invalid_json_rejected():
    assert evaluate(Transport(Response(raw=b"x" * 100001))).error_code == "provider_response_too_large"
    assert evaluate(Transport(Response(raw=b"not JSON"))).error_code == "provider_malformed_response"


def test_total_response_deadline_is_enforced(monkeypatch):
    import james_library.judgment.typesafe as typesafe_module

    ticks = iter((0.0, 31.0))
    monkeypatch.setattr(typesafe_module, "monotonic", lambda: next(ticks))
    assert evaluate(Transport()).error_code == "provider_timeout"


def test_duplicate_response_keys_are_rejected():
    raw = b'{"model":"jev-1","model":"jev-2","answers":{},"usage":{"input_tokens":0,"output_tokens":0}}'
    assert evaluate(Transport(Response(raw=raw))).error_code == "provider_malformed_response"


def test_configured_secret_in_state_never_sent_or_recorded():
    transport = Transport()
    provider = TypeSafeJudgmentProvider("fixture-credential", transport=transport)
    envelope = JudgmentService(provider).evaluate(ClaimEvidence(claim="fixture-credential"))
    assert envelope.decision.disposition == GateDisposition.UNAVAILABLE
    assert envelope.result.error_code == "state_contains_secret"
    assert transport.calls == []
    assert "fixture-credential" not in json.dumps(envelope.to_dict())
    assert "fixture-credential" not in repr(provider)


def test_secret_echoed_in_response_model_never_persisted():
    payload = response_payload()
    payload["model"] = "fixture-credential"
    assert evaluate(Transport(Response(payload))).error_code == "provider_malformed_response"


def test_secret_misconfigured_as_model_is_never_sent_or_persisted():
    transport = Transport()
    provider = TypeSafeJudgmentProvider(
        "fixture-credential",
        model="fixture-credential",
        transport=transport,
    )
    envelope = JudgmentService(provider).evaluate(ClaimEvidence(
        claim="Bounded claim",
        observations="Measured observation",
        tool_evidence="fixture run",
        source_identifiers=("fixture",),
        formal_status=ValidationStatus.PASSED,
        numerical_status=ValidationStatus.PASSED,
    ))
    assert envelope.decision.disposition == GateDisposition.UNAVAILABLE
    assert envelope.result.error_code == "state_contains_secret"
    assert transport.calls == []
    assert "fixture-credential" not in json.dumps(envelope.to_dict())
    assert envelope.state.state_hash == __import__("hashlib").sha256(
        envelope.state.canonical_text.encode("utf-8")
    ).hexdigest()


def test_other_configured_secret_misconfigured_as_model_is_blocked(monkeypatch):
    model_secret = "sk-fixture-openai-model-secret-123456"
    monkeypatch.setenv("OPENAI_API_KEY", model_secret)
    transport = Transport()
    provider = TypeSafeJudgmentProvider(
        "different-typesafe-key",
        model=model_secret,
        transport=transport,
    )
    envelope = JudgmentService(provider).evaluate(ClaimEvidence(claim="Bounded claim"))
    assert envelope.result.error_code == "state_contains_secret"
    assert transport.calls == []
    assert model_secret not in json.dumps(envelope.to_dict())


def test_missing_key_does_not_echo_sensitive_model_from_direct_provider():
    secret = "sk-fixture-model-not-real-123456789"
    provider = TypeSafeJudgmentProvider(None, model=secret)
    result = provider.evaluate(build_state(ClaimEvidence(claim="Bounded claim")), DEFAULT_QUESTION_SET)
    assert result.error_code == "state_contains_secret"
    assert secret not in repr(result)
