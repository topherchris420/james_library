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

        raw = json.loads(body)
        content = (
            raw.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if self.verbose:
            print(content)
        return CompletionResult(response=content, raw=raw)


__all__ = ["RLM", "CompletionResult"]
