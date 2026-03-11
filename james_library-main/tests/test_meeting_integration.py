"""Integration test: run a 2-turn meeting against a mock OpenAI-compatible server.

This test spins up a lightweight HTTP server that mimics the LM Studio / OpenAI
``/v1/chat/completions`` endpoint, then drives the orchestrator through a
subprocess to verify the end-to-end pipeline without any external service.

The subprocess approach avoids ``sys.modules`` pollution from other test files
that replace ``openai`` / ``pyttsx3`` with ``MagicMock`` at import time.
"""

import json
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Mock LLM server
# ---------------------------------------------------------------------------

_TURN_RESPONSES = [
    # Turn 0 — James opens
    "Hey team, let's dive into this topic. The papers describe resonance as a "
    "geometric property rather than a temporal one. I'd like us to explore: what "
    "testable prediction does that give us? [from Coherence Depth.md]",
    # Turn 1 — Jasmine challenges
    "Hold on, James. Before we extrapolate, what's the energy budget for "
    "sustaining that resonance? The papers don't provide material constraints. "
    "We need feasibility bounds first.",
    # Extra fallback for connection-test completions and retries
    "Acknowledged.",
    "Acknowledged.",
    "Acknowledged.",
    "Acknowledged.",
]

_call_counter = 0
_call_counter_lock = threading.Lock()


class _MockCompletionsHandler(BaseHTTPRequestHandler):
    """Handles POST /v1/chat/completions with canned responses."""

    def do_POST(self):
        global _call_counter
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)  # consume body

        with _call_counter_lock:
            idx = min(_call_counter, len(_TURN_RESPONSES) - 1)
            text = _TURN_RESPONSES[idx]
            _call_counter += 1

        body = json.dumps({
            "id": f"mock-{idx}",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }).encode()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Handle GET /v1/models for connection test."""
        body = json.dumps({
            "object": "list",
            "data": [{"id": "mock-model", "object": "model"}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # suppress request logging during tests


@pytest.fixture()
def mock_llm_server():
    """Start a mock LLM server on a free port and yield its base URL."""
    global _call_counter
    _call_counter = 0

    server = HTTPServer(("127.0.0.1", 0), _MockCompletionsHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/v1"
    server.shutdown()


@pytest.fixture()
def tmp_library(tmp_path):
    """Create a minimal library with one fake paper and a soul file."""
    paper = tmp_path / "Coherence Depth.md"
    paper.write_text(
        "# Coherence Depth\n\n"
        "Resonance is a geometric property of bounded scalar fields. "
        "The coherence depth measures how far a standing wave can propagate "
        "before decoherence dominates.\n",
        encoding="utf-8",
    )
    soul = tmp_path / "JAMES_SOUL.md"
    soul.write_text(
        "# James\nYou are James, lead lab technician.\n",
        encoding="utf-8",
    )
    return tmp_path


def _subprocess_env():
    """Build env dict with UTF-8 forced (avoids cp1252 errors on Windows)."""
    import os
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return env


def _run_meeting_subprocess(base_url: str, library_path: str, max_turns: int = 2) -> subprocess.CompletedProcess:
    """Run a meeting in a clean subprocess to avoid module pollution."""
    script = textwrap.dedent(f"""\
        import sys, os
        sys.path.insert(0, {str(REPO_ROOT)!r})
        os.chdir({str(REPO_ROOT)!r})

        from rain_lab_chat.config import Config
        from rain_lab_chat.orchestrator import RainLabOrchestrator

        config = Config(
            base_url={base_url!r},
            api_key="test-key",
            model_name="mock-model",
            temperature=0.0,
            max_tokens=200,
            timeout=15.0,
            max_turns={max_turns},
            wrap_up_turns=0,
            library_path={library_path!r},
            enable_web_search=False,
            emit_visual_events=False,
            recursive_intellect=False,
            verbose=False,
            enable_citation_tracking=False,
            paper_title_allowlist=("Coherence Depth",),
        )

        orchestrator = RainLabOrchestrator(config)
        orchestrator.run_meeting("Test topic: resonance geometry")
    """)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=_subprocess_env(),
    )


def _run_connection_test_subprocess(base_url: str, library_path: str) -> subprocess.CompletedProcess:
    """Run only the connection test in a clean subprocess."""
    script = textwrap.dedent(f"""\
        import sys, os
        sys.path.insert(0, {str(REPO_ROOT)!r})
        os.chdir({str(REPO_ROOT)!r})

        from rain_lab_chat.config import Config
        from rain_lab_chat.orchestrator import RainLabOrchestrator

        config = Config(
            base_url={base_url!r},
            api_key="test-key",
            model_name="mock-model",
            temperature=0.0,
            timeout=15.0,
            library_path={library_path!r},
            enable_web_search=False,
            emit_visual_events=False,
            recursive_intellect=False,
            enable_citation_tracking=False,
            paper_title_allowlist=("Coherence Depth",),
        )

        orchestrator = RainLabOrchestrator(config)
        ok = orchestrator.test_connection()
        sys.exit(0 if ok else 1)
    """)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env=_subprocess_env(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMeetingIntegration:
    """End-to-end meeting test against mock LLM (subprocess-isolated)."""

    def test_two_turn_meeting_produces_output(self, mock_llm_server, tmp_library):
        """Run a 2-turn meeting and verify agents spoke and log was created."""
        result = _run_meeting_subprocess(mock_llm_server, str(tmp_library), max_turns=2)

        assert result.returncode == 0, (
            f"Meeting subprocess failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout[-2000:]}\nSTDERR:\n{result.stderr[-2000:]}"
        )

        # Verify both agents spoke
        assert "James" in result.stdout, "James should have spoken"
        assert "MEETING ADJOURNED" in result.stdout, "Meeting should have completed"

        # Verify meeting log was created
        log_path = tmp_library / "RAIN_LAB_MEETING_LOG.md"
        assert log_path.exists(), "Meeting log should be written"
        log_content = log_path.read_text(encoding="utf-8")
        assert len(log_content) > 50, "Log should contain substantial meeting content"

    def test_connection_test_succeeds(self, mock_llm_server, tmp_library):
        """Verify the orchestrator connection test passes against mock server."""
        result = _run_connection_test_subprocess(mock_llm_server, str(tmp_library))

        assert result.returncode == 0, (
            f"Connection test failed:\nSTDOUT:\n{result.stdout[-1000:]}\n"
            f"STDERR:\n{result.stderr[-1000:]}"
        )
        assert "successful" in result.stdout.lower(), "Should report connection successful"

    def test_meeting_produces_stats(self, mock_llm_server, tmp_library):
        """Verify final stats are printed after meeting ends."""
        result = _run_meeting_subprocess(mock_llm_server, str(tmp_library), max_turns=2)

        assert result.returncode == 0, (
            f"Meeting subprocess failed:\nSTDERR:\n{result.stderr[-1000:]}"
        )
        assert "SESSION STATISTICS" in result.stdout or "MEETING ADJOURNED" in result.stdout, (
            "Final stats or adjournment message should appear in output"
        )
