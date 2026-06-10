"""Tests for the autonomy supervisor's synchronous cores."""

import json
from datetime import datetime, timedelta, timezone

from autonomy_supervisor import incident_alerts, segment_new_events, tail_jsonl
from rain_contracts.episodic import Episode, EpisodicEventV2


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def event_line(ts: datetime, tool: str = "file_read") -> str:
    return EpisodicEventV2(
        timestamp=ts.isoformat(),
        agent_name="R.A.I.N.Agent",
        tool=tool,
        args={},
        sentence=f"R.A.I.N.Agent ran tool '{tool}'",
        duration_ms=5,
        schema_version=2,
        session_id="session-1",
        channel="cli",
        outcome="success",
    ).to_jsonl()


class TestTailJsonl:
    def test_reads_appended_lines_and_resumes_from_offset(self, tmp_path):
        path = tmp_path / "stream.jsonl"
        write_lines(path, ['{"n":1}', '{"n":2}'])
        records, offset = tail_jsonl(path, 0)
        assert [r["n"] for r in records] == [1, 2]

        write_lines(path, ['{"n":3}'])
        records, offset = tail_jsonl(path, offset)
        assert [r["n"] for r in records] == [3]

        # No new data: nothing returned, offset stable.
        again, offset2 = tail_jsonl(path, offset)
        assert again == []
        assert offset2 == offset

    def test_partial_trailing_line_is_retried_not_lost(self, tmp_path):
        path = tmp_path / "stream.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"n":1}\n{"n":2')  # writer interrupted mid-append
        records, offset = tail_jsonl(path, 0)
        assert [r["n"] for r in records] == [1]

        with open(path, "a", encoding="utf-8") as f:
            f.write("}\n")
        records, _ = tail_jsonl(path, offset)
        assert [r["n"] for r in records] == [2]

    def test_missing_file_returns_empty(self, tmp_path):
        records, offset = tail_jsonl(tmp_path / "absent.jsonl", 0)
        assert records == []
        assert offset == 0


class TestIncidentAlerts:
    def test_alerts_only_on_incident_states(self):
        snapshots = [
            {"state": "idle", "cause": "startup"},
            {"state": "thinking", "cause": "turn"},
            {"state": "alert", "cause": "stagnation", "remediation_attempts": 1},
            {"state": "remediating", "cause": "plan", "remediation_attempts": 1},
        ]
        alerts = incident_alerts(snapshots)
        assert len(alerts) == 2
        assert "entered alert: stagnation" in alerts[0]
        assert "entered remediating" in alerts[1]


class TestSegmentNewEvents:
    def test_writes_closed_episodes_and_is_idempotent(self, tmp_path):
        events = tmp_path / "episodic_events.jsonl"
        episodes = tmp_path / "episodes.jsonl"
        offset = tmp_path / ".segmenter_offset"
        base = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        now = base + timedelta(hours=2)

        # Two bursts separated by a >gap pause; both long closed by `now`.
        write_lines(
            events,
            [event_line(base + timedelta(minutes=i)) for i in range(3)]
            + [event_line(base + timedelta(minutes=60 + i)) for i in range(2)],
        )

        written = segment_new_events(events, episodes, offset, gap_minutes=20, now=now)
        assert written == 2

        parsed = [Episode.from_jsonl(line) for line in episodes.read_text().splitlines()]
        assert [e.event_count for e in parsed] == [3, 2]

        # Second pass with no new events: nothing duplicated.
        assert segment_new_events(events, episodes, offset, gap_minutes=20, now=now) == 0
        assert len(episodes.read_text().splitlines()) == 2

    def test_open_trailing_episode_is_held_back(self, tmp_path):
        events = tmp_path / "episodic_events.jsonl"
        episodes = tmp_path / "episodes.jsonl"
        offset = tmp_path / ".segmenter_offset"
        base = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)

        # Burst still in progress: last event 5 minutes before `now`.
        write_lines(events, [event_line(base + timedelta(minutes=i)) for i in range(3)])
        now = base + timedelta(minutes=7)

        assert segment_new_events(events, episodes, offset, gap_minutes=20, now=now) == 0
        assert not episodes.exists()

        # Session continues, then goes quiet long enough to close.
        write_lines(events, [event_line(base + timedelta(minutes=8))])
        later = base + timedelta(minutes=60)
        assert segment_new_events(events, episodes, offset, gap_minutes=20, now=later) == 1

        parsed = [Episode.from_jsonl(line) for line in episodes.read_text().splitlines()]
        assert parsed[0].event_count == 4, "held-back events join the closed episode"

    def test_malformed_lines_are_skipped(self, tmp_path):
        events = tmp_path / "episodic_events.jsonl"
        episodes = tmp_path / "episodes.jsonl"
        offset = tmp_path / ".segmenter_offset"
        base = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)

        write_lines(events, [event_line(base), "{not json", event_line(base + timedelta(minutes=1))])
        now = base + timedelta(hours=1)
        assert segment_new_events(events, episodes, offset, gap_minutes=20, now=now) == 1

        parsed = [Episode.from_jsonl(line) for line in episodes.read_text().splitlines()]
        assert parsed[0].event_count == 2


def test_json_state_snapshot_lines_match_rust_writer_schema():
    # Mirrors BehavioralStateSnapshot in src/autonomy/state.rs.
    line = (
        '{"schema_version":1,"state":"alert","since":"2026-06-09T12:00:00Z",'
        '"trigger":"vitals_escalated","cause":"stagnation","remediation_attempts":1}'
    )
    snap = json.loads(line)
    assert incident_alerts([snap]) == [
        "R.A.I.N._runtime entered alert: stagnation (remediation attempts: 1)"
    ]
