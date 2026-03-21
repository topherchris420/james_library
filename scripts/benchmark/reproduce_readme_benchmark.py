#!/usr/bin/env python3
"""Recompute benchmark summary values used in README from CSV input."""

from __future__ import annotations

import csv
from pathlib import Path

DATASET = Path(__file__).resolve().parents[2] / "benchmark_data" / "rain_vs_autoresearch.csv"


def load_rows() -> list[dict[str, str]]:
    with DATASET.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    rows = load_rows()
    rain_scores = [float(row["rain_lab"]) for row in rows]
    auto_scores = [float(row["autoresearch"]) for row in rows]

    rain_avg = sum(rain_scores) / len(rain_scores)
    auto_avg = sum(auto_scores) / len(auto_scores)
    rain_peak = max(rain_scores)
    auto_peak = max(auto_scores)
    categories_won = sum(r > a for r, a in zip(rain_scores, auto_scores))

    print("# Reproduced Benchmark Summary")
    print(f"Dataset: {DATASET}")
    print()
    print("| Metric | R.A.I.N. Lab | AutoResearch |")
    print("|---|---:|---:|")
    print(f"| Average Score | {rain_avg:.1f} | {auto_avg:.1f} |")
    print(f"| Peak Score | {rain_peak:.0f} | {auto_peak:.0f} |")
    print(f"| Categories Won | {categories_won} / {len(rows)} | {len(rows) - categories_won} / {len(rows)} |")


if __name__ == "__main__":
    main()
