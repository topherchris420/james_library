"""Tests for the epistemic failsafe stagnation monitor."""

import pytest

from stagnation_monitor import (
    DeadEndDetector,
    MonitorVerdict,
    StagnationDetector,
    StagnationMonitor,
)


# ---------------------------------------------------------------------------
# DeadEndDetector
# ---------------------------------------------------------------------------


class TestDeadEndDetector:
    def test_no_dead_end_on_diverse_outputs(self):
        det = DeadEndDetector(window_size=3, threshold=0.95, consecutive_hits=3)
        assert not det.check("The resonance frequency is 432 Hz.")
        assert not det.check("We should consider plate geometry next.")
        assert not det.check("Chladni patterns emerge at eigenfrequencies.")
        assert not det.check("Let us review the amplitude data from the sim.")

    def test_dead_end_on_repeated_content(self):
        det = DeadEndDetector(window_size=3, threshold=0.95, consecutive_hits=3)
        base = "The standing wave forms a nodal pattern at 256 Hz on a circular plate."
        # First occurrence just seeds the window.
        assert not det.check(base)
        # Streak starts at 1, 2, then hits 3.
        assert not det.check(base)
        assert not det.check(base)
        assert det.check(base)

    def test_near_duplicate_triggers_dead_end(self):
        det = DeadEndDetector(window_size=3, threshold=0.90, consecutive_hits=3)
        v1 = "We observe resonance at approximately 440 Hz with high amplitude."
        v2 = "We observe resonance at approximately 440 Hz with high amplitude!"
        v3 = "We observe resonance at approximately 440 Hz with high amplitude.."
        v4 = "We observe resonance at approximately 440 Hz with high amplitude..."
        assert not det.check(v1)
        assert not det.check(v2)
        assert not det.check(v3)
        assert det.check(v4)

    def test_streak_resets_on_novel_input(self):
        det = DeadEndDetector(window_size=3, threshold=0.95, consecutive_hits=3)
        same = "Identical output from the agent."
        assert not det.check(same)
        assert not det.check(same)
        # Break the streak with something different.
        assert not det.check("Completely different topic about quantum decoherence.")
        # Restart — streak should reset.
        assert not det.check(same)
        assert not det.check(same)

    def test_reset_clears_state(self):
        det = DeadEndDetector(window_size=3, threshold=0.95, consecutive_hits=3)
        same = "Repetitive content for testing."
        det.check(same)
        det.check(same)
        det.check(same)
        det.reset()
        # After reset the streak is gone.
        assert not det.check(same)

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError):
            DeadEndDetector(threshold=0.0)
        with pytest.raises(ValueError):
            DeadEndDetector(threshold=1.5)

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError):
            DeadEndDetector(window_size=0)


# ---------------------------------------------------------------------------
# StagnationDetector
# ---------------------------------------------------------------------------


class TestStagnationDetector:
    def test_no_stagnation_on_diverse_outputs(self):
        det = StagnationDetector(window_size=3, variance_threshold=0.01, mean_threshold=0.15)
        responses = [
            "Acoustic resonance at 432 Hz on a steel plate.",
            "Quantum decoherence limits information transfer.",
            "The topology of the field gradient is non-trivial.",
            "Hardware constraints: piezo driver max voltage is 30V.",
            "Eigenfrequency spacing depends on plate boundary conditions.",
        ]
        for r in responses:
            assert not det.check(r)

    def test_stagnation_on_low_variance_novelty(self):
        det = StagnationDetector(window_size=5, variance_threshold=0.01, mean_threshold=0.20)
        # Feed very similar content repeatedly so novelty stays near zero.
        base = "The experiment shows resonance patterns consistent with previous results."
        for i in range(6):
            # Minor variation to avoid being *identical* but keeping similarity high.
            result = det.check(f"{base} Iteration {i}.")
        # After enough low-novelty turns the detector should trigger.
        assert det.check(f"{base} Iteration final.")

    def test_needs_full_window_before_triggering(self):
        det = StagnationDetector(window_size=5, variance_threshold=0.01, mean_threshold=0.20)
        same = "Exact same content every turn."
        # With window_size=5 we need at least 5 novelty scores before checking.
        for _ in range(4):
            assert not det.check(same)

    def test_reset_clears_state(self):
        det = StagnationDetector(window_size=3, variance_threshold=0.01, mean_threshold=0.20)
        same = "Repetitive low-novelty content."
        for _ in range(5):
            det.check(same)
        det.reset()
        # After reset, not enough data to trigger.
        assert not det.check(same)

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError):
            StagnationDetector(window_size=1)


# ---------------------------------------------------------------------------
# StagnationMonitor (facade)
# ---------------------------------------------------------------------------


class TestStagnationMonitor:
    def test_clean_verdict_on_normal_conversation(self):
        monitor = StagnationMonitor()
        verdict = monitor.check("Fresh and original scientific discussion point.")
        assert isinstance(verdict, MonitorVerdict)
        assert not verdict.is_dead_end
        assert not verdict.is_stagnant
        assert verdict.intervention_prompt is None

    def test_dead_end_returns_intervention_prompt(self):
        monitor = StagnationMonitor(
            dead_end_window=3,
            dead_end_threshold=0.95,
            dead_end_consecutive=3,
        )
        same = "Agents keep agreeing on the same conclusion without new evidence."
        monitor.check(same)
        monitor.check(same)
        monitor.check(same)
        verdict = monitor.check(same)
        assert verdict.is_dead_end
        assert verdict.intervention_prompt is not None
        assert "Dead-end loop detected" in verdict.intervention_prompt

    def test_stagnation_returns_intervention_prompt(self):
        monitor = StagnationMonitor(
            stagnation_window=4,
            stagnation_variance=0.02,
            stagnation_mean=0.25,
            # Raise dead-end threshold so only stagnation fires.
            dead_end_threshold=0.999,
            dead_end_consecutive=100,
        )
        # Feed slightly varied but highly similar content.
        for i in range(7):
            verdict = monitor.check(
                f"The resonance result is consistent with prior observation number {i}."
            )
        assert verdict.is_stagnant
        assert verdict.intervention_prompt is not None
        assert "stagnation detected" in verdict.intervention_prompt.lower()

    def test_intervention_prompt_format(self):
        monitor = StagnationMonitor(
            dead_end_window=2, dead_end_threshold=0.95, dead_end_consecutive=2,
        )
        same = "Exactly the same text every single turn in the meeting."
        monitor.check(same)
        monitor.check(same)
        verdict = monitor.check(same)
        assert verdict.intervention_prompt is not None
        assert verdict.intervention_prompt.startswith("SYSTEM OVERRIDE:")

    def test_reset_clears_all_state(self):
        monitor = StagnationMonitor(
            dead_end_window=2, dead_end_threshold=0.95, dead_end_consecutive=2,
        )
        same = "Same output."
        monitor.check(same)
        monitor.check(same)
        monitor.reset()
        verdict = monitor.check(same)
        assert not verdict.is_dead_end
        assert not verdict.is_stagnant
