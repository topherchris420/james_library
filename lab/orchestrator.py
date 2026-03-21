import datetime
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from statistics import mean

from generate_experiments import generate

ROOT = Path(__file__).resolve().parent.parent
LAB_DIR = ROOT / "lab"
LOGS = LAB_DIR / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

DEFAULT_SUMMARY_CHARS = 180
DEFAULT_PREVIEW_LINES = 3


def resolve_experiment_command() -> list[str] | None:
    configured = os.getenv("LAB_EXPERIMENT_CMD", "").strip()
    if configured:
        return shlex.split(configured)

    default_runner = ROOT / "run_experiments.py"
    if default_runner.exists():
        return [sys.executable, str(default_runner)]

    return None


def format_config_label(config: dict) -> str:
    if not config:
        return "default"
    return ", ".join(f"{key}={value}" for key, value in sorted(config.items()))


def preview_text(text: str, max_lines: int = DEFAULT_PREVIEW_LINES, max_chars: int = DEFAULT_SUMMARY_CHARS) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "(no output)"

    preview = " | ".join(lines[:max_lines])
    if len(preview) > max_chars:
        return preview[: max_chars - 1] + "…"
    return preview


def score_run(output: dict) -> int:
    score = 0
    if output["returncode"] == 0:
        score += 100
    else:
        score -= 100 + abs(output["returncode"])

    score += min(len(output["stdout"].strip()), 400)
    score -= min(len(output["stderr"].strip()), 200)
    return score


def run_experiments(config):
    config_label = format_config_label(config)
    print(f"Running experiments for config: {config_label}")

    command = resolve_experiment_command()
    if command is None:
        stderr = (
            "Experiment runner not found. Set LAB_EXPERIMENT_CMD to the command that should execute "
            "one experiment run."
        )
        output = {
            "config": config,
            "command": None,
            "returncode": 127,
            "stdout": "",
            "stderr": stderr,
            "duration_s": 0.0,
        }
        output["score"] = score_run(output)
        output["stdout_preview"] = preview_text(output["stdout"])
        output["stderr_preview"] = preview_text(output["stderr"])
        return output

    started = datetime.datetime.now(datetime.timezone.utc)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "LAB_CONFIG": json.dumps(config)},
    )
    duration_s = (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()

    output = {
        "config": config,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_s": round(duration_s, 3),
    }
    output["score"] = score_run(output)
    output["stdout_preview"] = preview_text(output["stdout"])
    output["stderr_preview"] = preview_text(output["stderr"])
    return output


def evaluate_results(outputs):
    total_runs = len(outputs)
    success_count = sum(1 for item in outputs if item["returncode"] == 0)
    failure_count = total_runs - success_count
    ranked_runs = sorted(outputs, key=lambda item: item["score"], reverse=True)
    best_run = ranked_runs[0] if ranked_runs else None
    average_score = round(mean(item["score"] for item in outputs), 2) if outputs else 0.0
    total_stdout_chars = sum(len(item["stdout"]) for item in outputs)
    total_stderr_chars = sum(len(item["stderr"]) for item in outputs)

    highlights = []
    for item in ranked_runs:
        config_label = format_config_label(item["config"])
        status = "ok" if item["returncode"] == 0 else f"failed ({item['returncode']})"
        snippet_source = item["stdout_preview"]
        if snippet_source == "(no output)" and item["stderr_preview"] != "(no output)":
            snippet_source = item["stderr_preview"]
        highlights.append(
            {
                "config": item["config"],
                "config_label": config_label,
                "status": status,
                "score": item["score"],
                "duration_s": item["duration_s"],
                "snippet": snippet_source,
            }
        )

    if not ranked_runs:
        summary = "No experiment runs were produced."
    elif failure_count == total_runs:
        summary = (
            f"{total_runs} experiment runs failed. Top issue from {highlights[0]['config_label']}: "
            f"{highlights[0]['snippet']}"
        )
    else:
        summary = (
            f"{success_count}/{total_runs} experiment runs succeeded. "
            f"Best run: {format_config_label(best_run['config'])}. Preview: {best_run['stdout_preview']}"
        )

    return {
        "score": average_score,
        "summary": summary,
        "total_runs": total_runs,
        "success_count": success_count,
        "failure_count": failure_count,
        "total_stdout_chars": total_stdout_chars,
        "total_stderr_chars": total_stderr_chars,
        "best_run": {
            "config": best_run["config"],
            "score": best_run["score"],
            "returncode": best_run["returncode"],
            "stdout_preview": best_run["stdout_preview"],
            "stderr_preview": best_run["stderr_preview"],
        }
        if best_run
        else None,
        "highlights": highlights,
        "runs": [
            {
                "config": item["config"],
                "returncode": item["returncode"],
                "score": item["score"],
                "duration_s": item["duration_s"],
                "stdout_preview": item["stdout_preview"],
                "stderr_preview": item["stderr_preview"],
            }
            for item in ranked_runs
        ],
    }


def format_evaluation_report(evaluation: dict) -> str:
    lines = [
        "Experiment evaluation:",
        (
            f"- Runs: {evaluation['total_runs']} total | {evaluation['success_count']} succeeded | "
            f"{evaluation['failure_count']} failed"
        ),
        f"- Average score: {evaluation['score']}",
        f"- Summary: {evaluation['summary']}",
    ]

    best_run = evaluation.get("best_run")
    if best_run is not None:
        best_run_line = (
            f"- Best run: {format_config_label(best_run['config'])}"
            f" | score={best_run['score']}"
            f" | returncode={best_run['returncode']}"
        )
        lines.append(best_run_line)

    if evaluation.get("highlights"):
        lines.append("- Run highlights:")
        for item in evaluation["highlights"]:
            highlight_line = (
                f"  • {item['config_label']} | {item['status']}"
                f" | score={item['score']}"
                f" | duration={item['duration_s']}s"
            )
            lines.append(highlight_line)
            lines.append(f"    preview: {item['snippet']}")

    return "\n".join(lines)


def save_log(data):
    timestamp = datetime.datetime.now().isoformat().replace(":", "-")
    file = LOGS / f"{timestamp}.json"
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return file


def commit_results():
    subprocess.run(["git", "add", "lab"], cwd=ROOT, check=False)
    subprocess.run(["git", "commit", "-m", "auto: experiment run"], cwd=ROOT, check=False)


def notify(summary):
    webhook_url = os.getenv("LAB_DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return

    try:
        import requests
    except ImportError:
        print("requests not installed; skipping Discord notification.")
        return

    try:
        requests.post(
            webhook_url,
            json={"content": f"Lab update:\n{summary}"},
            timeout=10,
        )
    except Exception as exc:
        print(f"Discord notification failed: {exc}")


def main():
    configs = generate()
    outputs = [run_experiments(config) for config in configs]
    evaluation = evaluate_results(outputs)

    log = {
        "time": datetime.datetime.now().isoformat(),
        "evaluation": evaluation,
        "outputs": outputs,
    }

    log_file = save_log(log)
    print(format_evaluation_report(evaluation))
    print(f"Saved log: {log_file}")

    notify(evaluation["summary"])

    if os.getenv("LAB_AUTO_COMMIT") == "1":
        commit_results()

    print("Done:", evaluation)


if __name__ == "__main__":
    main()
