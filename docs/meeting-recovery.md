# Adaptive meeting recovery

The Python expert-panel meeting started by `python rain_lab.py --mode chat --topic "..."`
uses the existing local repetition detectors to adjust a stalled discussion.
Recovery adds no model requests or network access of its own.

| When repetition persists | Next action |
| --- | --- |
| First detection | Request specific evidence or a missing measurement; distinguish source material from inference. |
| After the panel has had a full round to respond | Request a falsifiable alternative and a distinguishing test. |
| After another full round without recovery | Move into the configured closing turns and summarize unresolved questions. |

For the four-agent panel, each intervention allows four complete turns before
another intervention can fire. Four consecutive turns without either detector
flag reset escalation. A new meeting or a substantive founder instruction also
resets recovery and detector history. Once closing begins, recovery cannot
restart the debate. The configured total turn limit is always an upper bound;
zero closing turns means an immediate end after the final recovery decision.

The detectors measure textual similarity, not scientific validity. Similar
wording can be legitimate, and different wording can still repeat an idea.
Recovery does not itself prove or disprove hypotheses, verify new evidence, or
establish consensus. Its instructions preserve supported findings and ask for
explicit uncertainty. Existing detector thresholds and the optional formal
circuit-breaker API are unchanged.

Recovery messages appear as `SYSTEM` turns after the response that triggered
them, in both the transcript and the session JSON. In the existing
`rain-session-artifact/v1` envelope, recovery turns additionally contain:

```json
"metadata": {
  "verified_count": 0,
  "unverified_count": 0,
  "citation_rate": 0.0,
  "recovery": {"action": "evidence", "reason": "dead_end"}
}
```

Actions are `evidence`, `alternative`, and `wrap_up`; reasons are `dead_end` or
`stagnation`. Ordinary turns retain their existing metadata. No new setup or
configuration keys are required. This behavior applies to the Python meeting
coordinator; the Rust autonomous runtime and isolated peer-review swarm retain
their own controls.

## Verification

```bash
pytest -q tests/test_meeting_recovery.py tests/test_meeting_recovery_integration.py tests/test_session_artifact.py
```

The deterministic loop fixture supplies the same response to all four agents.
With a 30-turn limit and four closing turns, actions fire after discussion turns
4, 9, and 14; the meeting finishes after 18 model-response turns, including one
closing turn for every agent. This is a synthetic control-flow result, not a
measurement of model quality or real-world time savings. Tests also cover
recovered discussion, cooldown boundaries, ordinary wrap-up, zero closing turns,
session reuse, and artifact ordering.
