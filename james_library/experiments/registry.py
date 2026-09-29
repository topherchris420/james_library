"""File-backed experiment registry.

Layout (plain JSON files, reviewed and versioned with git)::

    experiments/
      registry.json                  allocation ledger: every ID ever issued
      V3D-EXP-0001/
        experiment.json              pre-registered definition (write-once per version)
        runs/
          RUN-0001/
            result.json              run record (rain-experiment-run/v1)
            artifacts/...            artifacts the data policy allows to be stored

Identifiers are never reused: allocation takes the maximum of the ledger and
the directories, so deleting an experiment directory does not free its ID.
Experiment and run directories are claimed with an exclusive ``mkdir``.
A final run record is never overwritten.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provenance import REPO_ROOT
from .schema import (
    DEFINITION_SCHEMA,
    ExperimentError,
    canonical_json,
    validate_definition,
)

DEFAULT_ROOT = REPO_ROOT / "experiments"
LEDGER_SCHEMA = "rain-experiment-registry/v1"

EXPERIMENT_ID = re.compile(r"^V3D-EXP-(\d{4,})$")
RUN_ID = re.compile(r"^(V3D-EXP-\d{4,})-RUN-(\d{4,})$")
_RUN_DIR = re.compile(r"^RUN-(\d{4,})$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_experiment_id(number: int) -> str:
    return f"V3D-EXP-{number:04d}"


def check_experiment_id(value: str) -> str:
    if not isinstance(value, str) or not EXPERIMENT_ID.match(value):
        raise ExperimentError(f"Not an experiment ID: {value!r} (expected V3D-EXP-0001 form)")
    return value


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path, limit: int = 16 * 1024 * 1024) -> Any:
    if path.is_symlink():
        raise ExperimentError(f"Refusing to read symlink {path.name}")
    if path.stat().st_size > limit:
        raise ExperimentError(f"{path.name} exceeds {limit} bytes")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"{path.name} is not valid JSON: {exc}") from exc


class Registry:
    def __init__(self, root: str | Path | None = None, results_path: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_ROOT
        self.results_path = Path(results_path) if results_path is not None else self.root.parent / "RESULTS.md"
        self.ledger_path = self.root / "registry.json"

    # ── identifiers ────────────────────────────────────────────────────
    def ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {"schema_version": LEDGER_SCHEMA, "allocated": []}
        ledger = read_json(self.ledger_path)
        if not isinstance(ledger, dict) or ledger.get("schema_version") != LEDGER_SCHEMA \
                or not isinstance(ledger.get("allocated"), list):
            raise ExperimentError("experiments/registry.json is not a valid allocation ledger")
        return ledger

    def experiment_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and EXPERIMENT_ID.match(p.name))

    @contextmanager
    def _ledger_lock(self, timeout_s: float = 10.0) -> Iterator[None]:
        """Serialize ledger read-claim-write so concurrent creates cannot drop an allocation."""
        lock = self.root / ".registry.lock"
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ExperimentError(
                        f"Registry is locked by another process ({lock}); if none is running, delete the lock file"
                    ) from None
                time.sleep(0.02)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _allocate(self, created_at: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._ledger_lock():
            return self._allocate_locked(created_at)

    def _allocate_locked(self, created_at: str) -> str:
        ledger = self.ledger()
        seen = [entry.get("id", "") for entry in ledger["allocated"]] + self.experiment_ids()
        numbers = [int(m.group(1)) for m in (EXPERIMENT_ID.match(i) for i in seen) if m]
        number = max(numbers, default=0) + 1
        while True:
            candidate = format_experiment_id(number)
            try:
                (self.root / candidate).mkdir()
            except FileExistsError:
                number += 1
                continue
            break
        ledger["allocated"].append({"id": candidate, "created_at": created_at})
        _atomic_write(self.ledger_path, canonical_json(ledger))
        return candidate

    # ── experiments ────────────────────────────────────────────────────
    def experiment_dir(self, experiment_id: str) -> Path:
        return self.root / check_experiment_id(experiment_id)

    def create(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Allocate the next ID and write a validated, write-once definition."""
        created_at = utc_now()
        draft = {"schema_version": DEFINITION_SCHEMA, "experiment_version": 1, **fields,
                 "experiment_id": "V3D-EXP-0000", "created_at": created_at}
        validate_definition(draft)  # refuse before an ID is consumed
        experiment_id = self._allocate(created_at)
        definition = {**draft, "experiment_id": experiment_id}
        path = self.experiment_dir(experiment_id) / "experiment.json"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(definition))
        return definition

    def load_definition(self, experiment_id: str) -> dict[str, Any]:
        path = self.experiment_dir(experiment_id) / "experiment.json"
        if not path.is_file():
            raise ExperimentError(f"{experiment_id} is not registered")
        definition = read_json(path)
        validate_definition(definition)
        if definition["experiment_id"] != experiment_id:
            raise ExperimentError(f"{path} declares {definition['experiment_id']}, not {experiment_id}")
        return definition

    # ── runs ───────────────────────────────────────────────────────────
    def run_dirs(self, experiment_id: str) -> list[Path]:
        runs = self.experiment_dir(experiment_id) / "runs"
        if not runs.is_dir():
            return []
        found = [p for p in runs.iterdir() if p.is_dir() and _RUN_DIR.match(p.name)]
        return sorted(found, key=lambda p: int(_RUN_DIR.match(p.name).group(1)))

    def runs(self, experiment_id: str) -> list[dict[str, Any]]:
        records = []
        for run_dir in self.run_dirs(experiment_id):
            path = run_dir / "result.json"
            if path.is_file():
                records.append(read_json(path))
        return records

    def begin_run(self, experiment_id: str) -> tuple[str, Path]:
        runs = self.experiment_dir(experiment_id) / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        existing = [int(_RUN_DIR.match(p.name).group(1)) for p in self.run_dirs(experiment_id)]
        number = max(existing, default=0) + 1
        while True:
            run_dir = runs / f"RUN-{number:04d}"
            try:
                run_dir.mkdir()
            except FileExistsError:
                number += 1
                continue
            return f"{experiment_id}-RUN-{number:04d}", run_dir

    def write_run(self, run_dir: Path, record: dict[str, Any]) -> None:
        path = run_dir / "result.json"
        if path.exists():
            current = read_json(path)
            if current.get("status") != "running":
                raise ExperimentError(f"{record['run_id']} is final; run records are never overwritten")
        _atomic_write(path, canonical_json(record))

    def resolve_run(self, run_id: str) -> tuple[Path, dict[str, Any]]:
        match = RUN_ID.match(run_id or "")
        if not match:
            raise ExperimentError(f"Not a run ID: {run_id!r} (expected V3D-EXP-0001-RUN-0001 form)")
        run_dir = self.experiment_dir(match.group(1)) / "runs" / f"RUN-{match.group(2)}"
        path = run_dir / "result.json"
        if not path.is_file():
            raise ExperimentError(f"{run_id} is not recorded")
        return run_dir, read_json(path)
