"""Minimal local RLM compatibility layer.

This repository previously relied on an external `rlm` package that is not vendored
here.  The launcher scripts only need a small subset of that API:

- `from rlm import RLM`
- `RLM(...).completion(prompt)` returning an object with `.response`

The implementation below keeps those scripts working against LM Studio's OpenAI-
compatible `/v1/chat/completions` endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import request, error


@dataclass
class CompletionResult:
    response: str
    raw: dict[str, Any] | None = None


class RLM:
    """Small compatibility wrapper for the historical RLM interface."""

    def __init__(
        self,
        backend: str = "openai",
        backend_kwargs: dict[str, Any] | None = None,
        environment: str | None = None,
        environment_kwargs: dict[str, Any] | None = None,
        custom_system_prompt: str | None = None,
        verbose: bool = False,
    ) -> None:
        if backend != "openai":
            raise ValueError("This lightweight RLM shim supports only backend='openai'.")

        self.backend_kwargs = backend_kwargs or {}
        self.base_url = str(self.backend_kwargs.get("base_url", "http://127.0.0.1:1234/v1")).rstrip("/")
        self.model_name = str(self.backend_kwargs.get("model_name", "qwen2.5-coder-7b-instruct"))
        self.api_key = str(self.backend_kwargs.get("api_key", "lm-studio"))
        self.timeout = float(self.backend_kwargs.get("timeout", 180.0))

        self.environment = environment
        self.environment_kwargs = environment_kwargs or {}
        self.custom_system_prompt = custom_system_prompt
        self.verbose = verbose

    def completion(self, prompt: str) -> CompletionResult:
        messages: list[dict[str, str]] = []
        if self.custom_system_prompt:
            messages.append({"role": "system", "content": self.custom_system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.2,
            # Explicitly request a non-stream response. Some local OpenAI-compatible
            # servers default to streaming, which can leave terminal callers waiting
            # for a final JSON payload that never arrives.
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")

        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
            raise RuntimeError(f"LM Studio request failed with HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to reach LM Studio endpoint at {self.base_url}: {exc}") from exc

        raw, content = _decode_completion_body(body)
        if self.verbose:
            print(content)
        return CompletionResult(response=content, raw=raw)


def _decode_completion_body(body: str) -> tuple[dict[str, Any], str]:
    """Decode either JSON chat completion payloads or SSE stream dumps."""
    try:
        raw = json.loads(body)
        return raw, _extract_content_from_completion_json(raw)
    except json.JSONDecodeError:
        # Some local servers can still return SSE frames in edge cases.
        # Parse those frames defensively so callers receive the final text.
        text = _extract_content_from_sse(body)
        return {"_raw_sse": body}, text


def _extract_content_from_completion_json(raw: dict[str, Any]) -> str:
    choice = raw.get("choices", [{}])[0]
    message = choice.get("message", {}) if isinstance(choice, dict) else {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content
    return ""


def _extract_content_from_sse(body: str) -> str:
    chunks: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            evt = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = evt.get("choices", []) if isinstance(evt, dict) else []
        if not choices:
            continue
        first = choices[0] if isinstance(choices[0], dict) else {}
        delta = first.get("delta", {}) if isinstance(first, dict) else {}
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            chunks.append(delta["content"])
            continue
        message = first.get("message", {}) if isinstance(first, dict) else {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            chunks.append(message["content"])
            continue
        if isinstance(first.get("text"), str):
            chunks.append(first["text"])
    return "".join(chunks)


__all__ = ["RLM", "CompletionResult"]


def _extract_choice_content(choice: dict[str, Any]) -> str:
    """Normalize LM Studio/OpenAI chat completion content variants."""
    message = choice.get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        if text:
            return str(text)

    text = choice.get("text")
    if isinstance(text, str):
        return text

    delta = choice.get("delta") or {}
    delta_content = delta.get("content")
    if isinstance(delta_content, str):
        return delta_content

    return ""
