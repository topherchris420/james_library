import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
RLM_PATH = REPO_ROOT / "rlm-main" / "rlm-main"

if str(RLM_PATH) not in sys.path:
    sys.path.insert(0, str(RLM_PATH))

import rlm


class _FakeHTTPResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False


def test_local_environment_executes_setup_code_and_python_blocks(monkeypatch):
    request_payloads: list[dict] = []
    responses = [json.dumps({"choices": [{"message": {"content": "```python\nprint(tool_ping())\n```"}}]})]

    def _fake_urlopen(req, timeout):  # noqa: ARG001
        request_payloads.append(json.loads(req.data.decode("utf-8")))
        return _FakeHTTPResponse(responses[len(request_payloads) - 1])

    monkeypatch.setattr(rlm.request, "urlopen", _fake_urlopen)
    client = rlm.RLM(
        environment="local",
        environment_kwargs={"setup_code": "def tool_ping():\n    return 'pong'\n"},
    )

    result = client.completion("Run tools")
    assert len(request_payloads) == 1
    assert "Local tool output:" in result.response
    assert "pong" in result.response


def test_local_environment_invalid_setup_code_raises():
    with pytest.raises(RuntimeError, match="setup_code"):
        rlm.RLM(environment="local", environment_kwargs={"setup_code": "def broken(\n"})


def test_local_environment_limits_python_tool_loops(monkeypatch):
    request_payloads: list[dict] = []
    responses = [
        json.dumps({"choices": [{"message": {"content": "```python\nprint('step1')\n```"}}]}),
        json.dumps({"choices": [{"message": {"content": "```python\nprint('step2')\n```"}}]}),
    ]

    def _fake_urlopen(req, timeout):  # noqa: ARG001
        request_payloads.append(json.loads(req.data.decode("utf-8")))
        return _FakeHTTPResponse(responses[len(request_payloads) - 1])

    monkeypatch.setattr(rlm.request, "urlopen", _fake_urlopen)
    client = rlm.RLM(
        environment="local",
        environment_kwargs={
            "setup_code": "pass",
            "local_followup_calls": True,
            "max_local_steps": 2,
        },
    )

    result = client.completion("loop")
    assert result.response == "Local execution step limit reached before a final answer."
    assert len(request_payloads) == 2


def test_local_environment_reports_python_syntax_error_to_model(monkeypatch):
    request_payloads: list[dict] = []
    responses = [
        json.dumps({"choices": [{"message": {"content": "```python\nfor\n```"}}]}),
        json.dumps({"choices": [{"message": {"content": "Recovered after syntax error."}}]}),
    ]

    def _fake_urlopen(req, timeout):  # noqa: ARG001
        request_payloads.append(json.loads(req.data.decode("utf-8")))
        return _FakeHTTPResponse(responses[len(request_payloads) - 1])

    monkeypatch.setattr(rlm.request, "urlopen", _fake_urlopen)
    client = rlm.RLM(
        environment="local",
        environment_kwargs={
            "setup_code": "pass",
            "local_followup_calls": True,
        },
    )

    result = client.completion("syntax")
    assert result.response == "Recovered after syntax error."
    assert len(request_payloads) == 2
    assert "SyntaxError" in request_payloads[1]["messages"][-1]["content"]
