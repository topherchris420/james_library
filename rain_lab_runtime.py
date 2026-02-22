"""Unified async runtime for R.A.I.N. Lab integrations.

This module provides a stable async entrypoint used by gateways (e.g. Telegram)
with lightweight typed runtime state/events plus provenance extraction.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


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


_RE_LOCAL_SOURCE = re.compile(r"\[from\s+([^\]]+?)\]", re.IGNORECASE)
_RE_WEB_SOURCE = re.compile(r"\[from\s+web:\s*([^\]]+?)\]", re.IGNORECASE)
_RE_QUOTE = re.compile(r'"([^"]+)"')


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_agent_name(agent: Optional[str]) -> str:
    if not agent:
        return "James"
    cleaned = agent.strip().lower()
    mapping = {"james": "James", "jasmine": "Jasmine", "elena": "Elena", "luca": "Luca"}
    return mapping.get(cleaned, "James")


def _library_path() -> Path:
    default_path = Path(__file__).resolve().parent
    return Path(os.environ.get("JAMES_LIBRARY_PATH", str(default_path)))


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


async def run_rain_lab(
    query: str,
    mode: str = "chat",
    agent: str | None = None,
    recursive_depth: int = 1,
) -> str:
    """Unified async runtime entrypoint for non-CLI gateways."""
    resolved_agent = _safe_agent_name(agent)
    state = RuntimeState(
        session_id=str(uuid.uuid4())[:8],
        query=query,
        mode=mode,
        agent=resolved_agent,
    )
    state.add_event("runtime_started", {"mode": mode, "agent": resolved_agent})

    context_block, paper_list = _load_context()
    state.add_event("context_loaded", {"papers": len(paper_list), "chars": len(context_block)})

    messages = _build_messages(
        query=query,
        mode=mode,
        agent=resolved_agent,
        context_block=context_block,
        recursive_depth=max(1, int(recursive_depth)),
    )
    state.add_event("llm_request_prepared", {"message_count": len(messages)})

    try:
        response_text = await asyncio.to_thread(_call_llm_sync, messages, 120.0)
        state.status = "ok"
        state.add_event("llm_response_received", {"chars": len(response_text)})
    except Exception as exc:
        state.status = "error"
        state.add_event("runtime_failed", {"error": str(exc)})
        _append_trace_line(
            {
                "timestamp": _utc_now(),
                "session_id": state.session_id,
                "status": state.status,
                "query": query,
                "mode": mode,
                "agent": resolved_agent,
                "events": [asdict(e) for e in state.events],
            }
        )
        return "R.A.I.N. runtime error: unable to generate response."

    provenance = _extract_provenance(response_text)
    confidence = _confidence_score(response_text, provenance)
    state.add_event(
        "provenance_analyzed",
        {
            "sources": len(provenance),
            "confidence": confidence,
        },
    )

    _append_trace_line(
        {
            "timestamp": _utc_now(),
            "session_id": state.session_id,
            "status": state.status,
            "query": query,
            "mode": mode,
            "agent": resolved_agent,
            "confidence": confidence,
            "provenance": [asdict(p) for p in provenance],
            "events": [asdict(e) for e in state.events],
        }
    )

    if provenance:
        sources = ", ".join(sorted({p.source for p in provenance})[:3])
        return f"{response_text}\n\nProvenance: {sources}\nConfidence: {confidence:.2f}"
    return f"{response_text}\n\nConfidence: {confidence:.2f}"
