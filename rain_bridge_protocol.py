"""Shared event protocol for the Rust↔Python bridge.

Every event flowing between the ZeroClaw Rust gateway and the
rain_lab_chat Python orchestrator is a JSON object with at least::

    {"type": "<event_type>", "timestamp": "<ISO-8601>"}

This module provides helpers for constructing those events from
Python and constants that keep both sides in sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ── Event type constants ─────────────────────────────────────────
# These MUST match the Rust enum variants in src/gateway/meeting.rs

# Lifecycle
MEETING_STARTED = "meeting_started"
MEETING_ENDED = "meeting_ended"
MEETING_ERROR = "meeting_error"

# Per-turn
AGENT_THINKING = "agent_thinking"
AGENT_UTTERANCE = "agent_utterance"

# Enrichment
CITATION_VERIFIED = "citation_verified"
WEB_SEARCH_RESULT = "web_search_result"

# Control (Rust → Python)
MEETING_START_CMD = "meeting_start"
MEETING_STOP_CMD = "meeting_stop"

# Status
MEETING_STATUS = "meeting_status"


# ── Helpers ──────────────────────────────────────────────────────

def _ts() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _base(event_type: str, **extra: Any) -> Dict[str, Any]:
    ev: Dict[str, Any] = {"type": event_type, "timestamp": _ts()}
    ev.update(extra)
    return ev


# ── Lifecycle events ─────────────────────────────────────────────

def meeting_started(
    topic: str,
    agents: List[str],
    paper_count: int,
    meeting_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _base(
        MEETING_STARTED,
        meeting_id=meeting_id or uuid.uuid4().hex[:12],
        topic=topic,
        agents=agents,
        paper_count=paper_count,
    )


def meeting_ended(
    meeting_id: str,
    topic: str,
    turn_count: int,
    stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return _base(
        MEETING_ENDED,
        meeting_id=meeting_id,
        topic=topic,
        turn_count=turn_count,
        stats=stats or {},
    )


def meeting_error(
    meeting_id: str,
    message: str,
) -> Dict[str, Any]:
    return _base(MEETING_ERROR, meeting_id=meeting_id, message=message)


# ── Per-turn events ──────────────────────────────────────────────

def agent_thinking(
    meeting_id: str,
    agent_name: str,
    turn: int,
) -> Dict[str, Any]:
    return _base(
        AGENT_THINKING,
        meeting_id=meeting_id,
        agent_name=agent_name,
        agent_id=agent_name.lower(),
        turn=turn,
    )


def agent_utterance(
    meeting_id: str,
    agent_name: str,
    text: str,
    turn: int,
    citations: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    return _base(
        AGENT_UTTERANCE,
        meeting_id=meeting_id,
        agent_name=agent_name,
        agent_id=agent_name.lower(),
        text=text,
        turn=turn,
        citations=citations or [],
    )


# ── Enrichment events ───────────────────────────────────────────

def citation_verified(
    meeting_id: str,
    agent_name: str,
    quote: str,
    source: str,
) -> Dict[str, Any]:
    return _base(
        CITATION_VERIFIED,
        meeting_id=meeting_id,
        agent_name=agent_name,
        quote=quote,
        source=source,
    )


def web_search_result(
    meeting_id: str,
    query: str,
    result_count: int,
) -> Dict[str, Any]:
    return _base(
        WEB_SEARCH_RESULT,
        meeting_id=meeting_id,
        query=query,
        result_count=result_count,
    )


# ── Status ───────────────────────────────────────────────────────

def meeting_status(
    state: str,
    meeting_id: Optional[str] = None,
    topic: Optional[str] = None,
    turn: int = 0,
    agents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """``state`` is one of: ``idle``, ``running``, ``stopping``."""
    return _base(
        MEETING_STATUS,
        state=state,
        meeting_id=meeting_id,
        topic=topic,
        turn=turn,
        agents=agents or [],
    )
