"""Small HTTP adapter for https://docs.typesafe.ai/api (System One endpoint)."""

import json
import re

import requests

from .contracts import (
    JudgmentAnswer, JudgmentResult, JudgmentState, QuestionSet, QuestionType, valid_answers,
)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_RESPONSE_BYTES = 100000
SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")
PROVIDER_ERROR_CODES = frozenset({
    "provider_not_configured", "provider_timeout", "provider_transport_error", "provider_authentication_error",
    "provider_rate_limited", "provider_http_error", "provider_response_too_large", "provider_malformed_response",
    "state_contains_secret", "provider_internal_error",
})


class TypeSafeJudgmentProvider:
    def __init__(self, api_key: str | None, model: str = "jev-latest", *, transport=None):
        if not isinstance(model, str) or not SAFE_MODEL.fullmatch(model):
            raise ValueError("invalid judgment model identifier")
        self._api_key = api_key or ""
        self.model = model
        self._transport = transport

    def preflight(self, state: JudgmentState, questions: QuestionSet) -> JudgmentResult | None:
        """Reject configuration or credential exposure before deterministic routing."""
        if not self._api_key:
            return JudgmentResult(
                "typesafe",
                model=self.model,
                state_hash=state.state_hash,
                question_set_version=questions.version,
                error_code="provider_not_configured",
            )
        if self._api_key in state.canonical_text or self._api_key in json.dumps(
            questions.to_dict(), ensure_ascii=False
        ):
            return JudgmentResult(
                "typesafe",
                state_hash=state.state_hash,
                question_set_version=questions.version,
                error_code="state_contains_secret",
            )
        return None

    def evaluate(self, state: JudgmentState, questions: QuestionSet) -> JudgmentResult:
        def failed(code: str, status: int | None = None) -> JudgmentResult:
            return JudgmentResult("typesafe", model=self.model, state_hash=state.state_hash,
                                  question_set_version=questions.version, error_code=code, error_status=status)

        preflight = self.preflight(state, questions)
        if preflight is not None:
            return preflight
        payload = {"state": state.canonical_text, "model": self.model, "questions": questions.to_dict()}
        session = self._transport or requests.Session()
        if self._transport is None:
            # Avoid ambient proxy credentials and netrc overriding the explicit authorization boundary.
            session.trust_env = False
        response = None
        try:
            response = session.post(ENDPOINT, json=payload,
                                    headers={"Authorization": f"Bearer {self._api_key}"},
                                    timeout=(5, 30), allow_redirects=False, stream=True, verify=True)
            status = response.status_code
            if status != 200:
                code = ("provider_authentication_error" if status in (401, 403)
                        else "provider_rate_limited" if status in (429, 529) else "provider_http_error")
                return failed(code, status)
            body = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    return failed("provider_response_too_large")
            if self._api_key.encode() in body:
                return failed("provider_malformed_response")
            return parse_response(json.loads(body), state, questions)
        except requests.Timeout:
            return failed("provider_timeout")
        except requests.RequestException:
            return failed("provider_transport_error")
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return failed("provider_malformed_response")
        finally:
            if response is not None:
                response.close()
            if self._transport is None:
                session.close()


def parse_response(payload: object, state: JudgmentState, questions: QuestionSet) -> JudgmentResult:
    """Copy only documented, validated fields; never retain the raw response."""
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
        raise ValueError("invalid response")
    if not SAFE_MODEL.fullmatch(payload["model"]):
        raise ValueError("invalid model")
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, dict) or set(raw_answers) != {q.question_id for q in questions.questions}:
        raise ValueError("invalid answers")
    usage = payload.get("usage")
    if not isinstance(usage, dict) or any(
        type(usage.get(key)) is not int or usage[key] < 0 for key in ("input_tokens", "output_tokens")
    ):
        raise ValueError("invalid usage")
    answers = []
    for question in questions.questions:
        raw = raw_answers[question.question_id]
        if not isinstance(raw, dict) or raw.get("type") != question.type.value:
            raise ValueError("invalid answer type")
        probabilities = raw.get("probabilities", {})
        if not isinstance(probabilities, dict):
            raise ValueError("invalid probabilities")
        if question.type == QuestionType.SCORE:
            legend = {str(index): text for index, text in enumerate(question.levels)}
            if raw.get("legend") != legend:
                raise ValueError("invalid legend")
        answers.append(JudgmentAnswer(question.question_id, question.type, raw[question.type.value],
                                      tuple(probabilities.items()), raw.get("confidence")))
    result = JudgmentResult("typesafe", payload["model"], tuple(answers), state.state_hash, questions.version)
    if not valid_answers(result, questions):
        raise ValueError("invalid typed answers")
    return result
