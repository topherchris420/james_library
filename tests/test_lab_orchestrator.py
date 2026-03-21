import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lab"))

import orchestrator


def test_preview_text_uses_non_empty_lines():
    text = "\nfirst line\n\nsecond line\nthird line\n"
    assert orchestrator.preview_text(text) == "first line | second line | third line"


def test_run_experiments_reports_missing_runner(monkeypatch):
    monkeypatch.delenv("LAB_EXPERIMENT_CMD", raising=False)
    monkeypatch.setattr(orchestrator, "ROOT", Path("/tmp/zeroclaw-lab-test"))

    result = orchestrator.run_experiments({"prompt_variant": "v1"})

    assert result["returncode"] == 127
    assert result["command"] is None
    assert "LAB_EXPERIMENT_CMD" in result["stderr"]
    assert result["stderr_preview"] != "(no output)"
    assert result["score"] == orchestrator.score_run(result)


def test_evaluate_results_summarizes_successful_runs():
    outputs = [
        {
            "config": {"prompt_variant": "v1"},
            "returncode": 0,
            "stdout": "alpha insight\nbeta detail\n",
            "stderr": "",
            "duration_s": 0.25,
            "score": 120,
            "stdout_preview": "alpha insight | beta detail",
            "stderr_preview": "(no output)",
        },
        {
            "config": {"prompt_variant": "v2"},
            "returncode": 0,
            "stdout": "gamma result",
            "stderr": "",
            "duration_s": 0.5,
            "score": 140,
            "stdout_preview": "gamma result",
            "stderr_preview": "(no output)",
        },
    ]

    evaluation = orchestrator.evaluate_results(outputs)

    assert evaluation["success_count"] == 2
    assert evaluation["failure_count"] == 0
    assert evaluation["best_run"]["config"] == {"prompt_variant": "v2"}
    assert "2/2 experiment runs succeeded" in evaluation["summary"]
    assert "Best run: prompt_variant=v2" in evaluation["summary"]
    assert evaluation["highlights"][0]["config_label"] == "prompt_variant=v2"


def test_format_evaluation_report_includes_highlights():
    evaluation = {
        "total_runs": 1,
        "success_count": 0,
        "failure_count": 1,
        "score": -150,
        "summary": "1 experiment runs failed.",
        "best_run": {
            "config": {"prompt_variant": "v1"},
            "score": -150,
            "returncode": 1,
            "stdout_preview": "(no output)",
            "stderr_preview": "runner failed",
        },
        "highlights": [
            {
                "config": {"prompt_variant": "v1"},
                "config_label": "prompt_variant=v1",
                "status": "failed (1)",
                "score": -150,
                "duration_s": 0.1,
                "snippet": "runner failed",
            }
        ],
    }

    report = orchestrator.format_evaluation_report(evaluation)

    assert "Experiment evaluation:" in report
    assert "prompt_variant=v1 | failed (1)" in report
    assert "preview: runner failed" in report
