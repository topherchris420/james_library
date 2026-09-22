"""Private subprocess entrypoint. Only this process loads optional ML dependencies."""

import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import sys


class InputTooLarge(ValueError):
    pass


def checkpoint_fingerprint(root: Path, runtime: str) -> str:
    digest = hashlib.sha256(runtime.encode())
    files = [root / "rl_agent_config.json", root / "model.safetensors"]
    for directory in ("tokenizer", "encoder"):
        files.extend(sorted((root / directory).rglob("*")))
    for path in files:
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return "laya-" + digest.hexdigest()


def check_capacity(agent, state, questions):
    """Reject any upstream head, option, or state truncation before prediction."""
    from laya.common import render_options
    tok = agent.tok
    state_count = len(tok(state, add_special_tokens=False)["input_ids"])
    for definition in questions.values():
        q = agent._to_internal(definition)
        instructions = str(q["ins"]).replace(tok.mask_token, " ")
        head = len(tok(f'{q["t"]} question: {instructions}', add_special_tokens=False)["input_ids"])
        options = [len(tok(" " + text.replace(tok.mask_token, " "),
                           add_special_tokens=False)["input_ids"]) for text in render_options(q)]
        option_total = sum(size + 1 for size in options)
        budget = agent.cfg.get("head_max_len", 192) - option_total
        if (any(size > 48 for size in options) or budget < 16 or head > max(8, budget)
                or head + option_total + state_count + 4 > agent.cfg.get("max_len", 512)):
            raise InputTooLarge


def run(payload):
    root = Path(payload["checkpoint"])
    required = ("rl_agent_config.json", "model.safetensors", "tokenizer/tokenizer_config.json",
                "tokenizer/tokenizer.json", "encoder/config.json")
    if not root.is_absolute() or not all((root / name).is_file() for name in required):
        return {"error": "provider_not_configured"}
    # Do not rely exclusively on HF environment flags: block Python network
    # connections in this dedicated worker before importing the inference stack.
    def no_network(*args, **kwargs):
        raise OSError("offline inference")
    socket.create_connection = no_network
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        os.environ[key] = "1"
    if importlib.metadata.version("laya") != "0.3.5":
        return {"error": "provider_runtime_unsupported"}
    import laya
    import torch
    device = payload["device"]
    if device == "cuda" and not torch.cuda.is_available():
        return {"error": "provider_not_configured"}
    if device == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
        return {"error": "provider_not_configured"}
    runtime = "/".join(importlib.metadata.version(name) for name in ("laya", "torch", "transformers"))
    agent = laya.load(str(root), device=device)
    check_capacity(agent, payload["state"], payload["questions"])
    prediction = agent.predict(payload["state"], payload["questions"])
    # Upstream may repair tokenizer metadata or fall back from GPU to CPU.
    # Bind calibration to the actual loaded files, runtime, and actual device.
    fingerprint = checkpoint_fingerprint(root, runtime + "/" + str(agent.device))
    return {"fingerprint": fingerprint, "prediction": prediction}


def main():
    try:
        raw = sys.stdin.read(100_001)
        if len(raw) > 100_000:
            raise InputTooLarge
        payload = json.loads(raw)
        # Suppress third-party banners and exception payloads, not just host logs.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = run(payload)
    except InputTooLarge:
        result = {"error": "provider_input_too_large"}
    except (ImportError, FileNotFoundError, importlib.metadata.PackageNotFoundError):
        result = {"error": "provider_not_configured"}
    except Exception:
        result = {"error": "provider_internal_error"}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
