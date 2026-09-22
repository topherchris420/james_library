"""Local Laya wire normalization, offline boundaries, and capacity refusal."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from james_library.judgment import DEFAULT_QUESTION_SET, build_state
from james_library.judgment.laya import LayaJudgmentProvider, parse_laya_response
from james_library.judgment import laya_worker
from tests.judgment_helpers import evidence
from tests.test_typesafe_judgment import response_payload


def prediction():
    payload = response_payload()
    for key in ("contradiction_present", "scope_violation", "human_review"):
        payload["answers"][key]["confidence"] = .95
        payload["answers"][key]["action"] = {"act_probability": .99}
    return {"fingerprint": "laya-" + "a"*64, "prediction": payload}


def test_same_contract_and_no_invented_noul_confidence():
    result = parse_laya_response(prediction(), build_state(evidence()), DEFAULT_QUESTION_SET)
    assert result.provider == "laya" and result.model == "laya-" + "a"*64
    assert result.answers[2].confidence is None
    assert result.answers[2].probabilities == ()


def test_local_inference_subprocess_has_offline_environment_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-secret")
    monkeypatch.setenv("HF_TOKEN", "fixture-hf-secret")
    monkeypatch.setenv("HTTP_PROXY", "https://example.com")
    def run(command, **kwargs):
        assert "laya_worker.py" in command[1]
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        assert kwargs["env"]["HF_HUB_DISABLE_TELEMETRY"] == "1"
        assert not {"TYPESAFE_API_KEY", "HF_TOKEN", "HTTP_PROXY", "PYTHONPATH"} & kwargs["env"].keys()
        assert json.loads(kwargs["input"])["checkpoint"] == str(tmp_path)
        return SimpleNamespace(returncode=0, stdout=json.dumps(prediction()))
    monkeypatch.setattr(subprocess, "run", run)
    result = LayaJudgmentProvider(str(tmp_path)).evaluate(build_state(evidence()), DEFAULT_QUESTION_SET)
    assert result.error_code is None


def test_missing_checkpoint_never_launches_process_or_downloads(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("launched"))
    result = LayaJudgmentProvider("convaiinnovations/laya").evaluate(build_state(evidence()), DEFAULT_QUESTION_SET)
    assert result.error_code == "provider_not_configured"


def test_worker_without_checkpoint_or_optional_dependencies_is_categorical(tmp_path):
    result = LayaJudgmentProvider(str(tmp_path)).evaluate(build_state(evidence()), DEFAULT_QUESTION_SET)
    assert result.error_code == "provider_not_configured"


def test_timeout_returns_failure_not_partial_prediction(tmp_path, monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 1)
    monkeypatch.setattr(subprocess, "run", run)
    result = LayaJudgmentProvider(str(tmp_path)).evaluate(build_state(evidence()), DEFAULT_QUESTION_SET)
    assert result.error_code == "provider_timeout"


def test_fingerprint_changes_with_weights_and_runtime(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"weights-a")
    (tmp_path / "rl_agent_config.json").write_text("{}")
    first = laya_worker.checkpoint_fingerprint(tmp_path, "runtime-a")
    (tmp_path / "model.safetensors").write_bytes(b"weights-b")
    assert first != laya_worker.checkpoint_fingerprint(tmp_path, "runtime-a")
    assert first != laya_worker.checkpoint_fingerprint(tmp_path, "runtime-b")


def test_capacity_guard_rejects_state_and_option_truncation(monkeypatch):
    class Tokenizer:
        mask_token = "[MASK]"
        def __call__(self, text, **kwargs):
            return {"input_ids": text.split()}
    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "laya.common", SimpleNamespace(render_options=lambda q: q["opts"]))
    agent = SimpleNamespace(tok=Tokenizer(), cfg={"max_len": 32, "head_max_len": 24},
                            _to_internal=lambda q: q)
    q = {"next": {"t": "choice", "ins": "Pick one", "opts": ["one", "two"]}}
    laya_worker.check_capacity(agent, "short state", q)
    with pytest.raises(laya_worker.InputTooLarge):
        laya_worker.check_capacity(agent, "long "*40, q)
    q["next"]["opts"] = ["long "*49, "two"]
    with pytest.raises(laya_worker.InputTooLarge):
        laya_worker.check_capacity(agent, "short state", q)


def test_worker_blocks_network_before_loading_local_model(tmp_path, monkeypatch):
    # Isolated child proves network blocking without altering the test process.
    for name in ("rl_agent_config.json", "model.safetensors", "tokenizer/tokenizer_config.json",
                 "tokenizer/tokenizer.json", "encoder/config.json"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("{}")
    script = '''
import importlib.metadata, socket, sys, types
from james_library.judgment.laya_worker import run
importlib.metadata.version = lambda name: "0.3.5"
def load(*a, **k):
    try:
        socket.create_connection(("example.com", 443))
    except OSError as e:
        assert str(e) == "offline inference"
        raise FileNotFoundError("fixture stops before real inference")
    raise AssertionError("network not blocked")
sys.modules["laya"] = types.SimpleNamespace(load=load)
sys.modules["torch"] = types.SimpleNamespace()
try:
    run({"checkpoint": sys.argv[1], "device":"cpu"})
except FileNotFoundError:
    print("offline verified")
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert "offline verified" in result.stdout


def test_no_optional_ml_imports_in_host():
    script = "import sys; from james_library.judgment.laya import LayaJudgmentProvider; " \
             "assert not {'torch', 'transformers', 'laya'} & sys.modules.keys()"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
