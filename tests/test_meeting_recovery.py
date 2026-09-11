"""Exercise recovery as a bounded feedback policy, without model calls."""

import pytest

from james_library.utilities.meeting_recovery import MeetingRecoveryController
from stagnation_monitor import MonitorVerdict, StagnationMonitor


LOOP = MonitorVerdict(is_dead_end=True)
CLEAR = MonitorVerdict()


def test_repeated_responses_get_two_recovery_attempts_then_one_wrap_up():
    monitor = StagnationMonitor()
    controller = MeetingRecoveryController()
    actions = []
    for turn in range(1, 31):
        verdict = monitor.check("The standing wave forms a nodal pattern on a circular plate.")
        decision = controller.observe(verdict)
        if decision:
            actions.append((turn, decision.action))

    assert actions == [(4, "evidence"), (9, "alternative"), (14, "wrap_up")]


def test_varied_responses_need_no_intervention():
    monitor = StagnationMonitor()
    controller = MeetingRecoveryController()
    for text in (
        "Measure thermal drift over a ten minute run.",
        "Boundary geometry changes the allowed eigenmodes.",
        "What instrument calibration uncertainty applies?",
        "A blinded control group could separate expectation from the intervention.",
        "Latency is limited by the acquisition buffer length.",
        "The sample is insufficient to estimate the treatment effect.",
    ):
        assert controller.observe(monitor.check(text)) is None


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [(LOOP, "dead_end"), (MonitorVerdict(is_stagnant=True), "stagnation")],
)
def test_actions_preserve_the_detection_reason(verdict, reason):
    decision = MeetingRecoveryController().observe(verdict)
    assert decision.action == "evidence"
    assert decision.reason == reason


def test_cooldown_counts_complete_turns_even_if_detector_remains_flagged():
    controller = MeetingRecoveryController(cooldown_turns=2)
    assert controller.observe(LOOP).action == "evidence"
    assert controller.observe(LOOP) is None
    assert controller.observe(LOOP) is None
    assert controller.observe(LOOP).action == "alternative"


def test_sustained_clear_turns_restore_the_first_recovery_step():
    controller = MeetingRecoveryController()
    assert controller.observe(LOOP).action == "evidence"
    for _ in range(4):
        assert controller.observe(CLEAR) is None
    assert controller.observe(LOOP).action == "evidence"


def test_one_clear_turn_does_not_erase_an_unresolved_loop():
    controller = MeetingRecoveryController(cooldown_turns=1)
    controller.observe(LOOP)
    assert controller.observe(CLEAR) is None
    assert controller.observe(LOOP).action == "alternative"


def test_reset_reopens_recovery_after_a_terminal_decision():
    controller = MeetingRecoveryController(cooldown_turns=1)
    decisions = [controller.observe(LOOP) for _ in range(5)]
    assert decisions[-1].action == "wrap_up"
    for _ in range(10):
        assert controller.observe(CLEAR) is None
    assert controller.observe(LOOP) is None
    controller.reset()
    assert controller.observe(LOOP).action == "evidence"


def test_wrap_up_does_not_inject_or_advance_recovery():
    controller = MeetingRecoveryController()
    for _ in range(10):
        assert controller.observe(LOOP, is_wrap_up=True) is None
    assert controller.observe(LOOP).action == "evidence"


def test_formal_verdict_is_preserved_in_the_recovery_instruction():
    verdict = MonitorVerdict(
        is_dead_end=True, is_circuit_breaker=True, intervention_prompt="Verified constraint contradiction."
    )
    decision = MeetingRecoveryController().observe(verdict)
    assert decision.prompt.startswith(verdict.intervention_prompt)
    assert decision.action == "evidence"


@pytest.mark.parametrize("field", ["cooldown_turns", "recovery_turns"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_turn_limits_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        MeetingRecoveryController(**{field: value})
