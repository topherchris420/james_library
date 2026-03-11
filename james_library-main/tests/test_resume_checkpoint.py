import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rain_lab_chat.logging_events import parse_log_for_resume


def test_parse_checkpoint_for_resume(tmp_path):
    checkpoint_path = tmp_path / "resume_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "rain_lab_checkpoint",
                "topic": "Resonance geometry",
                "turn_count": 4,
                "history": [
                    "James: Opening thought.",
                    "FOUNDER: Push harder on feasibility.",
                    "Luca: Let's test a geometric constraint.",
                ],
                "citation_counts": {"James": 2, "Luca": 1},
                "metrics_state": {"turn_count": 4, "all_quotes": ["x"]},
                "status": "running",
            }
        ),
        encoding="utf-8",
    )

    data = parse_log_for_resume(str(checkpoint_path))

    assert data["source"] == "checkpoint"
    assert data["topic"] == "Resonance geometry"
    assert data["turn_count"] == 4
    assert data["history"][1] == "FOUNDER: Push harder on feasibility."
    assert data["citation_counts"] == {"James": 2, "Luca": 1}
    assert data["metrics_state"]["turn_count"] == 4
    assert data["status"] == "running"
