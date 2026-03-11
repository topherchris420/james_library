from __future__ import annotations

import argparse
import os

from rain_lab_chat.doctor import collect_lm_studio_diagnostics, models_endpoint_from_base_url

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
_DIM = _c("\033[90m")
_RED = _c("\033[91m")
_GRN = _c("\033[92m")
_YLW = _c("\033[93m")
_CYN = _c("\033[96m")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LM Studio diagnostics for R.A.I.N. Lab")
    parser.add_argument("--base-url", type=str, default=os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
    parser.add_argument("--model", type=str, default=os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct"))
    parser.add_argument("--api-key", type=str, default=os.environ.get("LM_STUDIO_API_KEY", "lm-studio"))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("RAIN_LM_TIMEOUT", "10")))
    parser.add_argument("--no-completion-probe", action="store_true")
    return parser.parse_args(argv)


def _print_line(text: str) -> None:
    print(text)


def _print_actions(actions: list[str]) -> None:
    if not actions:
        return
    _print_line("")
    _print_line("Recommended actions:")
    for item in actions:
        _print_line(f"  - {item}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    timeout_s = max(1.0, float(args.timeout))
    diagnostics = collect_lm_studio_diagnostics(
        args.base_url,
        args.model,
        api_key=args.api_key,
        timeout_s=timeout_s,
        include_completion_probe=not args.no_completion_probe,
    )
    endpoint = diagnostics["endpoint"]
    probe = diagnostics["probe"]

    summary = (
        f"Base URL: {args.base_url}\n"
        f"Models URL: {models_endpoint_from_base_url(args.base_url)}\n"
        f"Configured model: {args.model}\n"
        f"Timeout: {timeout_s:.1f}s"
    )
    if _RICH:
        print_panel("LM STUDIO DOCTOR", summary)
    else:
        _print_line(f"{_CYN}LM STUDIO DOCTOR{_RST}")
        _print_line(summary)
        _print_line("")

    if endpoint["ok"]:
        prefix = status_indicator("ok") if _RICH else f"{_GRN}✓{_RST}"
        _print_line(f"{prefix} /v1/models reachable")
    else:
        prefix = status_indicator("error") if _RICH else f"{_RED}✗{_RST}"
        _print_line(f"{prefix} {endpoint.get('error') or 'LM Studio endpoint check failed'}")

    if endpoint.get("latency_ms") is not None:
        _print_line(f"  Latency: {endpoint['latency_ms']} ms")
    if endpoint.get("status_code") is not None:
        _print_line(f"  HTTP status: {endpoint['status_code']}")

    loaded_models = endpoint.get("loaded_models") or []
    if loaded_models:
        _print_line(f"  Loaded models: {', '.join(loaded_models)}")
        if endpoint.get("model_loaded"):
            ok_prefix = status_indicator("ok") if _RICH else f"{_GRN}✓{_RST}"
            _print_line(f"  {ok_prefix} Configured model is loaded")
        else:
            warn_prefix = status_indicator("warning") if _RICH else f"{_YLW}⚠{_RST}"
            _print_line(f"  {warn_prefix} Configured model is not loaded")
    else:
        warn_prefix = status_indicator("warning") if _RICH else f"{_YLW}⚠{_RST}"
        _print_line(f"  {warn_prefix} No loaded models detected")

    if probe.get("ok") is True:
        prefix = status_indicator("ok") if _RICH else f"{_GRN}✓{_RST}"
        _print_line(f"{prefix} Completion probe succeeded")
        if probe.get("latency_ms") is not None:
            _print_line(f"  Probe latency: {probe['latency_ms']} ms")
        if probe.get("finish_reason"):
            _print_line(f"  Finish reason: {probe['finish_reason']}")
        if probe.get("preview"):
            _print_line(f"  Preview: {probe['preview'][:80]}")
    elif probe.get("ok") is False:
        prefix = status_indicator("error") if _RICH else f"{_RED}✗{_RST}"
        _print_line(f"{prefix} {probe.get('error') or 'Completion probe failed'}")

    _print_actions(list(diagnostics.get("actions", [])))

    if diagnostics["ok"]:
        _print_line(f"\n{_GRN}Doctor result: healthy{_RST}")
        return 0

    _print_line(f"\n{_RED}Doctor result: issues detected{_RST}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
