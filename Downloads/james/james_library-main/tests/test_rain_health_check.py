import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rain_health_check as hc


def test_models_endpoint_from_base_url_defaults() -> None:
    endpoint = hc._models_endpoint_from_base_url("http://127.0.0.1:1234/v1")
    assert endpoint == "http://127.0.0.1:1234/v1/models"


def test_models_endpoint_from_base_url_existing_models() -> None:
    endpoint = hc._models_endpoint_from_base_url("http://127.0.0.1:1234/v1/models")
    assert endpoint == "http://127.0.0.1:1234/v1/models"


def test_models_endpoint_from_base_url_no_path() -> None:
    endpoint = hc._models_endpoint_from_base_url("http://127.0.0.1:1234")
    assert endpoint == "http://127.0.0.1:1234/v1/models"


def test_extract_model_names() -> None:
    payload = {
        "data": [
            {"id": "qwen2.5-coder-7b"},
            {"id": "gemini-2.5-flash"},
            {"name": "missing-id"},
        ]
    }
    names = hc._extract_model_names(payload)
    assert names == ["qwen2.5-coder-7b", "gemini-2.5-flash"]


def test_extract_recent_launcher_errors(tmp_path: Path) -> None:
    log_path = tmp_path / "launcher_events.jsonl"
    records = [
        {"ts": "2026-02-25T00:00:00Z", "event": "session_started"},
        {"ts": "2026-02-25T00:00:05Z", "event": "launcher_failed", "error": "bridge startup failed"},
        {"ts": "2026-02-25T00:00:10Z", "event": "sidecar_exited", "critical": True, "exit_code": 2},
    ]
    log_path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    errors = hc._extract_recent_launcher_errors(log_path, tail_lines=50, max_errors=5)
    assert len(errors) == 2
    assert errors[0]["event"] == "launcher_failed"
    assert errors[1]["event"] == "sidecar_exited"


def test_check_launcher_log_missing(tmp_path: Path) -> None:
    result = hc._check_launcher_log(tmp_path / "missing.jsonl", tail_lines=100, max_errors=3)
    assert result.status == "warn"
    assert "not found" in result.summary.lower()


def test_overall_status_fail_wins() -> None:
    results = [
        hc.CheckResult(name="a", status="pass", summary="", details={}),
        hc.CheckResult(name="b", status="warn", summary="", details={}),
        hc.CheckResult(name="c", status="fail", summary="", details={}),
    ]
    assert hc._overall_status(results) == "fail"
