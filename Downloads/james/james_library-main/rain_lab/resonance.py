"""Resonance/frequency detection for agent utterances."""

from __future__ import annotations

from .sanitize import RE_FREQUENCY, RE_RESONANCE_KEYWORDS


class ResonanceDetector:
    """Scan agent utterances for frequency/resonance discussion.

    Maintains a small rolling window of recently mentioned frequencies so
    that ``consensus_stability`` can rise when multiple agents converge on
    similar values and fall when discussion diverges.
    """

    _WINDOW_SIZE = 8

    def __init__(self) -> None:
        self._recent_frequencies: list[float] = []
        self._last_emitted_freq: float = 0.0
        self._last_stability: float = 0.0

    def analyze(self, text: str) -> "dict[str, float] | None":
        """Return a resonance_state payload dict, or *None* if nothing detected."""

        keyword_hits = len(RE_RESONANCE_KEYWORDS.findall(text))
        freq_matches = RE_FREQUENCY.findall(text)

        if keyword_hits == 0 and not freq_matches:
            return None

        if freq_matches:
            target_freq = float(freq_matches[-1])
        elif self._recent_frequencies:
            target_freq = self._recent_frequencies[-1]
        else:
            target_freq = 432.0

        self._recent_frequencies.append(target_freq)
        if len(self._recent_frequencies) > self._WINDOW_SIZE:
            self._recent_frequencies = self._recent_frequencies[-self._WINDOW_SIZE :]

        amplitude = min(1.0, 0.25 + keyword_hits * 0.15)
        stability = self._compute_stability()

        self._last_emitted_freq = target_freq
        self._last_stability = stability

        return {
            "target_frequency": round(target_freq, 2),
            "amplitude": round(amplitude, 3),
            "consensus_stability": round(stability, 3),
        }

    def _compute_stability(self) -> float:
        n = len(self._recent_frequencies)
        if n < 2:
            return 0.5
        mean = sum(self._recent_frequencies) / n
        if mean == 0.0:
            return 1.0
        variance = sum((f - mean) ** 2 for f in self._recent_frequencies) / n
        cv = (variance**0.5) / mean
        return max(0.0, min(1.0, 1.0 - cv * 2.0))
