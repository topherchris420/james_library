"""Replay gold prompt sets, collect session artifacts, and score them."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from james_library.utilities.session_eval import evaluate_artifacts_against_gold, load_gold_cases


DEFAULT_COMMAND_TEMPLATE = (
    '{python} rain_lab.py --mode chat --topic "{topic}" --turns 4 --ui off --library "{library_path}"'
)
MAX_RECORDED_ARTIFACT_BYTES = 5_000_000


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _default_artifact_dir(library_path: Path) -> Path:
    return library_path / "meeting_archives" / "session_artifacts"


def _default_report_dir(library_path: Path) -> Path:
    return library_path / "benchmark_data" / "session_eval_reports"


def _quote_shell_arg(value: str | Path) -> str:
    text = str(value)
    if os.name == "nt":
        return subprocess.list2cmdline([text])
    return shlex.quote(text)


def _format_command(command_template: str, *, artifact_dir: Path, case_id: str, topic: str, library_path: Path) -> str:
    return command_template.format(
        python=_quote_shell_arg(sys.executable),
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
    live_judgment: bool = False,
) -> dict[str, Any]:
    if live_judgment:
        raise ValueError("Live judgment is unsupported by gold replay; use rain_lab.py judge --evidence instead.")
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
        child_env = dict(os.environ)
        child_env["RAIN_JUDGMENT_PROVIDER"] = "off"
        child_env.pop("TYPESAFE_API_KEY", None)
        child_env.pop("TYPESAFE_MODEL", None)
        completed = subprocess.run(
            command,
            cwd=library_path,
            env=child_env,
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
        "mode": "live_session_replay",
        "judgment_mode": "disabled",
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


def replay_recorded_judgments(artifact: Path | str) -> dict[str, Any]:
    """Read recorded envelopes only; this path never constructs a provider."""
    try:
        with Path(artifact).open("rb") as artifact_file:
            raw = artifact_file.read(MAX_RECORDED_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_RECORDED_ARTIFACT_BYTES:
            raise ValueError
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_constant,
        )
        if not isinstance(payload, dict) or payload.get("schema_version") != "rain-session-artifact/v1":
            raise ValueError
        judgments = payload.get("judgments", [])
        if not isinstance(judgments, list):
            raise ValueError
        for judgment in judgments:
            if not isinstance(judgment, dict):
                raise ValueError
            state = judgment.get("state")
            state_hash = judgment.get("state_hash")
            envelope_hash = judgment.get("envelope_hash")
            if (
                not isinstance(state, str)
                or not isinstance(state_hash, str)
                or not isinstance(envelope_hash, str)
            ):
                raise ValueError
            if not hmac.compare_digest(hashlib.sha256(state.encode("utf-8")).hexdigest(), state_hash):
                raise ValueError
            unsigned = dict(judgment)
            del unsigned["envelope_hash"]
            encoded = json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            if not hmac.compare_digest(hashlib.sha256(encoded).hexdigest(), envelope_hash):
                raise ValueError
        return {
            "mode": "recorded_judgment",
            "session_id": str(payload.get("session_id", "")),
            "judgments": judgments,
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError("recorded_judgment_invalid") from exc


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
    parser.add_argument("--recorded-artifact", type=str, default=None,
                        help="Replay recorded judgments without launching a session or provider.")
    parser.add_argument("--live-judgment", action="store_true",
                        help="Unsupported; use rain_lab.py judge --evidence for live judgment.")
    args = parser.parse_args(argv)
    if args.live_judgment:
        parser.error("Live judgment is unsupported by gold replay; use rain_lab.py judge --evidence instead.")

    if args.recorded_artifact:
        report = replay_recorded_judgments(args.recorded_artifact)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("RECORDED JUDGMENT")
            for item in report["judgments"]:
                print(f"{item.get('judgment_id', '')}: {item.get('disposition', '')}")
        return 0

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
        live_judgment=args.live_judgment,
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
