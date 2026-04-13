"""Replay gold prompt sets, collect session artifacts, and score them."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from james_library.utilities.session_eval import evaluate_artifacts_against_gold, load_gold_cases


DEFAULT_COMMAND_TEMPLATE = (
    'python rain_lab.py --mode chat --topic "{topic}" --turns 4 --ui off --library "{library_path}"'
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _default_artifact_dir(library_path: Path) -> Path:
    return library_path / "meeting_archives" / "session_artifacts"


def _default_report_dir(library_path: Path) -> Path:
    return library_path / "benchmark_data" / "session_eval_reports"


def _format_command(command_template: str, *, artifact_dir: Path, case_id: str, topic: str, library_path: Path) -> str:
    return command_template.format(
        artifact_dir=str(artifact_dir),
        case_id=case_id,
        topic=topic.replace('"', "'"),
        library_path=str(library_path),
    )


def _snapshot_artifacts(artifact_dir: Path) -> set[str]:
    if not artifact_dir.exists():
        return set()
    return {path.name for path in artifact_dir.glob("session_*.json")}


def _newest_new_artifact(artifact_dir: Path, before: set[str]) -> Path | None:
    if not artifact_dir.exists():
        return None
    candidates = [path for path in artifact_dir.glob("session_*.json") if path.name not in before]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def run_replay(
    *,
    gold_path: Path | str,
    artifact_dir: Path | str,
    report_dir: Path | str,
    command_template: str = DEFAULT_COMMAND_TEMPLATE,
    library_path: Path | str,
) -> dict[str, Any]:
    gold_path = Path(gold_path)
    artifact_dir = Path(artifact_dir)
    report_dir = Path(report_dir)
    library_path = Path(library_path)

    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    gold_cases = load_gold_cases(gold_path)
    run_cases: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []

    for case in gold_cases:
        case_id = str(case.get("id", "unknown"))
        topic = str(case.get("topic", "")).strip()
        before = _snapshot_artifacts(artifact_dir)
        command = _format_command(
            command_template,
            artifact_dir=artifact_dir,
            case_id=case_id,
            topic=topic,
            library_path=library_path,
        )
        completed = subprocess.run(
            command,
            cwd=library_path,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        artifact_path = _newest_new_artifact(artifact_dir, before)
        if artifact_path is not None:
            artifact_paths.append(artifact_path)
        run_cases.append(
            {
                "id": case_id,
                "topic": topic,
                "command": command,
                "returncode": completed.returncode,
                "artifact_path": str(artifact_path) if artifact_path is not None else "",
                "stdout_tail": (completed.stdout or "")[-500:],
                "stderr_tail": (completed.stderr or "")[-500:],
            }
        )

    eval_report = evaluate_artifacts_against_gold(artifact_paths, gold_cases)
    report = {
        "timestamp": _utc_stamp(),
        "command_template": command_template,
        "gold_path": str(gold_path),
        "artifact_dir": str(artifact_dir),
        "summary": {
            "cases_run": len(run_cases),
            "artifacts_captured": len(artifact_paths),
        },
        "cases": run_cases,
        "eval": eval_report,
    }
    report_path = report_dir / f"session_replay_report_{report['timestamp']}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay gold prompt cases, collect session artifacts, and score them."
    )
    parser.add_argument(
        "--gold",
        type=str,
        default="benchmark_data/session_eval_gold.json",
        help="Gold prompt set JSON.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=str,
        default=None,
        help="Directory where session artifacts are expected.",
    )
    parser.add_argument("--report-dir", type=str, default=None, help="Directory for replay reports.")
    parser.add_argument(
        "--command-template",
        type=str,
        default=DEFAULT_COMMAND_TEMPLATE,
        help="Shell command template. Supports {topic}, {case_id}, {artifact_dir}, {library_path}.",
    )
    parser.add_argument("--library", type=str, default=".", help="Repo/library root used as subprocess cwd.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    library_path = Path(args.library).resolve()
    artifact_dir = (
        Path(args.artifact_dir).resolve()
        if args.artifact_dir
        else _default_artifact_dir(library_path)
    )
    report_dir = (
        Path(args.report_dir).resolve()
        if args.report_dir
        else _default_report_dir(library_path)
    )

    report = run_replay(
        gold_path=args.gold,
        artifact_dir=artifact_dir,
        report_dir=report_dir,
        command_template=args.command_template,
        library_path=library_path,
    )

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("R.A.I.N. Session Replay")
    print(f"Cases run: {report['summary']['cases_run']}")
    print(f"Artifacts captured: {report['summary']['artifacts_captured']}")
    print(
        f"Passing cases: {report['eval']['summary']['passing_cases']} / "
        f"{report['eval']['summary']['matched_cases']}"
    )
    print(f"Report: {report['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
