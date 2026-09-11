"""Bounded, deterministic recovery for repetitive research meetings.

Similarity is a scheduling signal, not evidence that a hypothesis is false.
Give the panel time to respond before escalating, and preserve a final summary
when two recovery attempts fail to restore varied discussion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from stagnation_monitor import MonitorVerdict

RecoveryAction = Literal["evidence", "alternative", "wrap_up"]


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: Literal["dead_end", "stagnation"]
    prompt: str


_RECOVERY_STEPS: tuple[tuple[RecoveryAction, str], ...] = (
    (
        "evidence",
        "Revisit one repeated claim. Identify the specific supporting evidence or the "
        "missing measurement. Separate quoted source material from inference, and preserve "
        "supported findings. Do not invent citations or treat repetition as disproof.",
    ),
    (
        "alternative",
        "The evidence check has not resolved the repetition. Propose one falsifiable "
        "alternative and a measurement that would distinguish it from the current "
        "hypothesis. State what remains unknown; do not discard verified evidence.",
    ),
    (
        "wrap_up",
        "Two recovery attempts have not resolved the repetition. Begin the final summary: "
        "preserve supported findings, disagreements, unresolved questions, and the next "
        "test or source needed. Do not declare consensus or a discovery from repetition.",
    ),
)


class MeetingRecoveryController:
    """Escalate once per panel round; reset after sustained varied discussion.

    ``cooldown_turns`` is the number of complete turns allowed after an action
    before another action may fire. ``recovery_turns`` consecutive unflagged
    turns reset escalation. A wrap-up decision is terminal until ``reset()``.
    """

    def __init__(self, *, cooldown_turns: int = 4, recovery_turns: int = 4) -> None:
        if isinstance(cooldown_turns, bool) or not isinstance(cooldown_turns, int) or cooldown_turns < 1:
            raise ValueError("cooldown_turns must be a positive integer")
        if isinstance(recovery_turns, bool) or not isinstance(recovery_turns, int) or recovery_turns < 1:
            raise ValueError("recovery_turns must be a positive integer")
        self._cooldown_turns = cooldown_turns
        self._recovery_turns = recovery_turns
        self.reset()

    def reset(self) -> None:
        """Start a new session or respond to a new human instruction."""
        self._step = 0
        self._cooldown_remaining = 0
        self._clear_turns = 0

    def observe(self, verdict: MonitorVerdict, *, is_wrap_up: bool = False) -> RecoveryDecision | None:
        if is_wrap_up or self._step == len(_RECOVERY_STEPS):
            return None

        flagged = verdict.is_dead_end or verdict.is_stagnant
        self._clear_turns = 0 if flagged else self._clear_turns + 1
        if self._clear_turns >= self._recovery_turns:
            self.reset()
            return None

        if self._cooldown_remaining:
            self._cooldown_remaining -= 1
            return None
        if not flagged:
            return None

        action, instruction = _RECOVERY_STEPS[self._step]
        self._step += 1
        self._cooldown_remaining = self._cooldown_turns
        reason: Literal["dead_end", "stagnation"] = "dead_end" if verdict.is_dead_end else "stagnation"
        prompt = f"SYSTEM OVERRIDE: Adaptive recovery ({action}; {reason}). {instruction}"
        if verdict.is_circuit_breaker and verdict.intervention_prompt:
            prompt = f"{verdict.intervention_prompt}\n{prompt}"
        return RecoveryDecision(action=action, reason=reason, prompt=prompt)
