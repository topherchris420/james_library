"""Opt-in next-step proposals. Scientific substance remains with the R.A.I.N. team."""

from .routing import DecisionRequest

PROCESS_ACTIONS = (
    ("CONTINUE", "Continue the current research direction."),
    ("VERIFY", "Independently check the current finding."),
    ("SWITCH_EXPERT", "Ask a different expert to inspect the subproblem."),
    ("SEARCH_EVIDENCE", "Gather more supporting or contradicting evidence."),
    ("CHALLENGE_ASSUMPTION", "Test a premise of the current reasoning."),
    ("SYNTHESIZE", "Ask the research team to summarize the available evidence."),
    ("ESCALATE_TO_HUMAN", "Request explicit human review."),
    ("STOP", "End this bounded research step without promoting its claims."),
)


def propose_next_step(router, *, state, allowed_actions, validator, enabled=False,
                      recorder=None, remote_allowed=False, consequence="high"):
    """Return None to preserve the normal workflow when disabled or escalated.

    The host curates state and allowed actions, persists before consuming a
    proposal, and owns execution. This function cannot change a meeting stage.
    """
    if type(enabled) is not bool:
        raise ValueError("metacognitive control must be boolean")
    if not enabled:
        return None
    if (not isinstance(allowed_actions, tuple) or len(set(allowed_actions)) != len(allowed_actions)
            or not set(allowed_actions) <= set(dict(PROCESS_ACTIONS))):
        raise ValueError("invalid research-process actions")
    request = DecisionRequest(
        "research_process", state,
        "Which allowed research-process action should the team consider next? "
        "Choose ESCALATE_TO_HUMAN when none fits and it is offered.",
        tuple((key, dict(PROCESS_ACTIONS)[key]) for key in allowed_actions),
        consequence=consequence, remote_allowed=remote_allowed,
    )
    envelope = router.decide(request, validator=validator)
    if recorder is not None:
        recorder(envelope)
    return envelope if envelope.destination == "proposal" else None


class MeetingProcessController:
    """Host integration for bounded hints at existing chat-turn boundaries."""

    def __init__(self, router, *, remote_allowed=False):
        self.router = router
        self.remote_allowed = remote_allowed

    def suggest(self, *, turn_count, max_turns, verified_count, recorder):
        # No transcript, topic, paper, private memory, or inferred human state.
        # Bounds and counters are sufficient for this experimental process hint.
        if (any(type(n) is not int or n < 0 for n in (turn_count, max_turns, verified_count))
                or turn_count >= max_turns or recorder is None):
            return None
        state = (f"Completed turns: {turn_count}. Turn budget: {max_turns}. "
                 f"Verified citations in the latest turn: {verified_count}.")
        return propose_next_step(
            self.router, state=state,
            allowed_actions=("CONTINUE", "VERIFY", "CHALLENGE_ASSUMPTION", "SYNTHESIZE"),
            validator=lambda request, choice: turn_count < max_turns and (
                choice is None or choice in dict(request.choices)
            ), enabled=True, recorder=recorder, remote_allowed=self.remote_allowed, consequence="low",
        )


def create_process_controller():
    from .config import create_decision_router, enabled
    if not enabled("RAIN_METACOGNITIVE_CONTROL"):
        return None
    return MeetingProcessController(create_decision_router(), remote_allowed=enabled("RAIN_DECISION_REMOTE_ALLOWED"))


PROCESS_HINTS = {
    "CONTINUE": "Continue the current research direction within the existing evidence constraints.",
    "VERIFY": "Independently verify the current finding; state what remains unsupported.",
    "CHALLENGE_ASSUMPTION": "Identify and challenge a premise of the current reasoning.",
    "SYNTHESIZE": "Summarize the evidence and disagreements without promoting an unverified claim.",
}
