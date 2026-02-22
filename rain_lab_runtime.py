"""Unified async runtime for R.A.I.N. Lab integrations.

This module provides a stable async entrypoint used by gateways (e.g. Telegram)
with lightweight typed runtime state/events plus provenance extraction.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


_RE_LOCAL_SOURCE = re.compile(r"\[from\s+([^\]]+?)\]", re.IGNORECASE)
_RE_WEB_SOURCE = re.compile(r"\[from\s+web:\s*([^\]]+?)\]", re.IGNORECASE)
_RE_QUOTE = re.compile(r'"([^"]+)"')
_RE_WHITESPACE = re.compile(r"\s+")
_CONTROL_TOKENS = ("<|endoftext|>", "<|im_start|>", "<|im_end|>", "|eoc_fim|")
_VALID_MODES = {"chat", "rlm"}


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


def _load_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        llm_timeout_s=_env_float("RAIN_RUNTIME_TIMEOUT_S", 120.0, 10.0, 600.0),
        llm_retries=_env_int("RAIN_RUNTIME_RETRIES", 2, 0, 5),
        llm_retry_backoff_s=_env_float("RAIN_RUNTIME_RETRY_BACKOFF_S", 0.8, 0.1, 5.0),
        max_query_chars=_env_int("RAIN_RUNTIME_MAX_QUERY_CHARS", 4000, 100, 32000),
        strict_grounding=_env_bool("RAIN_STRICT_GROUNDING", False),
        min_grounding_confidence=_env_float("RAIN_MIN_GROUNDED_CONFIDENCE", 0.4, 0.0, 1.0),
        return_json=_env_bool("RAIN_RUNTIME_JSON_RESPONSE", False),
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


def _sanitize_query(query: str, max_chars: int) -> str:
    text = query or ""
    for token in _CONTROL_TOKENS:
        text = text.replace(token, " ")
    text = text.replace("\0", " ")
    text = _RE_WHITESPACE.sub(" ", text).strip()
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _load_context(max_chars: int = 12000, max_files: int = 40) -> tuple[str, list[str]]:
    base = _library_path()
    if not base.exists():
        return "", []

    files = sorted(list(base.glob("*.md")) + list(base.glob("*.txt")))
    files = [
        p
        for p in files
        if "SOUL" not in p.name.upper() and "LOG" not in p.name.upper() and not p.name.startswith("_")
    ][:max_files]

    names: list[str] = []
    chunks: list[str] = []
    budget = max_chars
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not text:
            continue
        names.append(p.name)
        take = min(len(text), budget)
        chunks.append(f"--- {p.name} ---\n{text[:take]}")
        budget -= take
        if budget <= 0:
            break

    return "\n\n".join(chunks), names


def _extract_provenance(response_text: str) -> list[ProvenanceItem]:
    provenance: list[ProvenanceItem] = []

    web_sources = {m.strip() for m in _RE_WEB_SOURCE.findall(response_text)}
    local_sources = {m.strip() for m in _RE_LOCAL_SOURCE.findall(response_text)}

    # Avoid double-counting [from web: ...] as local.
    local_sources = {s for s in local_sources if not s.lower().startswith("web:")}

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
    env = os.environ.get("RAIN_RUNTIME_TRACE_PATH")
    if env:
        return Path(env)
    return _library_path() / "meeting_archives" / "runtime_events.jsonl"


def _append_trace_line(payload: dict[str, Any]) -> None:
    path = _trace_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _trace_state(state: RuntimeState, **extra: Any) -> None:
    payload = {
        "timestamp": _utc_now(),
        "session_id": state.session_id,
        "status": state.status,
        "query": state.query,
        "mode": state.mode,
        "agent": state.agent,
        "events": [asdict(e) for e in state.events],
    }
    payload.update(extra)
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


def _call_llm_sync(messages: list[dict[str, str]], timeout_s: float) -> str:
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError("openai package is required for run_rain_lab runtime") from exc

    client = openai.OpenAI(
        base_url=os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
        api_key=os.environ.get("LM_STUDIO_API_KEY", "lm-studio"),
        timeout=timeout_s,
    )
    response = client.chat.completions.create(
        model=os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct"),
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

    for attempt in range(config.llm_retries + 1):
        try:
            return await asyncio.to_thread(_call_llm_sync, messages, config.llm_timeout_s)
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


def runtime_healthcheck() -> dict[str, Any]:
    config = _load_runtime_config()
    library = _library_path()

    checks: dict[str, bool] = {
        "library_exists": library.exists(),
        "trace_dir_writable": False,
        "openai_importable": False,
    }

    try:
        import openai  # noqa: F401
        checks["openai_importable"] = True
    except Exception:
        checks["openai_importable"] = False

    try:
        trace_dir = _trace_log_path().parent
        trace_dir.mkdir(parents=True, exist_ok=True)
        checks["trace_dir_writable"] = os.access(trace_dir, os.W_OK)
    except Exception:
        checks["trace_dir_writable"] = False

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "config": asdict(config),
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


async def run_rain_lab(
    query: str,
    mode: str = "chat",
    agent: str | None = None,
    recursive_depth: int = 1,
) -> str:
    """Unified async runtime entrypoint for non-CLI gateways."""
    config = _load_runtime_config()
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
        },
    )

    if mode not in _VALID_MODES:
        state.status = "error"
        state.add_event("runtime_failed", {"error": f"Unsupported mode: {mode}"})
        _trace_state(state)
        return "R.A.I.N. runtime error: unsupported mode. Use 'chat' or 'rlm'."

    if not safe_query:
        state.status = "error"
        state.add_event("runtime_failed", {"error": "Empty query after sanitization"})
        _trace_state(state)
        return "R.A.I.N. runtime error: query is empty after sanitization."

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
        state.status = "error"
        state.add_event("runtime_failed", {"error": str(exc)})
        _trace_state(state)
        return "R.A.I.N. runtime error: unable to generate response."

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
    parser.add_argument("--library", type=str, default=None, help="Override JAMES_LIBRARY_PATH")
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
        if status:
            return 1

    lower = body.lower()
    if "grounding policy blocked" in lower:
        return 2
    if "runtime error" in lower:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_cli_args(argv)
    query = (args.query or args.topic or "").strip()
    if not query:
        print("R.A.I.N. runtime error: provide --topic or --query.")
        return 2

    if args.library:
        os.environ["JAMES_LIBRARY_PATH"] = args.library

    try:
        output = asyncio.run(
            run_rain_lab(
                query=query,
                mode=args.mode,
                agent=args.agent,
                recursive_depth=max(1, int(args.recursive_depth)),
            )
        )
    except Exception:
        print("R.A.I.N. runtime error: unexpected runtime failure.")
        return 1

    print(output)
    return _cli_exit_code(output)


if __name__ == "__main__":
    raise SystemExit(main())
