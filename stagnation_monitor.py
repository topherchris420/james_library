"""Epistemic failsafe: stagnation and dead-end detection for R.A.I.N. Lab meetings.

Prevents agents from falling into agreement loops or hallucination spirals
by tracking content similarity and novelty variance across meeting turns.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class MonitorVerdict:
    """Result of a single stagnation check."""

    is_dead_end: bool = False
    is_stagnant: bool = False
    intervention_prompt: str | None = None


# ---------------------------------------------------------------------------
# Dead-end detection
# ---------------------------------------------------------------------------

class DeadEndDetector:
    """Track content hashes over a sliding window and flag near-duplicate runs.

    A dead end is declared when the current response is >= *threshold*
    similar to any of the last *window_size* responses for at least
    *consecutive_hits* consecutive turns.
    """

    def __init__(
        self,
        window_size: int = 3,
        threshold: float = 0.95,
        consecutive_hits: int = 3,
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        if consecutive_hits < 1:
            raise ValueError("consecutive_hits must be >= 1")

        self._window: deque[str] = deque(maxlen=window_size)
        self._threshold = threshold
        self._consecutive_hits = consecutive_hits
        self._streak = 0

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    def check(self, response: str) -> bool:
        """Return True when a dead end is detected."""
        normalized = self._normalize(response)

        if self._window:
            max_sim = max(
                SequenceMatcher(None, normalized, prev).ratio()
                for prev in self._window
            )
            if max_sim >= self._threshold:
                self._streak += 1
            else:
                self._streak = 0
        else:
            self._streak = 0

        self._window.append(normalized)
        return self._streak >= self._consecutive_hits

    def reset(self) -> None:
        self._window.clear()
        self._streak = 0


# ---------------------------------------------------------------------------
# Stagnation detection (novelty variance)
# ---------------------------------------------------------------------------

class StagnationDetector:
    """Track novelty scores over a sliding window and flag low-variance runs.

    Novelty is defined as ``1.0 - max_similarity_to_recent_turns``.
    When the variance of the novelty window drops below *variance_threshold*
    AND the mean novelty is below *mean_threshold*, stagnation is declared.
    """

    def __init__(
        self,
        window_size: int = 5,
        variance_threshold: float = 0.01,
        mean_threshold: float = 0.15,
    ) -> None:
        if window_size < 2:
            raise ValueError("window_size must be >= 2")

        self._history: deque[str] = deque(maxlen=window_size + 1)
        self._novelty_scores: deque[float] = deque(maxlen=window_size)
        self._variance_threshold = variance_threshold
        self._mean_threshold = mean_threshold
        self._window_size = window_size

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    def _novelty(self, normalized: str) -> float:
        if not self._history:
            return 1.0
        max_sim = max(
            SequenceMatcher(None, normalized, prev).ratio()
            for prev in self._history
        )
        return 1.0 - max_sim

    def check(self, response: str) -> bool:
        """Return True when epistemic stagnation is detected."""
        normalized = self._normalize(response)
        score = self._novelty(normalized)
        self._history.append(normalized)
        self._novelty_scores.append(score)

        if len(self._novelty_scores) < self._window_size:
            return False

        mean = sum(self._novelty_scores) / len(self._novelty_scores)
        variance = sum(
            (s - mean) ** 2 for s in self._novelty_scores
        ) / len(self._novelty_scores)

        return variance < self._variance_threshold and mean < self._mean_threshold

    def reset(self) -> None:
        self._history.clear()
        self._novelty_scores.clear()


# ---------------------------------------------------------------------------
# Combined monitor facade
# ---------------------------------------------------------------------------

_DEFAULT_INTERVENTION = (
    "SYSTEM OVERRIDE: Epistemic stagnation detected. "
    "Agents must pivot to a contradictory theory immediately."
)

_DEAD_END_INTERVENTION = (
    "SYSTEM OVERRIDE: Dead-end loop detected — recent outputs are near-identical. "
    "Agents must abandon the current line of reasoning and propose a fundamentally "
    "different approach."
)


class StagnationMonitor:
    """Unified facade that combines dead-end and stagnation detection.

    Usage::

        monitor = StagnationMonitor()
        verdict = monitor.check(agent_response_text)
        if verdict.intervention_prompt:
            history_log.append(verdict.intervention_prompt)
    """

    def __init__(
        self,
        *,
        dead_end_window: int = 3,
        dead_end_threshold: float = 0.95,
        dead_end_consecutive: int = 3,
        stagnation_window: int = 5,
        stagnation_variance: float = 0.01,
        stagnation_mean: float = 0.15,
    ) -> None:
        self._dead_end = DeadEndDetector(
            window_size=dead_end_window,
            threshold=dead_end_threshold,
            consecutive_hits=dead_end_consecutive,
        )
        self._stagnation = StagnationDetector(
            window_size=stagnation_window,
            variance_threshold=stagnation_variance,
            mean_threshold=stagnation_mean,
        )

    def check(self, response: str) -> MonitorVerdict:
        """Evaluate a single agent response and return a verdict."""
        is_dead = self._dead_end.check(response)
        is_stagnant = self._stagnation.check(response)

        if is_dead:
            return MonitorVerdict(
                is_dead_end=True,
                is_stagnant=is_stagnant,
                intervention_prompt=_DEAD_END_INTERVENTION,
            )
        if is_stagnant:
            return MonitorVerdict(
                is_stagnant=True,
                intervention_prompt=_DEFAULT_INTERVENTION,
            )
        return MonitorVerdict()

    def reset(self) -> None:
        """Clear all internal state (e.g. between meeting sessions)."""
        self._dead_end.reset()
        self._stagnation.reset()
