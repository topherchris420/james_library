import json
from pathlib import Path
from types import SimpleNamespace

import james_library.utilities.session_replay as replay_module
from james_library.utilities.session_replay import run_replay

TOPIC = "Could acoustic interference patterns guide molecular assembly the way DNA guides cell growth?"


def _gold_case() -> dict[str, object]:
    return {
        "id": "case-1",
        "topic": TOPIC,
        "min_grounded_turn_ratio": 0.5,
        "require_disagreement": True,
        "min_actionability_score": 0.5,
    }


def _artifact_payload() -> dict[str, object]:
    return {
        "schema_version": "rain-session-artifact/v1",
        "session_id": "case-1",
        "status": "completed",
        "topic": TOPIC,
        "model": "fake-model",
        "recursive_depth": 1,
        "started_at": "2026-04-13T00:00:00Z",
        "completed_at": "2026-04-13T00:01:00Z",
        "library_path": ".",
        "log_path": "./meeting.log",
        "loaded_papers_count": 1,
        "loaded_papers": ["paper.md"],
        "metrics": {"citation_accuracy": 0.9},
        "summary": "Next step: run the thermal numbers and compare against the 10 Âµm target.",
        "turns": [
            {
                "index": 1,
                "timestamp": "2026-04-13T00:00:01Z",
                "agent": "James",
                "content": (
                    "I disagree with the optimistic framing, but the cited paper "
                    "keeps the mechanism plausible."
                ),
                "metadata": {
                    "verified_count": 1,
                    "unverified_count": 0,
                    "citation_rate": 1.0,
                },
                "grounded_response": {
                    "answer": (
                        "I disagree with the optimistic framing, but the cited "
                        "paper keeps the mechanism plausible."
                    ),
                    "confidence": 0.8,
                    "provenance": ["paper.md"],
                    "evidence": [{"source": "paper.md", "quote": "quoted evidence"}],
                    "repro_steps": ["inspect artifact"],
                    "grounded": True,
                    "red_badge": False,
                },
            }
        ],
    }


def test_run_replay_executes_cases_collects_artifacts_and_writes_report(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    report_dir = tmp_path / "reports"
    gold_path = tmp_path / "gold.json"
    emitter_path = tmp_path / "emit_artifact.py"

    gold_path.write_text(json.dumps([_gold_case()]), encoding="utf-8")

    emitter_path.write_text(
        "\n".join(
            [
                "import argparse, json",
                "from pathlib import Path",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--artifact-dir', required=True)",
                "parser.add_argument('--case-id', required=True)",
                "parser.add_argument('--topic', required=True)",
                "args = parser.parse_args()",
                "artifact_dir = Path(args.artifact_dir)",
                "artifact_dir.mkdir(parents=True, exist_ok=True)",
                "payload = " + repr(_artifact_payload()),
                "payload['session_id'] = args.case_id",
                "payload['topic'] = args.topic",
                "path = artifact_dir / f'session_{args.case_id}.json'",
                "path.write_text(json.dumps(payload), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )

    command_template = (
        f'python "{emitter_path}" --artifact-dir "{{artifact_dir}}" '
        f'--case-id "{{case_id}}" --topic "{{topic}}"'
    )
    result = run_replay(
        gold_path=gold_path,
        artifact_dir=artifact_dir,
        report_dir=report_dir,
        command_template=command_template,
        library_path=tmp_path,
    )

    assert result["summary"]["cases_run"] == 1
    assert result["eval"]["summary"]["passing_cases"] == 1
    assert Path(result["report_path"]).exists()
    assert result["cases"][0]["artifact_path"].endswith("session_case-1.json")


def test_run_replay_tolerates_missing_decoded_stdout(tmp_path: Path, monkeypatch) -> None:
    artifact_dir = tmp_path / "artifacts"
    report_dir = tmp_path / "reports"
    gold_path = tmp_path / "gold.json"

    gold_path.write_text(json.dumps([_gold_case()]), encoding="utf-8")

    def _fake_run(*args, **kwargs):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "session_case-1.json").write_text(
            json.dumps(_artifact_payload()),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    monkeypatch.setattr(replay_module.subprocess, "run", _fake_run)

    result = run_replay(
        gold_path=gold_path,
        artifact_dir=artifact_dir,
        report_dir=report_dir,
        command_template="ignored",
        library_path=tmp_path,
    )

    assert result["cases"][0]["stdout_tail"] == ""
    assert result["cases"][0]["stderr_tail"] == ""
