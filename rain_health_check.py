"""One-screen local health check for R.A.I.N. Lab deployments."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

STATUS_RANK = {"pass": 0, "warn": 1, "fail": 2}
STATUS_LABEL = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}


@dataclass(slots=True)
class CheckResult:
    name: str
    status: str
    summary: str
    details: dict[str, Any]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local health check for R.A.I.N. Lab.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="LM Studio request timeout in seconds (default: 3.0).",
    )
    parser.add_argument(
        "--tail-lines",
        type=int,
        default=400,
        help="Number of recent launcher log lines to inspect (default: 400).",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=5,
        help="Maximum recent launcher errors to display (default: 5).",
    )
    return parser.parse_args(argv)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _library_root(repo_root: Path) -> Path:
    raw = (os.environ.get("JAMES_LIBRARY_PATH") or "").strip()
    if not raw:
        return repo_root

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate


def _resolve_launcher_log_path(repo_root: Path) -> Path:
    library_root = _library_root(repo_root)
    raw = (os.environ.get("RAIN_LAUNCHER_LOG") or "meeting_archives/launcher_events.jsonl").strip()
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return (library_root / candidate).resolve()


def _models_endpoint_from_base_url(base_url: str) -> str:
    raw = (base_url or "").strip() or "http://127.0.0.1:1234/v1"
    parsed = urlparse(raw)
    if not parsed.scheme:
        parsed = urlparse(f"http://{raw}")

    scheme = parsed.scheme or "http"
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    if path.endswith("/models"):
        models_path = path
    elif path.endswith("/v1"):
        models_path = f"{path}/models"
    elif not path:
        models_path = "/v1/models"
    else:
        models_path = f"{path}/models"

    return urlunparse((scheme, netloc, models_path, "", "", ""))


def _extract_model_names(payload: dict[str, Any]) -> list[str]:
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return []

    names: list[str] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip():
            names.append(model_id.strip())
    return names


def _check_lm_studio(timeout_s: float) -> tuple[CheckResult, CheckResult]:
    base_url = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    endpoint = _models_endpoint_from_base_url(base_url)
    request = Request(endpoint, headers={"Accept": "application/json"})

    try:
        with urlopen(request, timeout=max(0.5, float(timeout_s))) as response:
            status_code = int(response.getcode())
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return (
            CheckResult(
                name="LM Studio API",
                status="fail",
                summary=f"Endpoint returned HTTP {exc.code}.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
            CheckResult(
                name="Model Loaded",
                status="fail",
                summary="Unable to check model because LM Studio API is failing.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
        )
    except URLError as exc:
        return (
            CheckResult(
                name="LM Studio API",
                status="fail",
                summary="Unable to reach LM Studio endpoint.",
                details={"endpoint": endpoint, "error": str(exc.reason)},
            ),
            CheckResult(
                name="Model Loaded",
                status="fail",
                summary="Unable to check model because LM Studio is unreachable.",
                details={"endpoint": endpoint, "error": str(exc.reason)},
            ),
        )
    except TimeoutError as exc:
        return (
            CheckResult(
                name="LM Studio API",
                status="fail",
                summary="LM Studio request timed out.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
            CheckResult(
                name="Model Loaded",
                status="fail",
                summary="Unable to check model due to timeout.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return (
            CheckResult(
                name="LM Studio API",
                status="fail",
                summary="LM Studio check failed unexpectedly.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
            CheckResult(
                name="Model Loaded",
                status="fail",
                summary="Unable to check model due to unexpected error.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
        )

    if status_code != 200:
        return (
            CheckResult(
                name="LM Studio API",
                status="fail",
                summary=f"Endpoint returned HTTP {status_code}.",
                details={"endpoint": endpoint, "status_code": status_code},
            ),
            CheckResult(
                name="Model Loaded",
                status="fail",
                summary="Unable to check model because LM Studio API is not healthy.",
                details={"endpoint": endpoint, "status_code": status_code},
            ),
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return (
            CheckResult(
                name="LM Studio API",
                status="fail",
                summary="Endpoint returned invalid JSON.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
            CheckResult(
                name="Model Loaded",
                status="fail",
                summary="Cannot read model list from invalid LM Studio response.",
                details={"endpoint": endpoint, "error": str(exc)},
            ),
        )

    models = _extract_model_names(payload if isinstance(payload, dict) else {})
    api_result = CheckResult(
        name="LM Studio API",
        status="pass",
        summary="Endpoint reachable and returned valid JSON.",
        details={"endpoint": endpoint, "status_code": status_code},
    )
    if models:
        model_result = CheckResult(
            name="Model Loaded",
            status="pass",
            summary=f"Loaded model: {models[0]}",
            details={"model_count": len(models), "models": models[:10]},
        )
    else:
        model_result = CheckResult(
            name="Model Loaded",
            status="fail",
            summary="No model loaded in LM Studio.",
            details={"model_count": 0, "models": []},
        )
    return api_result, model_result


def _resolve_godot_executable() -> str | None:
    preferred = (os.environ.get("RAIN_GODOT_BIN") or "").strip()
    candidates = [preferred] if preferred else []
    candidates.extend(["godot4", "godot"])

    for candidate in candidates:
        if not candidate:
            continue
        path_candidate = Path(candidate).expanduser()
        if path_candidate.is_absolute() or any(sep in candidate for sep in ("/", "\\")):
            if path_candidate.exists():
                return str(path_candidate)
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _check_ui_stack(repo_root: Path) -> CheckResult:
    project_root_raw = (os.environ.get("RAIN_GODOT_PROJECT_DIR") or "godot_client").strip()
    project_root = Path(project_root_raw).expanduser()
    if not project_root.is_absolute():
        project_root = (repo_root / project_root).resolve()

    visual_runtime = repo_root / "rain_lab_meeting_chat_version.py"
    bridge = repo_root / "godot_event_bridge.py"
    project_file = project_root / "project.godot"
    godot_bin = _resolve_godot_executable()

    details = {
        "visual_runtime": str(visual_runtime),
        "visual_runtime_exists": visual_runtime.exists(),
        "bridge_script": str(bridge),
        "bridge_exists": bridge.exists(),
        "godot_project": str(project_file),
        "project_exists": project_file.exists(),
        "godot_executable": godot_bin,
    }

    missing: list[str] = []
    if not visual_runtime.exists():
        missing.append("rain_lab_meeting_chat_version.py")
    if not bridge.exists():
        missing.append("godot_event_bridge.py")
    if not project_file.exists():
        missing.append("godot_client/project.godot")
    if not godot_bin:
        missing.append("Godot executable")

    if not missing:
        return CheckResult(
            name="Avatar UI Availability",
            status="pass",
            summary=f"Visual stack ready ({Path(godot_bin).name}).",
            details=details,
        )

    return CheckResult(
        name="Avatar UI Availability",
        status="warn",
        summary=f"Visual stack incomplete: {', '.join(missing)}.",
        details=details,
    )


def _extract_recent_launcher_errors(
    log_path: Path,
    tail_lines: int,
    max_errors: int,
) -> list[dict[str, Any]]:
    error_events = {"launcher_failed", "sidecar_fatal", "sidecar_restart_failed"}
    recent_lines: deque[str] = deque(maxlen=max(1, int(tail_lines)))

    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                recent_lines.append(stripped)

    found: list[dict[str, Any]] = []
    for line in recent_lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(payload, dict):
            continue

        event = str(payload.get("event", ""))
        has_error_text = isinstance(payload.get("error"), str) and payload.get("error", "").strip()
        critical_nonzero_exit = (
            event == "sidecar_exited"
            and bool(payload.get("critical"))
            and int(payload.get("exit_code", 0)) != 0
        )
        if not (event in error_events or has_error_text or critical_nonzero_exit):
            continue

        message = (
            payload.get("error")
            or payload.get("reason")
            or payload.get("summary")
            or (f"exit_code={payload.get('exit_code')}" if "exit_code" in payload else "unknown error")
        )
        found.append(
            {
                "ts": payload.get("ts"),
                "event": event,
                "message": str(message),
            }
        )

    if max_errors <= 0:
        return []
    return found[-max_errors:]


def _check_launcher_log(log_path: Path, tail_lines: int, max_errors: int) -> CheckResult:
    if not log_path.exists():
        return CheckResult(
            name="Launcher Errors (Recent)",
            status="warn",
            summary="Launcher log not found yet.",
            details={"log_path": str(log_path), "recent_errors": []},
        )

    recent_errors = _extract_recent_launcher_errors(
        log_path=log_path,
        tail_lines=tail_lines,
        max_errors=max_errors,
    )
    if not recent_errors:
        return CheckResult(
            name="Launcher Errors (Recent)",
            status="pass",
            summary="No recent launcher errors.",
            details={"log_path": str(log_path), "recent_errors": []},
        )

    return CheckResult(
        name="Launcher Errors (Recent)",
        status="warn",
        summary=f"Found {len(recent_errors)} recent launcher error(s).",
        details={"log_path": str(log_path), "recent_errors": recent_errors},
    )


def _overall_status(results: list[CheckResult]) -> str:
    worst = 0
    for result in results:
        worst = max(worst, STATUS_RANK.get(result.status, STATUS_RANK["fail"]))
    for status, rank in STATUS_RANK.items():
        if rank == worst:
            return status
    return "fail"


def _render_text(results: list[CheckResult], overall: str) -> str:
    lines = [
        "R.A.I.N. Lab Health Check",
        "=" * 70,
        f"Overall: {STATUS_LABEL.get(overall, overall.upper())}",
        "",
    ]

    for result in results:
        lines.append(
            f"[{STATUS_LABEL.get(result.status, result.status.upper())}] "
            f"{result.name}: {result.summary}"
        )
        if result.name == "Launcher Errors (Recent)":
            recent_errors = result.details.get("recent_errors", [])
            if isinstance(recent_errors, list) and recent_errors:
                for item in recent_errors:
                    ts = item.get("ts", "unknown-ts")
                    event = item.get("event", "unknown-event")
                    message = item.get("message", "")
                    lines.append(f"  - {ts} | {event} | {message}")
        if result.name == "LM Studio API":
            endpoint = result.details.get("endpoint")
            if endpoint:
                lines.append(f"  - Endpoint: {endpoint}")
    return "\n".join(lines)


def run_health_check(
    timeout_s: float = 3.0,
    tail_lines: int = 400,
    max_errors: int = 5,
) -> tuple[str, list[CheckResult]]:
    repo_root = _repo_root()
    log_path = _resolve_launcher_log_path(repo_root)

    lm_api_result, model_result = _check_lm_studio(timeout_s=timeout_s)
    ui_result = _check_ui_stack(repo_root)
    launcher_result = _check_launcher_log(
        log_path=log_path,
        tail_lines=tail_lines,
        max_errors=max_errors,
    )
    results = [lm_api_result, model_result, ui_result, launcher_result]
    return _overall_status(results), results


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    overall, results = run_health_check(
        timeout_s=args.timeout,
        tail_lines=args.tail_lines,
        max_errors=args.max_errors,
    )

    if args.json:
        payload = {
            "overall_status": overall,
            "checks": [asdict(result) for result in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_text(results, overall))

    return 1 if overall == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
