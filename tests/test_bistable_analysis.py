import numpy as np
import pandas as pd

from bistable_analysis import BistableAnalysisPipeline


def _sample_trials() -> pd.DataFrame:
    rows = []
    amplitudes = [0.1, 0.2, 0.3, 0.4]

    for amp in amplitudes:
        for _ in range(12):
            rows.append(
                {
                    "amplitude": amp,
                    "drive_site": "A",
                    "start_site": "A",
                    "end_site": "B" if np.random.random() < amp * 2 else "A",
                    "escape_time": 5.0 * np.exp(-2.0 * amp) + np.random.uniform(0.0, 0.2),
                }
            )

        for _ in range(12):
            rows.append(
                {
                    "amplitude": amp,
                    "drive_site": "B",
                    "start_site": "B",
                    "end_site": "A" if np.random.random() < amp * 2 else "B",
                    "escape_time": 5.5 * np.exp(-1.8 * amp) + np.random.uniform(0.0, 0.2),
                }
            )

    return pd.DataFrame(rows)


def test_pipeline_runs_end_to_end() -> None:
    np.random.seed(7)
    pipeline = BistableAnalysisPipeline(_sample_trials())

    results = pipeline.run_full_analysis()

    fit_ab = results["logistic_drive_A_to_B"]
    fit_ba = results["logistic_drive_B_to_A"]
    kinetics = results["escape_kinetics"]

    assert fit_ab.k > 0
    assert fit_ba.k > 0
    assert kinetics.slope_b > 0

    fig, axes = pipeline.plot_results(results)
    assert len(axes) == 2
    assert fig is not None


def test_invalid_site_validation() -> None:
    data = pd.DataFrame(
        [
            {
                "amplitude": 0.1,
                "drive_site": "C",
                "start_site": "A",
                "end_site": "B",
                "escape_time": 1.2,
            }
        ]
    )

    try:
        BistableAnalysisPipeline(data)
        assert False, "Expected ValueError for invalid drive_site"
    except ValueError as exc:
        assert "Invalid values" in str(exc)
