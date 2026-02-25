"""Minimal local RLM compatibility layer.

This repository previously relied on an external `rlm` package that is not vendored
here.  The launcher scripts only need a small subset of that API:

- `from rlm import RLM`
- `RLM(...).completion(prompt)` returning an object with `.response`

The implementation below keeps those scripts working against LM Studio's OpenAI-
compatible `/v1/chat/completions` endpoint.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import io
import json
import re
from typing import Any
from urllib import request, error

_PYTHON_BLOCK_RE = re.compile(r"```python\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_LOCAL_TOOL_RETRY_PROMPT = (
    "Tool results from local Python execution:\n"
    "{tool_report}\n\n"
    "Use these results to continue. "
    "If you are done, answer directly without a python code block."
)


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
        self.max_local_steps = max(1, int(self.environment_kwargs.get("max_local_steps", 4)))
        self.local_followup_calls = _coerce_bool(self.environment_kwargs.get("local_followup_calls"), False)
        self._local_scope: dict[str, Any] | None = None

        if self.environment == "local":
            self._local_scope = {"__name__": "__rlm_local__"}
            setup_code = str(self.environment_kwargs.get("setup_code", "") or "").strip()
            if setup_code:
                self._run_setup_code(setup_code)

    def completion(self, prompt: str) -> CompletionResult:
        messages: list[dict[str, str]] = []
        if self.custom_system_prompt:
            messages.append({"role": "system", "content": self.custom_system_prompt})
        messages.append({"role": "user", "content": prompt})

        if self.environment == "local":
            if self.local_followup_calls:
                return self._completion_with_local_tools(messages)
            return self._completion_single_pass_local(messages)
        return self._chat_completion(messages)

    def _run_setup_code(self, setup_code: str) -> None:
        if self._local_scope is None:
            return

        try:
            compiled = compile(setup_code, "<rlm_setup_code>", "exec")
            exec(compiled, self._local_scope, self._local_scope)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to execute local setup_code: {exc}") from exc

    def _run_local_code(self, code: str) -> tuple[bool, str]:
        if self._local_scope is None:
            return False, "Local execution environment is not initialized."

        output = io.StringIO()
        try:
            compiled = compile(code, "<rlm_local_code>", "exec")
        except Exception as exc:  # noqa: BLE001
            return False, f"SyntaxError: {exc}"

        try:
            with redirect_stdout(output), redirect_stderr(output):
                exec(compiled, self._local_scope, self._local_scope)
            text = output.getvalue().strip()
            return True, text or "[no output]"
        except Exception as exc:  # noqa: BLE001
            text = output.getvalue().strip()
            prefix = f"{text}\n" if text else ""
            return False, prefix + f"{exc.__class__.__name__}: {exc}"

    def _completion_single_pass_local(self, messages: list[dict[str, str]]) -> CompletionResult:
        """Run exactly one model inference and execute any local python blocks."""
        result = self._chat_completion(messages)
        code_blocks = _extract_python_code_blocks(result.response)
        if not code_blocks:
            return result

        execution_notes: list[tuple[int, bool, str]] = []
        for i, code in enumerate(code_blocks, 1):
            ok, local_output = self._run_local_code(code)
            execution_notes.append((i, ok, local_output))

        cleaned = _strip_python_code_blocks(result.response).strip()
        summary = _format_local_execution_notes(execution_notes)
        response = f"{cleaned}\n\n{summary}".strip() if cleaned else summary
        return CompletionResult(response=response, raw=result.raw)

    def _completion_with_local_tools(self, messages: list[dict[str, str]]) -> CompletionResult:
        last_result: CompletionResult | None = None

        for _ in range(self.max_local_steps):
            result = self._chat_completion(messages)
            last_result = result
            code_blocks = _extract_python_code_blocks(result.response)
            if not code_blocks:
                return result

            messages.append({"role": "assistant", "content": result.response})

            execution_notes: list[str] = []
            for i, code in enumerate(code_blocks, 1):
                ok, local_output = self._run_local_code(code)
                status = "ok" if ok else "error"
                execution_notes.append(f"[python block {i} {status}]\n{local_output}")

            tool_report = "\n\n".join(execution_notes) if execution_notes else "[no output]"
            messages.append(
                {
                    "role": "user",
                    "content": _LOCAL_TOOL_RETRY_PROMPT.format(tool_report=tool_report),
                }
            )

        return CompletionResult(
            response="Local execution step limit reached before a final answer.",
            raw=last_result.raw if last_result is not None else None,
        )

    def _chat_completion(self, messages: list[dict[str, str]]) -> CompletionResult:
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


def _extract_python_code_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for match in _PYTHON_BLOCK_RE.findall(text):
        code = match.strip()
        if code:
            blocks.append(code)
    return blocks


def _strip_python_code_blocks(text: str) -> str:
    return _PYTHON_BLOCK_RE.sub("", text).strip()


def _format_local_execution_notes(notes: list[tuple[int, bool, str]]) -> str:
    if not notes:
        return "Local tool output: [no output]"

    lines = ["Local tool output:"]
    for idx, ok, output in notes:
        status = "ok" if ok else "error"
        collapsed = " | ".join(str(output).splitlines())
        if len(collapsed) > 180:
            collapsed = collapsed[:177] + "..."
        lines.append(f"- python block {idx} [{status}]: {collapsed}")
    return "\n".join(lines)


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
