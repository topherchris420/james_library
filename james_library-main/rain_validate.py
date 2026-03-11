from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from rain_health_check import STATUS_LABEL, run_health_check

try:
    from rich_ui import print_panel, status_indicator, supports_ansi
    _RICH = True
    _ANSI = supports_ansi()
except ImportError:
    _RICH = False
    _ANSI = True


def _c(code: str) -> str:
    return code if _ANSI else ""


_RST = _c("\033[0m")
_GRN = _c("\033[92m")
_YLW = _c("\033[93m")
_RED = _c("\033[91m")


def _stdout_supports(text: str) -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except Exception:
        return False
    return True


_UNICODE_UI = _stdout_supports("✓⚠✗┌┐└┘─│")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified validation for R.A.I.N. Lab.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="LM Studio request timeout in seconds passed through to health checks.",
    )
    parser.add_argument(
        "--tail-lines",
        type=int,
        default=400,
        help="Number of recent launcher log lines to inspect.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=5,
        help="Maximum recent launcher errors to display.",
    )
    return parser.parse_args(argv)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _run_preflight(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root / "rain_preflight_check.py")],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _overall_status(health_status: str, preflight_exit_code: int) -> str:
    if preflight_exit_code != 0 or health_status == "fail":
        return "fail"
    if health_status == "warn":
        return "warn"
    return "pass"


def _status_counts(health_results: list[object]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for result in health_results:
        status = str(getattr(result, "status", "")).lower()
        if status in counts:
            counts[status] += 1
    return counts


def _readiness_summary(
    overall_status: str,
    counts: dict[str, int],
    preflight_result: subprocess.CompletedProcess[str],
) -> str:
    if overall_status == "pass":
        return "Core launcher, LM Studio, and embedded runtime checks look ready."
    if overall_status == "warn" and preflight_result.returncode == 0 and counts.get("fail", 0) == 0:
        return "Core flows look usable; the remaining warnings are optional polish items."
    return "One or more required checks still need attention before the happy path is ready."


def _status_prefix(status: str) -> str:
    normalized = status.lower()
    if _RICH and _UNICODE_UI:
        indicator = {"pass": "ok", "warn": "warning", "fail": "error"}.get(normalized, "warning")
        return status_indicator(indicator)
    fallback = {
        "pass": f"{_GRN}[PASS]{_RST}",
        "warn": f"{_YLW}[WARN]{_RST}",
        "fail": f"{_RED}[FAIL]{_RST}",
    }
    return fallback.get(normalized, "-")


def _recommended_actions(
    health_results: list[object],
    preflight_result: subprocess.CompletedProcess[str],
    overall_status: str,
) -> list[str]:
    checks = {str(getattr(result, "name", "")): result for result in health_results}
    actions: list[str] = []

    lm_api = checks.get("LM Studio API")
    model_loaded = checks.get("Model Loaded")
    zeroclaw_runtime = checks.get("Embedded ZeroClaw Runtime")
    avatar_ui = checks.get("Avatar UI Availability")

    if lm_api and getattr(lm_api, "status", "pass") in {"warn", "fail"}:
        actions.append("Run python rain_lab.py --mode doctor to repair LM Studio connectivity.")
    if model_loaded and getattr(model_loaded, "status", "pass") in {"warn", "fail"}:
        actions.append("Load a model in LM Studio, then re-run python rain_lab.py --mode validate.")
    if zeroclaw_runtime and getattr(zeroclaw_runtime, "status", "pass") in {"warn", "fail"}:
        actions.append("Run python bootstrap_local.py --skip-preflight or inspect python rain_lab.py --mode status.")
    if avatar_ui and getattr(avatar_ui, "status", "pass") in {"warn", "fail"}:
        actions.append("If you want visual avatars, run python godot_setup.py; otherwise continue with --ui auto or CLI chat.")
    if preflight_result.returncode != 0:
        actions.append("Run python rain_lab.py --mode preflight for the full checklist output.")

    if overall_status == "pass":
        actions.append("Continue with python rain_lab.py --mode first-run.")
        actions.append("Launch chat with python rain_lab.py --mode chat --ui auto --topic \"your research question\".")
    elif overall_status == "warn":
        actions.append("Review the warnings above, then continue with python rain_lab.py --mode first-run.")
        actions.append("If Rust-side operations matter immediately, inspect python rain_lab.py --mode status and python rain_lab.py --mode models.")
    else:
        actions.append("Fix the failed checks above, then re-run python rain_lab.py --mode validate.")
        actions.append("If LM Studio is the blocker, run python rain_lab.py --mode doctor.")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in actions:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _preflight_excerpt_lines(
    preflight_result: subprocess.CompletedProcess[str],
    max_lines: int = 10,
) -> list[str]:
    lines: list[str] = []
    for block in (preflight_result.stdout, preflight_result.stderr):
        text = block.strip()
        if not text:
            continue
        lines.extend(line.rstrip() for line in text.splitlines() if line.strip())
    if len(lines) <= max_lines:
        return lines
    return ["..."] + lines[-max_lines:]


def _print_text_report(
    health_status: str,
    health_results: list[object],
    preflight_result: subprocess.CompletedProcess[str],
    overall_status: str,
) -> None:
    counts = _status_counts(health_results)
    readiness = _readiness_summary(overall_status, counts, preflight_result)
    actions = _recommended_actions(health_results, preflight_result, overall_status)
    preflight_ok = preflight_result.returncode == 0
    summary = (
        f"Overall: {STATUS_LABEL.get(overall_status, overall_status.upper())}\n"
        f"Readiness: {readiness}\n"
        f"Checks: {counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail\n"
        f"Health Snapshot: {STATUS_LABEL.get(health_status, health_status.upper())}\n"
        f"Preflight: {'PASS' if preflight_ok else 'FAIL'}"
    )

    if _RICH and _UNICODE_UI:
        print_panel("R.A.I.N. LAB VALIDATION", summary)
    else:
        print("R.A.I.N. Lab Validation")
        print("=" * 70)
        print(summary)
        print("")

    print("Validation checks:")
    for result in health_results:
        print(f"{_status_prefix(result.status)} {result.name}: {result.summary}")
    print(f"{_status_prefix('pass' if preflight_ok else 'fail')} Preflight: {'PASS' if preflight_ok else 'FAIL'}")

    if not preflight_ok:
        print("  Run python rain_lab.py --mode preflight for the full checklist output.")
        for line in _preflight_excerpt_lines(preflight_result):
            print(f"  {line}")

    if actions:
        print("")
        print("Recommended actions:")
        for item in actions:
            print(f"- {item}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = _repo_root()
    health_status, health_results = run_health_check(
        timeout_s=args.timeout,
        tail_lines=args.tail_lines,
        max_errors=args.max_errors,
    )
    preflight_result = _run_preflight(repo_root)
    overall_status = _overall_status(health_status, preflight_result.returncode)
    counts = _status_counts(health_results)
    readiness = _readiness_summary(overall_status, counts, preflight_result)
    actions = _recommended_actions(health_results, preflight_result, overall_status)
    preflight_excerpt = _preflight_excerpt_lines(preflight_result)

    if args.json:
        payload = {
            "overall_status": overall_status,
            "health_status": health_status,
            "preflight_passed": preflight_result.returncode == 0,
            "preflight_exit_code": preflight_result.returncode,
            "status_counts": counts,
            "readiness_summary": readiness,
            "recommended_actions": actions,
            "health_checks": [asdict(result) for result in health_results],
            "preflight_stdout": preflight_result.stdout,
            "preflight_stderr": preflight_result.stderr,
            "preflight_excerpt": preflight_excerpt,
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    else:
        _print_text_report(health_status, health_results, preflight_result, overall_status)

    return 1 if overall_status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
