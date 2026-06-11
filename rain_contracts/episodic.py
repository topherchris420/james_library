"""Episodic memory contracts — Python mirror of ``src/autonomy/episodic.rs``.

Wire compatibility contract (both languages):
  - v2 only adds optional fields to the v1 ``episodic_events.jsonl`` line
    schema, so v1 readers and writers keep working.
  - Unknown keys are ignored on read; missing optional keys default to None.
  - Single writer per file: Rust appends events, Python appends episodes.

Stdlib only — no third-party dependencies.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum

EPISODIC_SCHEMA_VERSION = 2


class BehavioralState(str, Enum):
    """Mirror of the Rust ``BehavioralState`` enum (lowercase wire values)."""

    IDLE = "idle"
    THINKING = "thinking"
    ALERT = "alert"
    REMEDIATING = "remediating"

    @property
    def is_incident(self) -> bool:
        """Alert/Remediating mark incident time: segmentation boundaries."""
        return self in (BehavioralState.ALERT, BehavioralState.REMEDIATING)


def _parse_timestamp(value: str) -> datetime | None:
    """Parse an RFC 3339 timestamp, tolerating a trailing 'Z'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(slots=True)
class EpisodicEventV2:
    """One raw episodic event (one JSONL line).

    The first six fields are the v1 wire schema; the rest are optional v2
    additions. Writers should keep ``args`` empty or redacted: raw arguments
    can carry sensitive payloads and the stream is plaintext.
    """

    # v1 fields (wire-required)
    timestamp: str
    agent_name: str
    tool: str
    args: dict
    sentence: str
    duration_ms: int
    # v2 optional additions
    schema_version: int | None = None
    episode_id: str | None = None
    session_id: str | None = None
    channel: str | None = None
    state: BehavioralState | None = None
    outcome: str | None = None  # "success" | "failure" | "intervened"

    def to_jsonl(self) -> str:
        data = {k: v for k, v in asdict(self).items() if v is not None}
        if isinstance(data.get("state"), BehavioralState):
            data["state"] = data["state"].value
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, raw: dict) -> EpisodicEventV2:
        """Build from a decoded JSON object, ignoring unknown keys and
        defaulting missing optional keys (forward/backward compatible)."""
        state = raw.get("state")
        known = {
            "timestamp": str(raw.get("timestamp", "")),
            "agent_name": str(raw.get("agent_name", "unknown")),
            "tool": str(raw.get("tool", "unknown")),
            "args": raw.get("args") if isinstance(raw.get("args"), dict) else {},
            "sentence": str(raw.get("sentence", "")),
            "duration_ms": int(raw.get("duration_ms", 0) or 0),
            "schema_version": raw.get("schema_version"),
            "episode_id": raw.get("episode_id"),
            "session_id": raw.get("session_id"),
            "channel": raw.get("channel"),
            "state": BehavioralState(state) if state else None,
            "outcome": raw.get("outcome"),
        }
        return cls(**known)

    @classmethod
    def from_jsonl(cls, line: str) -> EpisodicEventV2:
        return cls.from_dict(json.loads(line))

    def parsed_timestamp(self) -> datetime | None:
        return _parse_timestamp(self.timestamp)


@dataclass(slots=True)
class AffectTrace:
    """Behavioral/affect trace for alignment retrieval."""

    valence: float = 0.0  # -1.0 (failing) .. +1.0 (succeeding)
    arousal: float = 0.0  # 0.0 (calm) .. 1.0 (alert/remediating)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Episode:
    """A segmented episode (one line of ``episodes.jsonl``)."""

    schema_version: int
    id: str
    started_at: str
    ended_at: str
    event_count: int
    summary: str
    affect: AffectTrace
    salience: float
    state_trace: list[tuple[str, int]] = field(default_factory=list)
    ambient_digest: list[str] = field(default_factory=list)
    interventions: list[str] = field(default_factory=list)
    session_id: str | None = None
    channel: str | None = None

    def to_jsonl(self) -> str:
        data = asdict(self)
        data["affect"] = asdict(self.affect) if isinstance(self.affect, AffectTrace) else self.affect
        data["state_trace"] = [[state, ms] for state, ms in self.state_trace]
        data = {k: v for k, v in data.items() if v is not None}
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, raw: dict) -> Episode:
        affect_raw = raw.get("affect") or {}
        affect = AffectTrace(
            valence=float(affect_raw.get("valence", 0.0)),
            arousal=float(affect_raw.get("arousal", 0.0)),
            tags=list(affect_raw.get("tags", [])),
        )
        return cls(
            schema_version=int(raw.get("schema_version", EPISODIC_SCHEMA_VERSION)),
            id=str(raw.get("id", "")),
            started_at=str(raw.get("started_at", "")),
            ended_at=str(raw.get("ended_at", "")),
            event_count=int(raw.get("event_count", 0)),
            summary=str(raw.get("summary", "")),
            affect=affect,
            salience=float(raw.get("salience", 0.0)),
            state_trace=[(str(s), int(ms)) for s, ms in raw.get("state_trace", [])],
            ambient_digest=list(raw.get("ambient_digest", [])),
            interventions=list(raw.get("interventions", [])),
            session_id=raw.get("session_id"),
            channel=raw.get("channel"),
        )

    @classmethod
    def from_jsonl(cls, line: str) -> Episode:
        return cls.from_dict(json.loads(line))


# ── Segmentation ─────────────────────────────────────────────────


def _is_boundary(prev: EpisodicEventV2, current: EpisodicEventV2, gap: timedelta) -> bool:
    """An episode closes before ``current`` when any boundary fires:
    temporal gap, session/channel change, or an incident-state transition
    (entering or leaving alert/remediating)."""
    prev_ts = prev.parsed_timestamp()
    cur_ts = current.parsed_timestamp()
    if prev_ts is not None and cur_ts is not None and cur_ts - prev_ts > gap:
        return True
    if prev.session_id != current.session_id or prev.channel != current.channel:
        return True
    prev_incident = prev.state.is_incident if prev.state else False
    cur_incident = current.state.is_incident if current.state else False
    return prev_incident != cur_incident


def _build_episode(events: list[EpisodicEventV2]) -> Episode:
    first, last = events[0], events[-1]
    count = len(events)

    # Deterministic heuristic summary (an LLM summary can replace this later
    # without changing the schema).
    tool_counts: dict[str, int] = {}
    failures = 0
    interventions: list[str] = []
    for ev in events:
        tool_counts[ev.tool] = tool_counts.get(ev.tool, 0) + 1
        if ev.outcome == "failure":
            failures += 1
        elif ev.outcome == "intervened":
            interventions.append(ev.sentence)
    top_tools = sorted(tool_counts, key=lambda t: (-tool_counts[t], t))[:3]
    summary = (
        f"{count} event(s) from {first.timestamp} to {last.timestamp}"
        f"{f' on {first.channel}' if first.channel else ''}"
        f" using {', '.join(top_tools)}; {failures} failure(s)."
    )

    # State trace: consecutive same-state runs with durations from timestamps.
    state_trace: list[tuple[str, int]] = []
    incident_ms = 0
    run_state: str | None = None
    run_start: datetime | None = None
    for ev in events:
        ts = ev.parsed_timestamp()
        state = ev.state.value if ev.state else None
        if state != run_state:
            if run_state is not None and run_start is not None and ts is not None:
                ms = max(int((ts - run_start).total_seconds() * 1000), 0)
                state_trace.append((run_state, ms))
                if BehavioralState(run_state).is_incident:
                    incident_ms += ms
            run_state, run_start = state, ts
    if run_state is not None:
        state_trace.append((run_state, 0))

    # Affect heuristics, documented and deterministic:
    # valence — net success ratio; interventions weigh double.
    outcomes = [ev.outcome for ev in events if ev.outcome]
    if outcomes:
        score = sum(
            1 if o == "success" else -1 if o == "failure" else -2 for o in outcomes
        )
        valence = max(-1.0, min(1.0, score / len(outcomes)))
    else:
        valence = 0.0
    # arousal — fraction of events observed in an incident state.
    stated = [ev for ev in events if ev.state]
    arousal = (
        sum(1 for ev in stated if ev.state and ev.state.is_incident) / len(stated)
        if stated
        else 0.0
    )
    tags = []
    if failures:
        tags.append("failures")
    if interventions:
        tags.append("intervened")
    if arousal > 0.0:
        tags.append("incident")

    # Salience — bounded blend of size, failure pressure, and incident time.
    failure_fraction = failures / count
    salience = min(1.0, 0.2 + 0.02 * count + 0.3 * failure_fraction + 0.3 * arousal)

    return Episode(
        schema_version=EPISODIC_SCHEMA_VERSION,
        id=f"ep-{uuid.uuid4().hex[:12]}",
        started_at=first.timestamp,
        ended_at=last.timestamp,
        event_count=count,
        summary=summary,
        affect=AffectTrace(valence=round(valence, 4), arousal=round(arousal, 4), tags=tags),
        salience=round(salience, 4),
        state_trace=state_trace,
        interventions=interventions,
        session_id=first.session_id,
        channel=first.channel,
    )


def segment_events(
    events: list[EpisodicEventV2],
    *,
    gap_minutes: int = 20,
) -> list[Episode]:
    """Group a chronological event stream into episodes.

    Boundaries (design doc §3.3): temporal gap > ``gap_minutes``,
    session/channel change, and incident-state transitions. Embedding-drift
    segmentation is deliberately out of scope until embeddings are wired in.
    """
    if not events:
        return []
    gap = timedelta(minutes=gap_minutes)
    episodes: list[Episode] = []
    current: list[EpisodicEventV2] = [events[0]]
    for prev, ev in zip(events, events[1:]):
        if _is_boundary(prev, ev, gap):
            episodes.append(_build_episode(current))
            current = [ev]
        else:
            current.append(ev)
    episodes.append(_build_episode(current))
    return episodes
