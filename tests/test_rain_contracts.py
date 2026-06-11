"""Tests for the rain_contracts episodic schema and segmentation.

The golden lines below are duplicated in ``src/autonomy/episodic.rs`` tests;
if either side changes the wire format, both test suites must be updated
together.
"""

import json
from datetime import datetime, timezone

from rain_contracts.episodic import (
    EPISODIC_SCHEMA_VERSION,
    BehavioralState,
    Episode,
    EpisodicEventV2,
    segment_events,
)

# Mirrors the v1 fixture in src/autonomy/episodic.rs.
GOLDEN_V1_LINE = (
    '{"timestamp":"2026-06-09T12:00:00Z","agent_name":"R.A.I.N.Agent",'
    '"tool":"shell","args":{"cmd":"ls"},"sentence":"ran shell","duration_ms":40}'
)

# Mirrors the episode fixture in src/autonomy/episodic.rs.
GOLDEN_EPISODE_LINE = (
    '{"schema_version":2,"id":"ep-01","started_at":"2026-06-09T12:00:00Z",'
    '"ended_at":"2026-06-09T12:10:00Z","session_id":"session-1","channel":"telegram",'
    '"event_count":4,"summary":"4 events using file_read, shell.",'
    '"affect":{"valence":0.5,"arousal":0.0,"tags":["productive"]},"salience":0.4,'
    '"state_trace":[["thinking",60000],["idle",540000]],"ambient_digest":[],"interventions":[]}'
)


def event(
    ts: str,
    tool: str = "file_read",
    *,
    session: str | None = "session-1",
    channel: str | None = "telegram",
    state: BehavioralState | None = BehavioralState.THINKING,
    outcome: str | None = "success",
) -> EpisodicEventV2:
    return EpisodicEventV2(
        timestamp=ts,
        agent_name="R.A.I.N.Agent",
        tool=tool,
        args={},
        sentence=f"R.A.I.N.Agent ran tool '{tool}'",
        duration_ms=10,
        schema_version=EPISODIC_SCHEMA_VERSION,
        session_id=session,
        channel=channel,
        state=state,
        outcome=outcome,
    )


def ts_at(minute: int, second: int = 0) -> str:
    return datetime(2026, 6, 9, 12, minute, second, tzinfo=timezone.utc).isoformat()


class TestEventContract:
    def test_v1_golden_line_parses(self):
        ev = EpisodicEventV2.from_jsonl(GOLDEN_V1_LINE)
        assert ev.tool == "shell"
        assert ev.args == {"cmd": "ls"}
        assert ev.schema_version is None
        assert ev.state is None
        assert ev.outcome is None

    def test_v2_round_trip(self):
        ev = event(ts_at(0))
        parsed = EpisodicEventV2.from_jsonl(ev.to_jsonl())
        assert parsed == ev

    def test_unknown_keys_ignored(self):
        raw = json.loads(GOLDEN_V1_LINE)
        raw["some_v3_field"] = True
        ev = EpisodicEventV2.from_dict(raw)
        assert ev.tool == "shell"

    def test_absent_optionals_omitted_from_wire(self):
        ev = event(ts_at(0), session=None, channel=None, state=None, outcome=None)
        data = json.loads(ev.to_jsonl())
        assert "session_id" not in data
        assert "state" not in data
        assert "episode_id" not in data

    def test_state_round_trips_lowercase(self):
        ev = event(ts_at(0), state=BehavioralState.REMEDIATING)
        data = json.loads(ev.to_jsonl())
        assert data["state"] == "remediating"
        assert EpisodicEventV2.from_dict(data).state is BehavioralState.REMEDIATING


class TestEpisodeContract:
    def test_golden_episode_line_round_trips(self):
        ep = Episode.from_jsonl(GOLDEN_EPISODE_LINE)
        assert ep.event_count == 4
        assert ep.state_trace[0] == ("thinking", 60000)
        assert ep.affect.valence == 0.5

        # Re-serialized form parses identically (key order may differ).
        again = Episode.from_jsonl(ep.to_jsonl())
        assert again == ep


class TestSegmentation:
    def test_empty_stream_yields_no_episodes(self):
        assert segment_events([]) == []

    def test_contiguous_events_form_one_episode(self):
        events = [event(ts_at(i)) for i in range(5)]
        episodes = segment_events(events, gap_minutes=20)
        assert len(episodes) == 1
        assert episodes[0].event_count == 5
        assert episodes[0].session_id == "session-1"
        assert episodes[0].channel == "telegram"

    def test_temporal_gap_cuts_boundary(self):
        events = [event(ts_at(0)), event(ts_at(1)), event(ts_at(30))]
        episodes = segment_events(events, gap_minutes=20)
        assert [e.event_count for e in episodes] == [2, 1]

    def test_session_change_cuts_boundary(self):
        events = [
            event(ts_at(0)),
            event(ts_at(1), session="session-2"),
        ]
        episodes = segment_events(events, gap_minutes=20)
        assert len(episodes) == 2

    def test_incident_transition_cuts_boundary_both_ways(self):
        events = [
            event(ts_at(0), state=BehavioralState.THINKING),
            event(ts_at(1), state=BehavioralState.ALERT),
            event(ts_at(2), state=BehavioralState.REMEDIATING),
            event(ts_at(3), state=BehavioralState.IDLE),
        ]
        episodes = segment_events(events, gap_minutes=20)
        # thinking | alert+remediating | idle — the incident is its own episode.
        assert [e.event_count for e in episodes] == [1, 2, 1]
        assert "incident" in episodes[1].affect.tags

    def test_affect_valence_reflects_outcomes(self):
        all_good = segment_events([event(ts_at(i)) for i in range(4)])[0]
        assert all_good.affect.valence == 1.0

        all_bad = segment_events(
            [event(ts_at(i), outcome="failure") for i in range(4)]
        )[0]
        assert all_bad.affect.valence == -1.0
        assert "failures" in all_bad.affect.tags

    def test_salience_grows_with_failures_and_stays_bounded(self):
        calm = segment_events([event(ts_at(i)) for i in range(3)])[0]
        rough = segment_events(
            [event(ts_at(i), outcome="failure") for i in range(3)]
        )[0]
        assert rough.salience > calm.salience
        assert 0.0 <= calm.salience <= 1.0
        assert 0.0 <= rough.salience <= 1.0

    def test_summary_is_deterministic_and_names_tools(self):
        events = [event(ts_at(0)), event(ts_at(1), tool="shell")]
        a = segment_events(events)[0]
        b = segment_events(events)[0]
        assert a.summary == b.summary
        assert "file_read" in a.summary
        assert "shell" in a.summary

    def test_episode_lines_round_trip_through_jsonl(self):
        events = [
            event(ts_at(0)),
            event(ts_at(1), state=BehavioralState.ALERT, outcome="intervened"),
        ]
        for ep in segment_events(events):
            parsed = Episode.from_jsonl(ep.to_jsonl())
            assert parsed == ep


class TestIngestorAdoption:
    def test_ingestor_alias_parses_v1_and_v2(self):
        from episodic_memory_ingestor import EpisodicEvent

        v1 = EpisodicEvent.from_jsonl(GOLDEN_V1_LINE)
        assert v1.tool == "shell"
        v2 = EpisodicEvent.from_jsonl(event(ts_at(0)).to_jsonl())
        assert v2.state is BehavioralState.THINKING
