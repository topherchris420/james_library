"""Tests for rain_bridge_protocol and rain_bridge_server."""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import rain_bridge_protocol as proto

# ═══════════════════════════════════════════════════════════════════
# Protocol tests
# ═══════════════════════════════════════════════════════════════════


class TestProtocolEvents:
    """Verify that protocol helpers produce well-formed JSON events."""

    def test_meeting_started(self):
        ev = proto.meeting_started("quantum resonance", ["James", "Jasmine"], 5, meeting_id="abc123")
        assert ev["type"] == proto.MEETING_STARTED
        assert ev["topic"] == "quantum resonance"
        assert ev["agents"] == ["James", "Jasmine"]
        assert ev["paper_count"] == 5
        assert ev["meeting_id"] == "abc123"
        assert "timestamp" in ev

    def test_meeting_started_auto_id(self):
        ev = proto.meeting_started("topic", ["A"], 0)
        assert len(ev["meeting_id"]) == 12  # uuid hex[:12]

    def test_meeting_ended(self):
        ev = proto.meeting_ended("abc", "topic", 10, stats={"citations": 5})
        assert ev["type"] == proto.MEETING_ENDED
        assert ev["turn_count"] == 10
        assert ev["stats"]["citations"] == 5

    def test_meeting_error(self):
        ev = proto.meeting_error("abc", "something broke")
        assert ev["type"] == proto.MEETING_ERROR
        assert ev["message"] == "something broke"

    def test_agent_thinking(self):
        ev = proto.agent_thinking("abc", "James", 3)
        assert ev["type"] == proto.AGENT_THINKING
        assert ev["agent_id"] == "james"
        assert ev["turn"] == 3

    def test_agent_utterance(self):
        ev = proto.agent_utterance("abc", "Jasmine", "Great point!", 2)
        assert ev["type"] == proto.AGENT_UTTERANCE
        assert ev["text"] == "Great point!"
        assert ev["citations"] == []

    def test_agent_utterance_with_citations(self):
        cites = [{"quote": "E=mc²", "source": "paper.md"}]
        ev = proto.agent_utterance("abc", "Elena", "text", 1, citations=cites)
        assert len(ev["citations"]) == 1

    def test_citation_verified(self):
        ev = proto.citation_verified("abc", "Luca", "some quote", "paper.md")
        assert ev["type"] == proto.CITATION_VERIFIED
        assert ev["source"] == "paper.md"

    def test_web_search_result(self):
        ev = proto.web_search_result("abc", "quantum", 5)
        assert ev["type"] == proto.WEB_SEARCH_RESULT
        assert ev["result_count"] == 5

    def test_meeting_status_idle(self):
        ev = proto.meeting_status("idle")
        assert ev["state"] == "idle"
        assert ev["meeting_id"] is None

    def test_meeting_status_running(self):
        ev = proto.meeting_status("running", meeting_id="x", topic="t", turn=3, agents=["A"])
        assert ev["state"] == "running"
        assert ev["agents"] == ["A"]

    def test_all_events_are_json_serializable(self):
        """Every protocol event must round-trip through JSON."""
        events = [
            proto.meeting_started("t", ["A"], 1),
            proto.meeting_ended("x", "t", 5),
            proto.meeting_error("x", "err"),
            proto.agent_thinking("x", "A", 0),
            proto.agent_utterance("x", "A", "hi", 0),
            proto.citation_verified("x", "A", "q", "s"),
            proto.web_search_result("x", "q", 3),
            proto.meeting_status("idle"),
        ]
        for ev in events:
            roundtripped = json.loads(json.dumps(ev))
            assert roundtripped["type"] == ev["type"]


# ═══════════════════════════════════════════════════════════════════
# Bridge server tests
# ═══════════════════════════════════════════════════════════════════

from http.server import HTTPServer

from rain_bridge_server import BridgeHandler, MeetingRunner


@pytest.fixture()
def bridge_server():
    """Start a bridge server on a random port in a background thread."""
    server = HTTPServer(("127.0.0.1", 0), BridgeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def _post(url: str, data: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestBridgeServer:
    """Integration tests for the HTTP bridge server."""

    def test_health_endpoint(self, bridge_server):
        result = _get(f"{bridge_server}/health")
        assert result["status"] == "ok"

    def test_status_idle(self, bridge_server):
        result = _get(f"{bridge_server}/meeting/status")
        assert result["state"] == "idle"
        assert result["meeting_id"] is None

    def test_start_requires_topic(self, bridge_server):
        code, result = _post(f"{bridge_server}/meeting/start", {})
        assert code == 400
        assert "topic" in result["error"]

    def test_404_on_unknown_route(self, bridge_server):
        code, result = _post(f"{bridge_server}/nonexistent", {})
        assert code == 404


class TestMeetingRunner:
    """Unit tests for MeetingRunner state machine."""

    def test_initial_state_is_idle(self):
        runner = MeetingRunner()
        assert runner.state == "idle"

    def test_status_returns_protocol_event(self):
        runner = MeetingRunner()
        status = runner.status()
        assert status["type"] == proto.MEETING_STATUS
        assert status["state"] == "idle"

    def test_stop_when_idle_returns_error(self):
        runner = MeetingRunner()
        result = runner.stop()
        assert "error" in result

    def test_drain_events_empty(self):
        runner = MeetingRunner()
        assert runner.drain_events() == []

    def test_double_start_returns_error(self):
        runner = MeetingRunner()
        # Monkey-patch _run to block briefly so state stays "running"
        original_run = runner._run

        def slow_run(topic, overrides):
            time.sleep(2)

        runner._run = slow_run
        result1 = runner.start("topic1")
        assert "meeting_id" in result1

        # Second start should fail while first is running
        result2 = runner.start("topic2")
        assert "error" in result2

        # Cleanup
        runner.stop()
        time.sleep(0.1)
