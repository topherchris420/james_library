"""Command-line entrypoint for held-out calibration and drift checks."""
from .benchmark import calibration_main

if __name__ == "__main__":
    raise SystemExit(calibration_main())
