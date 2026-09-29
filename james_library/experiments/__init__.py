"""R.A.I.N. Experiments: turn a claim into a bounded, recorded, reproducible run.

Claim → Run → Measure → Record → Publish → Repeat.

- ``schema``     versioned contracts (JSON Schema under contracts/experiments/)
- ``registry``   file-backed registry with never-reused V3D-EXP-NNNN IDs
- ``runner``     run pipeline and external submission admission
- ``evaluate``   the only code that assigns passed / failed / inconclusive
- ``verify``     re-derives every stored result from stored data
- ``results``    RESULTS.md, ``show`` and ``compare`` views
- ``runners``    factory of builtin experiment implementations

See EXPERIMENTS.md at the repository root.
"""

from .registry import Registry
from .runner import RunContext, RunnerSpec, RunOutput, record_submission, run_experiment
from .schema import ExperimentError

__all__ = [
    "ExperimentError",
    "Registry",
    "RunContext",
    "RunOutput",
    "RunnerSpec",
    "record_submission",
    "run_experiment",
]
