import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rain_lab_chat.doctor as doctor


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_models_endpoint_from_base_url_normalizes_common_forms():
    assert doctor.models_endpoint_from_base_url("127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1/models"
    assert doctor.models_endpoint_from_base_url("http://127.0.0.1:1234") == "http://127.0.0.1:1234/v1/models"
    assert doctor.models_endpoint_from_base_url("http://127.0.0.1:1234/custom") == "http://127.0.0.1:1234/custom/models"


def test_diagnose_lm_studio_reports_loaded_model(monkeypatch):
    assert doctor.requests is not None

    def _fake_get(_url, timeout):  # noqa: ARG001
        return _FakeResponse(200, {"data": [{"id": "good-model"}]})

    monkeypatch.setattr(doctor.requests, "get", _fake_get)
    result = doctor.diagnose_lm_studio("http://127.0.0.1:1234/v1", "good-model", timeout_s=3.0)

    assert result["reachable"] is True
    assert result["model_loaded"] is True
    assert result["ok"] is True
    assert result["loaded_models"] == ["good-model"]


def test_diagnose_lm_studio_suggests_loading_missing_model(monkeypatch):
    assert doctor.requests is not None

    def _fake_get(_url, timeout):  # noqa: ARG001
        return _FakeResponse(200, {"data": [{"id": "different-model"}]})

    monkeypatch.setattr(doctor.requests, "get", _fake_get)
    result = doctor.diagnose_lm_studio("http://127.0.0.1:1234/v1", "wanted-model", timeout_s=3.0)

    assert result["reachable"] is True
    assert result["model_loaded"] is False
    assert result["ok"] is False
    assert any("wanted-model" in action for action in result["actions"])
