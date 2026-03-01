"""Unified async runtime for R.A.I.N. Lab integrations.

This module provides a stable async entrypoint used by gateways (e.g. Telegram)
with lightweight typed runtime state/events plus provenance extraction.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from heapq import nsmallest
from itertools import chain
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 compatibility
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]

try:
    from truth_layer import Evidence, assert_grounded, build_grounded_response
except Exception:
    Evidence = None
    assert_grounded = None
    build_grounded_response = None


@dataclass(slots=True)
class RuntimeEvent:
    timestamp: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProvenanceItem:
    source: str
    source_type: str  # "paper" | "web"
    quote: Optional[str] = None


@dataclass(slots=True)
class RuntimeState:
    session_id: str
    query: str
    mode: str
    agent: Optional[str]
    status: str = "initialized"
    events: list[RuntimeEvent] = field(default_factory=list)

    def add_event(self, kind: str, payload: Optional[dict[str, Any]] = None) -> None:
        self.events.append(
            RuntimeEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                kind=kind,
                payload=payload or {},
            )
        )


@dataclass(slots=True)
class RuntimeConfig:
    llm_timeout_s: float
    llm_retries: int
    llm_retry_backoff_s: float
    max_query_chars: int
    strict_grounding: bool
    min_grounding_confidence: float
    return_json: bool
    trace_enabled: bool
    trace_include_payload: bool
    llm_base_url: str
    llm_model: str
    llm_api_key: Optional[str] = field(default=None, repr=False)
    config_path: Optional[str] = None


_RE_SOURCE_TAG = re.compile(r"\[from\s+(web:\s*)?([^\]]+?)\]", re.IGNORECASE)
_RE_QUOTE = re.compile(r'"([^"]+)"')
_RE_WHITESPACE = re.compile(r"\s+")
_CONTROL_TOKENS = ("<|endoftext|>", "<|im_start|>", "<|im_end|>", "|eoc_fim|")
_VALID_MODES = {"chat", "rlm"}
_DEFAULT_LLM_BASE_URL = "http://127.0.0.1:1234/v1"
_DEFAULT_LLM_MODEL = "qwen2.5-coder-7b-instruct"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _coerce_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _normalize_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pick_optional_str(*values: Any) -> Optional[str]:
    for value in values:
        normalized = _normalize_optional_str(value)
        if normalized:
            return normalized
    return None


def _dict_section(root: dict[str, Any], key: str) -> dict[str, Any]:
    section = root.get(key)
    if isinstance(section, dict):
        return section
    return {}


def _resolve_runtime_config_path(config_path: Optional[str]) -> Optional[Path]:
    raw = (config_path or os.environ.get("RAIN_RUNTIME_CONFIG") or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _load_runtime_config_file(config_path: Optional[str]) -> tuple[dict[str, Any], Optional[Path]]:
    resolved = _resolve_runtime_config_path(config_path)
    if resolved is None:
        return {}, None
    if not resolved.exists():
        raise RuntimeError(f"R.A.I.N. runtime config error: file not found: {resolved}")
    if tomllib is None:
        raise RuntimeError(
            "R.A.I.N. runtime config error: TOML parser unavailable. "
            "Use Python 3.11+ or install tomli."
        )

    try:
        content = resolved.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)
    except Exception as exc:
        raise RuntimeError(f"R.A.I.N. runtime config error: failed to parse {resolved}: {exc}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"R.A.I.N. runtime config error: top-level table required in {resolved}")
    return parsed, resolved


def _is_local_or_private_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or getattr(ip, "is_unspecified", False)
    )


def _validate_runtime_config(config: RuntimeConfig) -> None:
    base_url = (config.llm_base_url or "").strip()
    parsed = urlparse(base_url)
    if not base_url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            "R.A.I.N. runtime config error: invalid LLM base URL. "
            "Set LM_STUDIO_BASE_URL or llm.base_url to a valid http(s) URL."
        )

    model = (config.llm_model or "").strip()
    if not model:
        raise RuntimeError(
            "R.A.I.N. runtime config error: missing model. "
            "Set LM_STUDIO_MODEL or llm.model."
        )

    if not config.llm_api_key and not _is_local_or_private_base_url(base_url):
        raise RuntimeError(
            "R.A.I.N. runtime config error: missing API key for non-local endpoint. "
            "Set LM_STUDIO_API_KEY or llm.api_key."
        )


def _public_runtime_config(config: RuntimeConfig) -> dict[str, Any]:
    return {
        "llm_timeout_s": config.llm_timeout_s,
        "llm_retries": config.llm_retries,
        "llm_retry_backoff_s": config.llm_retry_backoff_s,
        "max_query_chars": config.max_query_chars,
        "strict_grounding": config.strict_grounding,
        "min_grounding_confidence": config.min_grounding_confidence,
        "return_json": config.return_json,
        "trace_enabled": config.trace_enabled,
        "trace_include_payload": config.trace_include_payload,
        "llm_base_url": config.llm_base_url,
        "llm_model": config.llm_model,
        "llm_api_key_configured": bool(config.llm_api_key),
        "config_path": config.config_path,
    }


def _load_runtime_config(config_path: Optional[str] = None) -> RuntimeConfig:
    file_config, resolved_config_path = _load_runtime_config_file(config_path)
    runtime_section = _dict_section(file_config, "runtime")
    llm_section = _dict_section(file_config, "llm")

    timeout_default = _coerce_float(
        runtime_section.get("llm_timeout_s", runtime_section.get("timeout_s")),
        120.0,
        10.0,
        600.0,
    )
    retries_default = _coerce_int(runtime_section.get("llm_retries", runtime_section.get("retries")), 2, 0, 5)
    retry_backoff_default = _coerce_float(
        runtime_section.get("llm_retry_backoff_s", runtime_section.get("retry_backoff_s")),
        0.8,
        0.1,
        5.0,
    )
    max_query_chars_default = _coerce_int(runtime_section.get("max_query_chars"), 4000, 100, 32000)
    strict_grounding_default = _coerce_bool(runtime_section.get("strict_grounding"), False)
    min_grounding_default = _coerce_float(
        runtime_section.get("min_grounding_confidence"),
        0.4,
        0.0,
        1.0,
    )
    return_json_default = _coerce_bool(runtime_section.get("return_json"), False)
    trace_enabled_default = _coerce_bool(runtime_section.get("trace_enabled"), False)
    trace_include_payload_default = _coerce_bool(runtime_section.get("trace_include_payload"), False)

    base_url_default = _pick_optional_str(
        llm_section.get("base_url"),
        runtime_section.get("llm_base_url"),
        _DEFAULT_LLM_BASE_URL,
    ) or _DEFAULT_LLM_BASE_URL
    model_default = _pick_optional_str(
        llm_section.get("model"),
        runtime_section.get("llm_model"),
        _DEFAULT_LLM_MODEL,
    ) or _DEFAULT_LLM_MODEL
    api_key_default = _pick_optional_str(
        llm_section.get("api_key"),
        runtime_section.get("llm_api_key"),
    )

    return RuntimeConfig(
        llm_timeout_s=_env_float("RAIN_RUNTIME_TIMEOUT_S", timeout_default, 10.0, 600.0),
        llm_retries=_env_int("RAIN_RUNTIME_RETRIES", retries_default, 0, 5),
        llm_retry_backoff_s=_env_float("RAIN_RUNTIME_RETRY_BACKOFF_S", retry_backoff_default, 0.1, 5.0),
        max_query_chars=_env_int("RAIN_RUNTIME_MAX_QUERY_CHARS", max_query_chars_default, 100, 32000),
        strict_grounding=_env_bool("RAIN_STRICT_GROUNDING", strict_grounding_default),
        min_grounding_confidence=_env_float("RAIN_MIN_GROUNDED_CONFIDENCE", min_grounding_default, 0.0, 1.0),
        return_json=_env_bool("RAIN_RUNTIME_JSON_RESPONSE", return_json_default),
        trace_enabled=_env_bool("RAIN_RUNTIME_TRACE_ENABLED", trace_enabled_default),
        trace_include_payload=_env_bool("RAIN_RUNTIME_TRACE_INCLUDE_PAYLOAD", trace_include_payload_default),
        llm_base_url=_pick_optional_str(os.environ.get("LM_STUDIO_BASE_URL"), base_url_default)
        or _DEFAULT_LLM_BASE_URL,
        llm_model=_pick_optional_str(os.environ.get("LM_STUDIO_MODEL"), model_default) or _DEFAULT_LLM_MODEL,
        llm_api_key=_pick_optional_str(os.environ.get("LM_STUDIO_API_KEY"), api_key_default),
        config_path=str(resolved_config_path) if resolved_config_path else None,
    )


def _safe_agent_name(agent: Optional[str]) -> str:
    if not agent:
        return "James"
    cleaned = agent.strip().lower()
    mapping = {"james": "James", "jasmine": "Jasmine", "elena": "Elena", "luca": "Luca"}
    return mapping.get(cleaned, "James")


def _library_path() -> Path:
    default_path = Path(__file__).resolve().parent
    raw = os.environ.get("JAMES_LIBRARY_PATH", str(default_path))
    return Path(raw).expanduser().resolve()


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _sanitize_query(query: str, max_chars: int) -> str:
    text = query or ""
    for token in _CONTROL_TOKENS:
        text = text.replace(token, " ")
    text = text.replace("\0", " ")
    text = _RE_WHITESPACE.sub(" ", text).strip()
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _read_context_excerpt(path: Path, char_budget: int) -> str:
    """Read at most `char_budget` chars of stripped text from `path`.

    Preserves prior behavior: equivalent to `path.read_text(...).strip()[:char_budget]`
    while avoiding full-file reads when the budget is already exhausted.
    """
    if char_budget <= 0:
        return ""

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        collected: list[str] = []
        remaining = char_budget
        found_non_whitespace = False

        while True:
            chunk = handle.read(8192)
            if not chunk:
                break

            if not found_non_whitespace:
                chunk = chunk.lstrip()
                if not chunk:
                    continue
                found_non_whitespace = True

            if len(chunk) >= remaining:
                prefix = chunk[:remaining]
                collected.append(prefix)

                # If any non-whitespace content remains, this is a true
                # truncation and we can return immediately.
                tail = chunk[remaining:]
                if tail.strip():
                    return "".join(collected)

                # Otherwise, only trailing whitespace may remain. Keep scanning
                # until EOF or until we confirm additional non-whitespace text.
                while True:
                    trailing = handle.read(8192)
                    if not trailing:
                        return "".join(collected).rstrip()
                    if trailing.strip():
                        return "".join(collected)

            collected.append(chunk)
            remaining -= len(chunk)

        if not collected:
            return ""

    return "".join(collected).rstrip()


def _load_context(max_chars: int = 12000, max_files: int = 40) -> tuple[str, list[str]]:
    base = _library_path()
    if not base.exists():
        return "", []

    candidates = chain(base.glob("*.md"), base.glob("*.txt"))
    filtered_candidates = (
        p
        for p in candidates
        if "SOUL" not in p.name.upper() and "LOG" not in p.name.upper() and not p.name.startswith("_")
    )
    files = nsmallest(max_files, filtered_candidates, key=lambda p: str(p))

    names: list[str] = []
    chunks: list[str] = []
    budget = max_chars
    for p in files:
        try:
            text = _read_context_excerpt(p, budget)
        except Exception:
            continue
        if not text:
            continue
        names.append(p.name)
        chunks.append(f"--- {p.name} ---\n{text}")
        budget -= len(text)
        if budget <= 0:
            break

    return "\n\n".join(chunks), names


def _extract_provenance(response_text: str) -> list[ProvenanceItem]:
    provenance: list[ProvenanceItem] = []
    web_sources: set[str] = set()
    local_sources: set[str] = set()
    for match in _RE_SOURCE_TAG.finditer(response_text):
        source = match.group(2).strip()
        if not source:
            continue
        if match.group(1):
            web_sources.add(source)
        else:
            local_sources.add(source)

    quotes = [q.strip() for q in _RE_QUOTE.findall(response_text) if len(q.split()) > 3]
    first_quote = quotes[0] if quotes else None

    for src in sorted(local_sources):
        provenance.append(ProvenanceItem(source=src, source_type="paper", quote=first_quote))
    for src in sorted(web_sources):
        provenance.append(ProvenanceItem(source=src, source_type="web", quote=first_quote))

    return provenance


def _confidence_score(response_text: str, provenance: list[ProvenanceItem]) -> float:
    score = 0.35
    citation_bonus = min(len(provenance), 3) * 0.18
    score += citation_bonus

    lower = response_text.lower()
    if "[speculation]" in lower or "[theory]" in lower:
        score -= 0.12
    if "don't know" in lower or "not sure" in lower or "papers don't cover this" in lower:
        score -= 0.15

    return max(0.05, min(0.98, round(score, 2)))


def _trace_log_path() -> Path:
    library = _library_path()
    default_path = library / "meeting_archives" / "runtime_events.jsonl"
    env = os.environ.get("RAIN_RUNTIME_TRACE_PATH")
    if not env:
        return default_path

    candidate = Path(env).expanduser()
    if not candidate.is_absolute():
        candidate = library / candidate
    candidate = candidate.resolve()

    if _env_bool("RAIN_ALLOW_EXTERNAL_TRACE_PATH", False):
        return candidate

    if _is_relative_to(candidate, library):
        return candidate
    return default_path


def _append_trace_line(payload: dict[str, Any]) -> None:
    path = _trace_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _redact_trace_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"present": value is not None}

    provenance = value.get("provenance", [])
    provenance_count = len(provenance) if isinstance(provenance, list) else 0
    answer = value.get("answer", "")
    return {
        "status": value.get("status"),
        "mode": value.get("mode"),
        "agent": value.get("agent"),
        "confidence": value.get("confidence"),
        "grounded": value.get("grounded"),
        "red_badge": value.get("red_badge"),
        "provenance_count": provenance_count,
        "answer_chars": len(str(answer)),
    }


def _sanitize_trace_extras(extra: dict[str, Any], include_payload: bool) -> dict[str, Any]:
    if include_payload:
        return extra

    sanitized: dict[str, Any] = {}
    for key, value in extra.items():
        if key == "response":
            sanitized["response"] = _redact_trace_response(value)
            continue
        if key == "provenance":
            if isinstance(value, list):
                sanitized["provenance"] = {"count": len(value)}
            else:
                sanitized["provenance"] = {"count": None}
            continue
        sanitized[key] = value
    return sanitized


def _trace_state(state: RuntimeState, config: RuntimeConfig, **extra: Any) -> None:
    if not config.trace_enabled:
        return

    payload = {
        "timestamp": _utc_now(),
        "session_id": state.session_id,
        "status": state.status,
        "mode": state.mode,
        "agent": state.agent,
        "events": [asdict(e) for e in state.events],
    }

    if config.trace_include_payload:
        payload["query"] = state.query
    else:
        payload["query"] = "[redacted]"
        payload["query_chars"] = len(state.query)

    payload.update(_sanitize_trace_extras(extra, config.trace_include_payload))
    _append_trace_line(payload)


def _build_messages(
    query: str,
    mode: str,
    agent: str,
    context_block: str,
    recursive_depth: int,
) -> list[dict[str, str]]:
    mode_instruction = (
        "You are in multi-agent synthesis mode. Give concise, evidence-grounded synthesis."
        if mode == "rlm"
        else "You are in direct chat mode. Answer crisply with research grounding."
    )
    system_prompt = (
        f"You are {agent}, a R.A.I.N. Lab research agent. "
        f"{mode_instruction} "
        f"Prefer grounded claims and cite as [from filename.md] or [from web: source]. "
        f"Recursive depth hint: {recursive_depth}. Keep answer under 180 words.\n\n"
        f"LOCAL RESEARCH CONTEXT:\n{context_block}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]


def _call_llm_sync(
    messages: list[dict[str, str]],
    timeout_s: float,
    base_url: str,
    api_key: str,
    model: str,
) -> str:
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError("openai package is required for run_rain_lab runtime") from exc

    client = openai.OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout_s,
    )
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=220,
        temperature=0.4,
    )
    return (response.choices[0].message.content or "").strip()


async def _call_llm_with_retries(
    messages: list[dict[str, str]],
    config: RuntimeConfig,
    state: RuntimeState,
) -> str:
    last_error: Exception | None = None
    api_key = config.llm_api_key or "lm-studio"

    for attempt in range(config.llm_retries + 1):
        try:
            return await asyncio.to_thread(
                _call_llm_sync,
                messages,
                config.llm_timeout_s,
                config.llm_base_url,
                api_key,
                config.llm_model,
            )
        except Exception as exc:
            last_error = exc
            state.add_event(
                "llm_attempt_failed",
                {
                    "attempt": attempt + 1,
                    "max_attempts": config.llm_retries + 1,
                    "error": str(exc),
                },
            )
            if attempt < config.llm_retries:
                await asyncio.sleep(config.llm_retry_backoff_s * (attempt + 1))

    assert last_error is not None
    raise RuntimeError(f"LLM call failed after retries: {last_error}")


def _build_grounding_payload(
    answer: str,
    confidence: float,
    provenance: list[ProvenanceItem],
    state: RuntimeState,
) -> dict[str, Any]:
    provenance_sources = [p.source for p in provenance]
    repro_steps = [e.kind for e in state.events]

    if build_grounded_response is None or Evidence is None:
        return {
            "answer": answer,
            "confidence": confidence,
            "provenance": provenance_sources,
            "evidence": [asdict(p) for p in provenance],
            "repro_steps": repro_steps,
            "grounded": bool(provenance),
            "red_badge": not bool(provenance),
        }

    evidence = [
        Evidence(source=p.source, quote=(p.quote or ""), span_start=None, span_end=None)
        for p in provenance
    ]
    return build_grounded_response(
        answer=answer,
        confidence=confidence,
        provenance=provenance_sources,
        evidence=evidence,
        repro_steps=repro_steps,
    )


def runtime_healthcheck(config_path: Optional[str] = None) -> dict[str, Any]:
    config = _load_runtime_config(config_path=config_path)
    library = _library_path()

    checks: dict[str, bool] = {
        "library_exists": library.exists(),
        "trace_dir_writable": False,
        "openai_importable": False,
        "llm_config_valid": False,
    }

    try:
        import openai  # noqa: F401
        checks["openai_importable"] = True
    except Exception:
        checks["openai_importable"] = False

    if config.trace_enabled:
        try:
            trace_dir = _trace_log_path().parent
            trace_dir.mkdir(parents=True, exist_ok=True)
            checks["trace_dir_writable"] = os.access(trace_dir, os.W_OK)
        except Exception:
            checks["trace_dir_writable"] = False
    else:
        checks["trace_dir_writable"] = True

    try:
        _validate_runtime_config(config)
        checks["llm_config_valid"] = True
    except Exception:
        checks["llm_config_valid"] = False

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "config": _public_runtime_config(config),
        "library_path": str(library),
        "trace_path": str(_trace_log_path()),
    }


def _format_output(payload: dict[str, Any], return_json: bool) -> str:
    if return_json:
        return json.dumps(payload, ensure_ascii=False)

    answer = payload.get("answer", "")
    confidence = float(payload.get("confidence", 0.0))
    provenance = payload.get("provenance", [])

    lines = [answer.strip()] if answer else []
    if provenance:
        sources = ", ".join(sorted({str(s) for s in provenance})[:3])
        lines.append(f"Provenance: {sources}")
    lines.append(f"Confidence: {confidence:.2f}")

    if not payload.get("grounded", True):
        lines.append("Grounded: no")

    return "\n\n".join(lines)


def _classify_runtime_exception(exc: Exception) -> tuple[str, str]:
    message = str(exc).strip()
    lower = message.lower()
    if lower.startswith("r.a.i.n. runtime config error:"):
        return ("error", message)
    if (
        "operation was canceled" in lower
        or "operation was cancelled" in lower
        or "request was canceled" in lower
        or "request was cancelled" in lower
    ):
        return (
            "canceled",
            "R.A.I.N. runtime canceled: the operation was canceled. "
            "Retry and verify LM Studio is running with a loaded model.",
        )
    return ("error", "R.A.I.N. runtime error: unable to generate response.")


async def run_rain_lab(
    query: str,
    mode: str = "chat",
    agent: str | None = None,
    recursive_depth: int = 1,
    config_path: str | None = None,
    llm_timeout_s: float | None = None,
    max_turns: int = 1,
) -> str:
    """Unified async runtime entrypoint for non-CLI gateways."""
    try:
        config = _load_runtime_config(config_path=config_path)
    except Exception as exc:
        return str(exc)

    if llm_timeout_s is not None:
        config.llm_timeout_s = max(10.0, min(600.0, float(llm_timeout_s)))

    resolved_agent = _safe_agent_name(agent)
    safe_query = _sanitize_query(query, config.max_query_chars)

    state = RuntimeState(
        session_id=str(uuid.uuid4())[:8],
        query=safe_query,
        mode=mode,
        agent=resolved_agent,
    )
    state.add_event(
        "runtime_started",
        {
            "mode": mode,
            "agent": resolved_agent,
            "strict_grounding": config.strict_grounding,
            "max_query_chars": config.max_query_chars,
            "config_path": config.config_path,
            "llm_base_url": config.llm_base_url,
            "llm_model": config.llm_model,
            "trace_enabled": config.trace_enabled,
            "trace_include_payload": config.trace_include_payload,
            "max_turns": max_turns,
        },
    )

    if mode not in _VALID_MODES:
        state.status = "error"
        state.add_event("runtime_failed", {"error": f"Unsupported mode: {mode}"})
        _trace_state(state, config)
        return "R.A.I.N. runtime error: unsupported mode. Use 'chat' or 'rlm'."

    if not safe_query:
        state.status = "error"
        state.add_event("runtime_failed", {"error": "Empty query after sanitization"})
        _trace_state(state, config)
        return "R.A.I.N. runtime error: query is empty after sanitization."

    try:
        _validate_runtime_config(config)
    except Exception as exc:
        message = str(exc)
        state.status = "error"
        state.add_event("runtime_failed", {"error": message, "kind": "config"})
        _trace_state(state, config)
        return message

    if max_turns < 1:
        state.status = "error"
        state.add_event("runtime_failed", {"error": "Invalid max_turns", "max_turns": max_turns})
        _trace_state(state, config)
        return "R.A.I.N. runtime error: --max-turns must be at least 1."

    if max_turns != 1:
        state.status = "error"
        state.add_event(
            "runtime_failed",
            {"error": "Unsupported max_turns for this runtime", "max_turns": max_turns},
        )
        _trace_state(state, config)
        return "R.A.I.N. runtime error: chat runtime currently supports --max-turns 1."

    context_block, paper_list = _load_context()
    state.add_event("context_loaded", {"papers": len(paper_list), "chars": len(context_block)})

    messages = _build_messages(
        query=safe_query,
        mode=mode,
        agent=resolved_agent,
        context_block=context_block,
        recursive_depth=max(1, int(recursive_depth)),
    )
    state.add_event("llm_request_prepared", {"message_count": len(messages)})

    try:
        response_text = await _call_llm_with_retries(messages, config, state)
        state.status = "ok"
        state.add_event("llm_response_received", {"chars": len(response_text)})
    except Exception as exc:
        status, message = _classify_runtime_exception(exc)
        state.status = status
        state.add_event("runtime_failed", {"error": str(exc), "status": status})
        _trace_state(state, config)
        return message

    provenance = _extract_provenance(response_text)
    confidence = _confidence_score(response_text, provenance)
    grounded = bool(provenance) and confidence >= config.min_grounding_confidence

    if config.strict_grounding and not grounded:
        response_text = (
            "Grounding policy blocked this answer. "
            "Please provide a narrower query or add supporting local sources."
        )
        state.status = "blocked"
        state.add_event(
            "grounding_blocked",
            {
                "sources": len(provenance),
                "confidence": confidence,
                "min_confidence": config.min_grounding_confidence,
            },
        )

    state.add_event(
        "provenance_analyzed",
        {
            "sources": len(provenance),
            "confidence": confidence,
            "grounded": grounded,
        },
    )

    payload = _build_grounding_payload(
        answer=response_text,
        confidence=confidence,
        provenance=provenance,
        state=state,
    )

    if config.strict_grounding and assert_grounded is not None:
        try:
            assert_grounded(payload)
        except ValueError as exc:
            state.add_event("grounding_assertion_failed", {"error": str(exc)})
            payload["grounded"] = False
            payload["red_badge"] = True

    payload.update(
        {
            "session_id": state.session_id,
            "status": state.status,
            "mode": mode,
            "agent": resolved_agent,
        }
    )

    _trace_state(
        state,
        config,
        confidence=confidence,
        grounded=bool(payload.get("grounded", False)),
        provenance=[asdict(p) for p in provenance],
        response=payload,
    )

    return _format_output(payload, config.return_json)


def _parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="R.A.I.N. Lab runtime CLI")
    parser.add_argument("--topic", type=str, default=None, help="Research topic/query")
    parser.add_argument("--query", type=str, default=None, help="Alias for --topic")
    parser.add_argument("--mode", choices=sorted(_VALID_MODES), default="chat")
    parser.add_argument("--agent", type=str, default=None, help="Agent identity hint")
    parser.add_argument("--recursive-depth", type=int, default=1, help="Internal critique depth")
    parser.add_argument(
        "--no-recursive-intellect",
        action="store_true",
        help="Disable recursive self-reflection (forces recursive depth to 1).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Per-request LLM timeout override in seconds.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=1,
        help="Maximum turns for chat runtime. Current runtime supports 1.",
    )
    parser.add_argument("--library", type=str, default=None, help="Override JAMES_LIBRARY_PATH")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Optional TOML config path for runtime and LLM settings.",
    )
    return parser.parse_args(argv)


def _cli_exit_code(output: str) -> int:
    body = output.strip()
    if body.startswith("{") and body.endswith("}"):
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        status = str(payload.get("status", "")).lower()
        if status == "ok":
            return 0
        if status == "blocked":
            return 2
        if status == "canceled":
            return 3
        if status:
            return 1

    lower = body.lower()
    if "grounding policy blocked" in lower:
        return 2
    if "runtime canceled" in lower:
        return 3
    if "runtime error" in lower:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_cli_args(argv)
    query = (args.query or args.topic or "").strip()
    if not query:
        print("R.A.I.N. runtime error: provide --topic or --query.")
        return 2

    recursive_depth = 1 if args.no_recursive_intellect else max(1, int(args.recursive_depth))

    if args.library:
        os.environ["JAMES_LIBRARY_PATH"] = args.library

    try:
        output = asyncio.run(
            run_rain_lab(
                query=query,
                mode=args.mode,
                agent=args.agent,
                recursive_depth=recursive_depth,
                config_path=args.config,
                llm_timeout_s=args.timeout,
                max_turns=args.max_turns,
            )
        )
    except Exception:
        print("R.A.I.N. runtime error: unexpected runtime failure.")
        return 1

    print(output)
    return _cli_exit_code(output)


if __name__ == "__main__":
    raise SystemExit(main())
