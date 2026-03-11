from __future__ import annotations

import time
from typing import Dict
from urllib.parse import urlparse, urlunparse

try:
    import requests
except ImportError:
    requests = None


def models_endpoint_from_base_url(base_url: str) -> str:
    raw = (base_url or "").strip() or "http://127.0.0.1:1234/v1"
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)

    scheme = parsed.scheme or "http"
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    if path.endswith("/models"):
        models_path = path
    elif path.endswith("/v1"):
        models_path = f"{path}/models"
    elif not path:
        models_path = "/v1/models"
    else:
        models_path = f"{path}/models"

    return urlunparse((scheme, netloc, models_path, "", "", ""))


def _dedupe_actions(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def diagnose_lm_studio(base_url: str, model_name: str, timeout_s: float = 5.0) -> Dict:
    models_url = models_endpoint_from_base_url(base_url)
    result = {
        "base_url": base_url,
        "models_url": models_url,
        "configured_model": model_name,
        "timeout_s": timeout_s,
        "requests_available": requests is not None,
        "reachable": False,
        "status_code": None,
        "latency_ms": None,
        "loaded_models": [],
        "model_loaded": False,
        "ok": False,
        "error": None,
        "actions": [],
    }

    if requests is None:
        result["error"] = "The 'requests' package is not installed."
        result["actions"] = ["Install requests: pip install requests"]
        return result

    started = time.perf_counter()
    try:
        response = requests.get(models_url, timeout=timeout_s)
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        result["status_code"] = response.status_code
        if response.status_code != 200:
            result["error"] = f"LM Studio returned HTTP {response.status_code} from /v1/models."
            result["actions"] = _dedupe_actions(
                [
                    "Confirm LM Studio is running.",
                    "Enable the Local Server in LM Studio.",
                    f"Verify the configured base URL: {base_url}",
                ]
            )
            return result

        result["reachable"] = True
        try:
            payload = response.json()
        except ValueError:
            result["error"] = "LM Studio responded, but /v1/models returned invalid JSON."
            result["actions"] = ["Restart the LM Studio local server and try again."]
            return result

        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            loaded_models = [str(item.get("id", "unknown")) for item in data if isinstance(item, dict)]
        else:
            loaded_models = []
        result["loaded_models"] = loaded_models
        if model_name:
            result["model_loaded"] = model_name in loaded_models
        else:
            result["model_loaded"] = bool(loaded_models)

        actions: list[str] = []
        if not loaded_models:
            actions.append("Load a model in LM Studio before starting the meeting.")
        elif model_name and model_name not in loaded_models:
            actions.append(f"Load the configured model '{model_name}' in LM Studio.")
        result["actions"] = _dedupe_actions(actions)
        result["ok"] = result["reachable"] and (result["model_loaded"] or not model_name)
        if not result["ok"] and result["error"] is None:
            if not loaded_models:
                result["error"] = "LM Studio is reachable, but no model is loaded."
            else:
                result["error"] = f"LM Studio is reachable, but '{model_name}' is not loaded."
        return result

    except requests.exceptions.ConnectionError:
        result["error"] = f"Could not connect to LM Studio at {models_url}."
        result["actions"] = _dedupe_actions(
            [
                "Start LM Studio.",
                "Enable the Local Server in LM Studio.",
                f"Verify the configured base URL: {base_url}",
            ]
        )
        return result
    except requests.exceptions.Timeout:
        result["error"] = f"LM Studio did not respond to /v1/models within {timeout_s:.1f}s."
        result["actions"] = _dedupe_actions(
            [
                "Wait for the model to finish loading in LM Studio.",
                "Try a lighter model or increase timeout settings.",
                f"Verify the configured base URL: {base_url}",
            ]
        )
        return result
    except requests.RequestException as exc:
        result["error"] = f"LM Studio diagnostics request failed: {exc}"
        result["actions"] = _dedupe_actions(
            [
                "Restart the LM Studio local server.",
                f"Verify the configured base URL: {base_url}",
            ]
        )
        return result


def probe_lm_studio_completion(base_url: str, api_key: str, model_name: str, timeout_s: float) -> Dict:
    result = {
        "ok": False,
        "latency_ms": None,
        "finish_reason": None,
        "preview": "",
        "error": None,
        "actions": [],
    }

    try:
        import openai
    except ImportError:
        result["error"] = "The 'openai' package is not installed."
        result["actions"] = ["Install openai: pip install openai"]
        return result

    started = time.perf_counter()
    try:
        client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=max(5.0, timeout_s))
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "Reply with the word READY."}],
            temperature=0.0,
            max_tokens=8,
        )
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        result["finish_reason"] = getattr(response.choices[0], "finish_reason", None)
        result["preview"] = (response.choices[0].message.content or "").strip()
        result["ok"] = True
        return result
    except openai.APITimeoutError:
        result["error"] = f"Chat completion timed out after {timeout_s:.1f}s."
        result["actions"] = _dedupe_actions(
            [
                f"Increase RAIN_LM_TIMEOUT above {timeout_s:.1f}s.",
                "Wait for the model to finish loading in LM Studio.",
            ]
        )
        return result
    except openai.APIConnectionError as exc:
        result["error"] = f"OpenAI-compatible connection failed: {exc}"
        result["actions"] = _dedupe_actions(
            [
                "Ensure LM Studio Local Server is enabled.",
                f"Verify the configured base URL: {base_url}",
            ]
        )
        return result
    except openai.APIError as exc:
        result["error"] = f"LM Studio returned an API error: {exc}"
        result["actions"] = ["Reload the model in LM Studio and retry."]
        return result
    except Exception as exc:
        result["error"] = f"Chat completion probe failed: {exc}"
        result["actions"] = ["Run doctor mode again after verifying LM Studio is healthy."]
        return result


def collect_lm_studio_diagnostics(
    base_url: str,
    model_name: str,
    api_key: str = "lm-studio",
    timeout_s: float = 5.0,
    include_completion_probe: bool = True,
) -> Dict:
    endpoint = diagnose_lm_studio(base_url, model_name, timeout_s=timeout_s)
    if include_completion_probe and endpoint.get("reachable") and endpoint.get("model_loaded"):
        probe = probe_lm_studio_completion(base_url, api_key, model_name, timeout_s)
    else:
        probe = {
            "ok": None,
            "latency_ms": None,
            "finish_reason": None,
            "preview": "",
            "error": None,
            "actions": [],
        }

    actions = _dedupe_actions(list(endpoint.get("actions", [])) + list(probe.get("actions", [])))
    ok = bool(endpoint.get("ok")) and (probe.get("ok") in (True, None))
    return {
        "ok": ok,
        "base_url": base_url,
        "configured_model": model_name,
        "timeout_s": timeout_s,
        "endpoint": endpoint,
        "probe": probe,
        "actions": actions,
    }
