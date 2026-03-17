import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from generate_experiments import generate

ROOT = Path(__file__).resolve().parent.parent
LAB_DIR = ROOT / "lab"
LOGS = LAB_DIR / "logs"
LOGS.mkdir(parents=True, exist_ok=True)


def run_experiments(config):
    print(f"Running experiments for config: {config}")
    result = subprocess.run(
        [sys.executable, "run_experiments.py"],  # adjust to your actual entrypoint
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "LAB_CONFIG": json.dumps(config)},
    )
    return {
        "config": config,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def evaluate_results(outputs):
    combined_stdout = "\n".join(item["stdout"] for item in outputs)
    score = len(combined_stdout)
    return {
        "score": score,
        "summary": combined_stdout[:500],
        "runs": [
            {
                "config": item["config"],
                "returncode": item["returncode"],
            }
            for item in outputs
        ],
    }


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

    requests.post(
        webhook_url,
        json={"content": f"Lab update:\n{summary}"},
        timeout=10,
    )


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
    print(f"Saved log: {log_file}")

    notify(evaluation["summary"])

    if os.getenv("LAB_AUTO_COMMIT") == "1":
        commit_results()

    print("Done:", evaluation)


if __name__ == "__main__":
    main()
