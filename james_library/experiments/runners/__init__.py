"""Factory of builtin experiment runners.

A runner is a function ``(RunContext) -> RunOutput`` that measures something
and returns numbers. It never returns a status. To add one: write the
function, register a ``RunnerSpec`` below under a stable lowercase key, and
reference that key from an experiment definition (``runner.name``).

Registry files name a key; they never supply code or import paths.
"""

from __future__ import annotations

from ..runner import RunnerSpec
from .circle_controls import run_circle_error_rates
from .citation import run_citation_discrimination, run_citation_typography

BUILTIN_RUNNERS: dict[str, RunnerSpec] = {
    spec.name: spec
    for spec in (
        RunnerSpec("citation-discrimination", "1", "measured", run_citation_discrimination),
        RunnerSpec("citation-typography", "1", "measured", run_citation_typography),
        RunnerSpec("circle-error-rates", "1", "simulated", run_circle_error_rates),
    )
}
