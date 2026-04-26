"""Bistable-system statistical analysis pipeline.

This module provides an object-oriented workflow for fitting:
1) Logistic occupation curves for mirrored drive conditions.
2) Arrhenius/Kramers-like log-linear escape-time kinetics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

REQUIRED_COLUMNS = ["amplitude", "drive_site", "start_site", "end_site", "escape_time"]
VALID_SITES = {"A", "B"}


@dataclass(frozen=True)
class LogisticFitResult:
    drive_site: str
    target_site: str
    amplitudes: np.ndarray
    probabilities: np.ndarray
    k: float
    x0: float
    covariance: np.ndarray


@dataclass(frozen=True)
class KineticsFitResult:
    amplitudes: np.ndarray
    mean_escape_time: np.ndarray
    log_mean_escape_time: np.ndarray
    intercept_a: float
    slope_b: float


class BistableAnalysisPipeline:
    """Pipeline for empirical occupation statistics and transition kinetics."""

    def __init__(self, data: pd.DataFrame | None = None) -> None:
        self._raw_data = pd.DataFrame(columns=REQUIRED_COLUMNS)
        if data is not None:
            self.load_data(data)

    @staticmethod
    def _logistic(x: np.ndarray, k: float, x0: float) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-k * (x - x0)))

    @staticmethod
    def _arrhenius_log_linear(amplitude: np.ndarray, a: float, b: float) -> np.ndarray:
        return a - b * amplitude

    def load_data(self, data: pd.DataFrame | Iterable[dict]) -> "BistableAnalysisPipeline":
        """Replace existing data with validated trial records."""
        frame = pd.DataFrame(data)
        self._raw_data = self._validate_and_normalize(frame)
        return self

    def append_data(self, data: pd.DataFrame | Iterable[dict]) -> "BistableAnalysisPipeline":
        """Append additional trial records and preserve existing data."""
        frame = pd.DataFrame(data)
        normalized = self._validate_and_normalize(frame)
        self._raw_data = pd.concat([self._raw_data, normalized], ignore_index=True)
        return self

    def load_csv(self, csv_path: str | Path) -> "BistableAnalysisPipeline":
        """Load trial records from CSV."""
        frame = pd.read_csv(csv_path)
        return self.load_data(frame)

    def _validate_and_normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        normalized = frame.loc[:, REQUIRED_COLUMNS].copy()

        normalized["amplitude"] = pd.to_numeric(normalized["amplitude"], errors="coerce")
        normalized["escape_time"] = pd.to_numeric(normalized["escape_time"], errors="coerce")

        for site_column in ("drive_site", "start_site", "end_site"):
            normalized[site_column] = normalized[site_column].astype(str).str.strip().str.upper()
            invalid = ~normalized[site_column].isin(VALID_SITES)
            if invalid.any():
                invalid_values = sorted(normalized.loc[invalid, site_column].dropna().unique())
                raise ValueError(f"Invalid values in {site_column}: {invalid_values}")

        if normalized["amplitude"].isna().any():
            raise ValueError("amplitude column contains non-numeric or missing values")

        return normalized

    def aggregate_occupation_statistics(self, drive_site: str, target_site: str) -> pd.DataFrame:
        """Aggregate end-site occupation probability by amplitude for one drive condition."""
        drive = drive_site.strip().upper()
        target = target_site.strip().upper()
        if drive not in VALID_SITES or target not in VALID_SITES:
            raise ValueError("drive_site and target_site must be 'A' or 'B'")

        subset = self._raw_data[self._raw_data["drive_site"] == drive].copy()
        if subset.empty:
            raise ValueError(f"No rows found for drive_site={drive}")

        grouped = (
            subset.assign(is_target=(subset["end_site"] == target).astype(float))
            .groupby("amplitude", as_index=False)
            .agg(probability=("is_target", "mean"), count=("is_target", "size"))
            .sort_values("amplitude")
        )
        return grouped

    def fit_logistic_occupation(self, drive_site: str, target_site: str) -> LogisticFitResult:
        """Fit bounded logistic occupation probability curve P(x)."""
        grouped = self.aggregate_occupation_statistics(drive_site=drive_site, target_site=target_site)
        x = grouped["amplitude"].to_numpy(dtype=float)
        y = grouped["probability"].to_numpy(dtype=float)

        if len(x) < 3:
            raise ValueError("At least 3 distinct amplitude points are required for logistic fit")

        p0 = [1.0, float(np.median(x))]
        bounds = ([0.0, float(np.min(x))], [np.inf, float(np.max(x))])
        params, covariance = curve_fit(self._logistic, x, y, p0=p0, bounds=bounds, maxfev=20_000)

        return LogisticFitResult(
            drive_site=drive_site.strip().upper(),
            target_site=target_site.strip().upper(),
            amplitudes=x,
            probabilities=y,
            k=float(params[0]),
            x0=float(params[1]),
            covariance=covariance,
        )

    def aggregate_escape_kinetics(self) -> pd.DataFrame:
        """Aggregate mean escape times by amplitude from finite escape observations."""
        subset = self._raw_data.dropna(subset=["escape_time"]).copy()
        subset = subset[subset["escape_time"] > 0.0]
        if subset.empty:
            raise ValueError("No positive escape_time records available for kinetics analysis")

        grouped = (
            subset.groupby("amplitude", as_index=False)
            .agg(mean_escape_time=("escape_time", "mean"), count=("escape_time", "size"))
            .sort_values("amplitude")
        )
        grouped["log_mean_escape_time"] = np.log(grouped["mean_escape_time"])
        return grouped

    def fit_escape_kinetics(self) -> KineticsFitResult:
        """Fit ln(tau) = a - b*A over amplitude-aggregated means."""
        grouped = self.aggregate_escape_kinetics()
        x = grouped["amplitude"].to_numpy(dtype=float)
        y = grouped["log_mean_escape_time"].to_numpy(dtype=float)

        if len(x) < 2:
            raise ValueError("At least 2 distinct amplitude points are required for kinetics fit")

        params, _ = curve_fit(self._arrhenius_log_linear, x, y, p0=(float(np.max(y)), 1.0), maxfev=20_000)
        a, b = float(params[0]), float(params[1])

        return KineticsFitResult(
            amplitudes=x,
            mean_escape_time=grouped["mean_escape_time"].to_numpy(dtype=float),
            log_mean_escape_time=y,
            intercept_a=a,
            slope_b=b,
        )

    def run_full_analysis(self) -> dict[str, LogisticFitResult | KineticsFitResult]:
        """Run symmetric occupation fitting and escape kinetics fitting."""
        logistic_drive_a = self.fit_logistic_occupation(drive_site="A", target_site="B")
        logistic_drive_b = self.fit_logistic_occupation(drive_site="B", target_site="A")
        kinetics = self.fit_escape_kinetics()
        return {
            "logistic_drive_A_to_B": logistic_drive_a,
            "logistic_drive_B_to_A": logistic_drive_b,
            "escape_kinetics": kinetics,
        }

    def plot_results(
        self,
        analysis_results: dict[str, LogisticFitResult | KineticsFitResult] | None = None,
        figsize: tuple[float, float] = (12.0, 5.0),
    ) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
        """Create a publication-style two-panel figure for occupation and kinetics."""
        if analysis_results is None:
            analysis_results = self.run_full_analysis()

        fit_ab = analysis_results["logistic_drive_A_to_B"]
        fit_ba = analysis_results["logistic_drive_B_to_A"]
        kinetics = analysis_results["escape_kinetics"]
        assert isinstance(fit_ab, LogisticFitResult)
        assert isinstance(fit_ba, LogisticFitResult)
        assert isinstance(kinetics, KineticsFitResult)

        plt.style.use("seaborn-v0_8-whitegrid")
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize, constrained_layout=True)

        x_min = float(min(np.min(fit_ab.amplitudes), np.min(fit_ba.amplitudes)))
        x_max = float(max(np.max(fit_ab.amplitudes), np.max(fit_ba.amplitudes)))
        x_fine = np.linspace(x_min, x_max, 400)

        ax1.scatter(fit_ab.amplitudes, fit_ab.probabilities, color="#1f77b4", label="Drive A data", zorder=3)
        ax1.plot(x_fine, self._logistic(x_fine, fit_ab.k, fit_ab.x0), color="#1f77b4", label="Drive A fit")

        ax1.scatter(fit_ba.amplitudes, fit_ba.probabilities, color="#d62728", label="Drive B data", zorder=3)
        ax1.plot(x_fine, self._logistic(x_fine, fit_ba.k, fit_ba.x0), color="#d62728", label="Drive B fit")

        ax1.set_xlabel("Amplitude (field proxy)")
        ax1.set_ylabel("Final occupation probability")
        ax1.set_title("Mirrored occupation control")
        ax1.set_ylim(-0.02, 1.02)
        ax1.legend(frameon=True)

        ax2.scatter(
            kinetics.amplitudes,
            kinetics.log_mean_escape_time,
            color="#2ca02c",
            label="Log-mean data",
            zorder=3,
        )
        ax2.plot(
            kinetics.amplitudes,
            self._arrhenius_log_linear(kinetics.amplitudes, kinetics.intercept_a, kinetics.slope_b),
            color="#2ca02c",
            label=f"Fit: ln(τ)={kinetics.intercept_a:.3f}-{kinetics.slope_b:.3f}A",
        )

        ax2.set_xlabel("Amplitude (field proxy)")
        ax2.set_ylabel("ln(mean escape time)")
        ax2.set_title("Arrhenius/Kramers-like escape kinetics")
        ax2.legend(frameon=True)

        return fig, (ax1, ax2)


__all__ = [
    "BistableAnalysisPipeline",
    "KineticsFitResult",
    "LogisticFitResult",
]
