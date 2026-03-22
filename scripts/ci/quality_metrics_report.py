#!/usr/bin/env python3
"""Compute repository quality metrics from static scans and test artifacts."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import xml.etree.ElementTree as et
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class MetricResult:
    panic_count: int
    unwrap_count: int
    flaky_test_rate_pct: float
    flaky_tests: int
    total_tests_in_run1: int
    mean_pr_size_loc: float
    critical_path_coverage_pct: float
    critical_path_discovered: int
    critical_path_executed: int


def run_cmd(args: list[str]) -> str:
    completed = subprocess.run(args, check=True, text=True, capture_output=True)
    return completed.stdout


def rg_count(pattern: str) -> int:
    args = [
        "rg",
        "-n",
        "--no-heading",
        "--glob",
        "!src/**/tests/**",
        "--glob",
        "!src/**/*_test.rs",
        pattern,
        "src",
    ]
    completed = subprocess.run(args, text=True, capture_output=True, check=False)
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr.strip())
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return len(lines)


def parse_junit_statuses(junit_path: Path) -> dict[str, str]:
    if not junit_path.exists():
        return {}
    tree = et.parse(junit_path)
    root = tree.getroot()
    statuses: dict[str, str] = {}
    for case in root.findall(".//testcase"):
        name = case.attrib.get("name", "")
        classname = case.attrib.get("classname", "")
        full_name = f"{classname}::{name}" if classname else name
        status = "passed"
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        statuses[full_name] = status
    return statuses


def parse_test_list(test_list_path: Path) -> set[str]:
    if not test_list_path.exists():
        return set()
    tests: set[str] = set()
    for line in test_list_path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("PASS", "FAIL", "SKIP")):
            tests.add(stripped)
    return tests


def compute_flaky_rate(run1: dict[str, str], run2: dict[str, str]) -> tuple[int, int, float]:
    total = len(run1)
    if total == 0:
        return 0, 0, 0.0
    flaky = sum(1 for test, status in run1.items() if status == "failed" and run2.get(test) == "passed")
    return flaky, total, round((flaky / total) * 100.0, 2)


def compute_mean_pr_size(days: int) -> float:
    output = run_cmd(["git", "log", f"--since={days}.days", "--numstat", "--pretty=tformat:commit"])
    commit_sizes: list[int] = []
    current = 0
    for line in output.splitlines():
        if line.startswith("commit"):
            if current > 0:
                commit_sizes.append(current)
            current = 0
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add_s, del_s, _ = parts
        if add_s.isdigit() and del_s.isdigit():
            current += int(add_s) + int(del_s)
    if current > 0:
        commit_sizes.append(current)
    if not commit_sizes:
        return 0.0
    return round(statistics.mean(commit_sizes), 2)


def find_critical_path_tests(candidates: Iterable[str]) -> set[str]:
    critical_keywords = ("security", "gateway", "runtime", "tool", "pairing", "policy")
    return {name for name in candidates if any(key in name.lower() for key in critical_keywords)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", default="artifacts", help="Directory containing test artifacts")
    parser.add_argument("--days", type=int, default=30, help="Lookback window for mean PR size")
    parser.add_argument("--output-json", required=True, help="JSON report output path")
    parser.add_argument("--output-md", required=True, help="Markdown report output path")
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    test_artifacts_dir = artifacts_dir / "test-artifacts"

    panic_count = rg_count(r"panic!\s*\(")
    unwrap_count = rg_count(r"\.unwrap\s*\(")

    run1 = parse_junit_statuses(test_artifacts_dir / "run1.xml")
    run2 = parse_junit_statuses(test_artifacts_dir / "run2.xml")
    flaky_tests, total_tests, flaky_rate = compute_flaky_rate(run1, run2)

    test_list = parse_test_list(test_artifacts_dir / "test-list.txt")
    critical_discovered = find_critical_path_tests(test_list)
    critical_executed = {test for test in critical_discovered if test in run1}
    critical_coverage = 0.0
    if critical_discovered:
        critical_coverage = round((len(critical_executed) / len(critical_discovered)) * 100.0, 2)

    result = MetricResult(
        panic_count=panic_count,
        unwrap_count=unwrap_count,
        flaky_test_rate_pct=flaky_rate,
        flaky_tests=flaky_tests,
        total_tests_in_run1=total_tests,
        mean_pr_size_loc=compute_mean_pr_size(args.days),
        critical_path_coverage_pct=critical_coverage,
        critical_path_discovered=len(critical_discovered),
        critical_path_executed=len(critical_executed),
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(asdict(result), indent=2) + "\n")

    output_md = Path(args.output_md)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(
        "\n".join(
            [
                "# Quality Metrics Report",
                "",
                "| Metric | Value |",
                "|---|---:|",
                f"| Panic count (production path) | {result.panic_count} |",
                f"| Unwrap count (production path) | {result.unwrap_count} |",
                (
                    f"| Flaky test rate | {result.flaky_test_rate_pct}% "
                    f"({result.flaky_tests}/{result.total_tests_in_run1}) |"
                ),
                f"| Mean PR size (LOC, {args.days}d) | {result.mean_pr_size_loc} |",
                (
                    f"| Critical-path test coverage | {result.critical_path_coverage_pct}% "
                    f"({result.critical_path_executed}/{result.critical_path_discovered}) |"
                ),
                "",
                "Generated by `scripts/ci/quality_metrics_report.py`.",
            ]
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
