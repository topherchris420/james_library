"""Autonomy supervisor — the offline Python tier of the autonomous runtime.

Tails the JSONL streams written by the Rust runtime (single writer per file)
and drives the offline work that should never block the reasoning loop:

  - ``runtime/state_snapshots.jsonl`` → out-of-band alerts when the runtime
    enters ``alert`` / ``remediating``.
  - ``episodic_memory/episodic_events.jsonl`` → periodic segmentation into
    ``episodic_memory/episodes.jsonl`` via :mod:`rain_contracts.episodic`.

Core logic is synchronous and unit-testable; :class:`AutonomySupervisor`
is a thin asyncio shell with the same supervised-task-with-backoff pattern
used by the Rust channel listeners.

Stdlib only — no third-party dependencies.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from rain_contracts.episodic import EpisodicEventV2, segment_events

logger = logging.getLogger("autonomy_supervisor")

INCIDENT_STATES = ("alert", "remediating")


# ── JSONL tailing (sync core) ────────────────────────────────────


def tail_jsonl(path: Path | str, offset: int) -> tuple[list[dict], int]:
    """Read decoded JSON objects appended since ``offset``.

    Tolerates a partial trailing line (a writer mid-append): the offset only
    advances past complete, newline-terminated lines, so partial data is
    re-read on the next call. Malformed complete lines are skipped with a
    warning (they will not be re-read).
    """
    path = Path(path)
    if not path.exists():
        return [], offset

    records: list[dict] = []
    new_offset = offset
    with open(path, "rb") as f:
        f.seek(offset)
        for raw in f:
            if not raw.endswith(b"\n"):
                break  # partial trailing line — retry next pass
            new_offset += len(raw)
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("skipping malformed JSONL line: %s", exc)
    return records, new_offset


# ── State alerting (sync core) ───────────────────────────────────


def incident_alerts(snapshots: list[dict]) -> list[str]:
    """Render alert messages for snapshots that entered an incident state."""
    alerts = []
    for snap in snapshots:
        state = snap.get("state")
        if state in INCIDENT_STATES:
            alerts.append(
                f"R.A.I.N._runtime entered {state}: {snap.get('cause', 'unknown cause')} "
                f"(remediation attempts: {snap.get('remediation_attempts', 0)})"
            )
    return alerts


# ── Episode segmentation pass (sync core) ────────────────────────


def segment_new_events(
    events_path: Path | str,
    episodes_path: Path | str,
    offset_path: Path | str,
    *,
    gap_minutes: int = 20,
    now: datetime | None = None,
) -> int:
    """Segment newly appended events into episodes, idempotently.

    The byte offset of consumed events persists in ``offset_path``. The
    trailing episode is only written once it is *closed* — its last event is
    older than ``gap_minutes`` — so a session still in progress is never
    split prematurely. Returns the number of episodes written.
    """
    events_path = Path(events_path)
    episodes_path = Path(episodes_path)
    offset_path = Path(offset_path)
    now = now or datetime.now(timezone.utc)

    offset = 0
    if offset_path.exists():
        with contextlib.suppress(ValueError):
            offset = int(offset_path.read_text().strip() or 0)

    # Track per-record byte offsets so the offset can land on an episode
    # boundary rather than the end of the file.
    raw_records: list[tuple[dict, int]] = []  # (record, end_offset)
    if not events_path.exists():
        return 0
    with open(events_path, "rb") as f:
        f.seek(offset)
        position = offset
        for raw in f:
            if not raw.endswith(b"\n"):
                break
            position += len(raw)
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                raw_records.append((json.loads(line), position))
            except json.JSONDecodeError:
                logger.warning("segmenter: skipping malformed event line")

    if not raw_records:
        return 0

    events = [EpisodicEventV2.from_dict(rec) for rec, _ in raw_records]
    episodes = segment_events(events, gap_minutes=gap_minutes)

    # Determine which episodes are closed: every episode except possibly the
    # last, plus the last one when its final event is older than the gap.
    closed = episodes[:-1]
    last = episodes[-1]
    last_ts = events[-1].parsed_timestamp()
    if last_ts is not None and now - last_ts > timedelta(minutes=gap_minutes):
        closed.append(last)
        consumed_events = len(events)
    else:
        consumed_events = len(events) - last.event_count

    if not closed:
        return 0

    episodes_path.parent.mkdir(parents=True, exist_ok=True)
    with open(episodes_path, "a", encoding="utf-8") as f:
        for episode in closed:
            f.write(episode.to_jsonl() + "\n")

    new_offset = raw_records[consumed_events - 1][1] if consumed_events > 0 else offset
    offset_path.parent.mkdir(parents=True, exist_ok=True)
    offset_path.write_text(str(new_offset))
    logger.info("segmenter: wrote %d episode(s)", len(closed))
    return len(closed)


# ── Async shell ──────────────────────────────────────────────────


async def _log_alert(message: str) -> None:
    logger.warning("[autonomy alert] %s", message)


@dataclass
class AutonomySupervisor:
    """Supervised offline loops over the runtime's JSONL streams.

    Parameters
    ----------
    workspace_dir:
        The R.A.I.N. workspace (contains ``runtime/`` and
        ``episodic_memory/``).
    alerter:
        Async callable invoked with each incident alert message. Defaults to
        log-only; wire a channel sender for real out-of-band delivery.
    """

    workspace_dir: str = "."
    alerter: Callable[[str], Awaitable[None]] = _log_alert
    poll_seconds: float = 2.0
    segment_interval_seconds: float = 300.0
    gap_minutes: int = 20

    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _state_offset: int = field(default=0, init=False, repr=False)

    @property
    def _paths(self) -> dict[str, Path]:
        ws = Path(self.workspace_dir)
        return {
            "state": ws / "runtime" / "state_snapshots.jsonl",
            "events": ws / "episodic_memory" / "episodic_events.jsonl",
            "episodes": ws / "episodic_memory" / "episodes.jsonl",
            "offset": ws / "episodic_memory" / ".segmenter_offset",
        }

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(self._supervise(self._state_tail, "state_tail")),
            asyncio.create_task(self._supervise(self._segment_loop, "segmenter")),
        ]
        await self._stop.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stop.set()

    async def _supervise(self, factory: Callable[[], Awaitable[Any]], name: str) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await factory()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — supervisor boundary
                logger.error("%s crashed: %r; retry in %.0fs", name, exc, backoff)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                backoff = min(backoff * 2, 300.0)

    async def _state_tail(self) -> None:
        while not self._stop.is_set():
            snapshots, self._state_offset = tail_jsonl(
                self._paths["state"], self._state_offset
            )
            for alert in incident_alerts(snapshots):
                await self.alerter(alert)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)

    async def _segment_loop(self) -> None:
        while not self._stop.is_set():
            paths = self._paths
            await asyncio.to_thread(
                segment_new_events,
                paths["events"],
                paths["episodes"],
                paths["offset"],
                gap_minutes=self.gap_minutes,
            )
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.segment_interval_seconds
                )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="R.A.I.N. autonomy supervisor")
    parser.add_argument("--workspace", default=".", help="workspace directory")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(AutonomySupervisor(workspace_dir=args.workspace).run())
