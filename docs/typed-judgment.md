# Typed judgment in R.A.I.N. Lab

Typed judgment is an optional, independent evaluation layer for a single
candidate claim and a bounded evidence packet. It sits after the existing peer
critique score and before discovery promotion. It is decision support and
epistemic routing; it is not scientific proof and is not another R.A.I.N.
persona.

```text
Agents / Evidence
      ↓
Peer Critique
      ↓
JudgmentProvider
      ↓
Atomic Questions
      ↓
Typed Answers + Probabilities + Confidence
      ↓
Deterministic JudgmentGate
      ↓
PASS / REVISE / HUMAN_REVIEW / UNAVAILABLE
      ↓
Discovery workflow
```

Generative agents propose and critique. Simulations and tools produce evidence.
The formal logic engine checks propositional consistency. A `JudgmentProvider`
evaluates five independent questions against the same immutable state. Ordinary
R.A.I.N. code then applies a fixed policy. Provider output cannot alter the
peer score, formal result, numerical result, questions, thresholds, or final
disposition rules.

The existing conversational `chat` and `rlm` modes do not produce a
machine-readable five-stage promotion record, so they remain unchanged. The
explicit strict-cycle command is the supported boundary:

```bash
python rain_lab.py judge --evidence cycle.json
```

## Evidence packet

The command accepts `rain-judgment-cycle/v1` JSON. The caller must curate the
packet from trusted host/tool output rather than agent prose:

```json
{
  "schema_version": "rain-judgment-cycle/v1",
  "claim": "The measured resonance peak is 40 Hz in this simulated setup.",
  "method": "Sweep 30 to 50 Hz with a fixed simulated load.",
  "observations": "A peak occurred at 40 Hz in three runs.",
  "quantitative_results": "Peaks [40, 40, 40] Hz; resolution 1 Hz.",
  "tool_evidence": "Run fixture-1 exported peaks [40, 40, 40].",
  "known_limitations": "Simulation only; no physical replication.",
  "source_identifiers": ["fixture-1"],
  "formal_logic_result": {"satisfiable": true, "model": {"peak": true}},
  "numerical_validation": {"passed": true, "details": "All peaks are inside the sweep bounds."},
  "synthesis_summary": "The simulated peak repeats at 40 Hz.",
  "peer_critique": {
    "reviewer": "R.A.I.N.Reviewer",
    "score": 9,
    "feedback": "The narrow simulated claim is supported; physical replication is missing."
  }
}
```

Unknown fields, duplicate JSON keys, malformed validation values, and packets
over 128 KiB fail before provider construction or artifact creation. Omitted
formal or numerical validation is recorded as `not_run`; it cannot pass the
gate. A peer score below 8 routes to revision without calling a provider.
This is reported as `NOT_RUN` with reason `peer_score_below_threshold`.

## Atomic questions

Question set `rain-atomic-1` asks:

- `claim_support` (`Choice`): supported, mixed, unsupported, or insufficient evidence.
- `evidence_quality` (`Score`): a four-level rubric from insufficient (0) to strong (3).
- `contradiction_present` (`Noul`): probability of a meaningful contradiction.
- `scope_violation` (`Noul`): probability that the claim exceeds the evidence.
- `human_review` (`Noul`): probability that explicit review is warranted.

TypeSafe Score values are fractional expected zero-based rubric indices. Choice
and Score include distributions and confidence. Noul is itself a yes
probability and has no separate confidence field. No answer is fed into another
question; every question sees the same canonical state.

## Deterministic policy

Policy `rain-gate-1` applies these rules in order:

1. Failed formal or numerical validation, missing measured evidence, or missing
   source identifiers yields `REVISE` before a remote provider is called.
2. Validation that was not run or errored, or state truncation, yields
   `HUMAN_REVIEW` before a remote provider is called.
3. A provider/configuration/transport/HTTP/malformed-response failure yields
   `UNAVAILABLE`. It never becomes a pass and never falls back to another model.
4. `mixed`, `unsupported`, or `insufficient_evidence`; evidence quality below
   2; or contradiction/scope probability at least 0.70 yields `REVISE`.
5. Choice/Score confidence below 0.80, or any Noul at least 0.20, yields
   `HUMAN_REVIEW` unless a revision rule already applies.
6. Only supported evidence quality of at least 2, confidence of at least 0.80,
   all Nouls below 0.20, passed local validations, and a complete state can
   yield `PASS`.

A `PASS` means the bounded promotion policy was satisfied. It does not mean a
hypothesis is scientifically true. SAT, numerical checks, citations, tool
outputs, peer critique, and typed judgment remain distinct evidence channels.

## TypeSafe Jev

Remote judgment is opt-in:

```bash
set RAIN_JUDGMENT_PROVIDER=typesafe
set TYPESAFE_API_KEY=replace-with-your-key
set TYPESAFE_MODEL=jev-latest
python rain_lab.py judge --evidence cycle.json
```

On macOS/Linux, use `export` instead of `set`. `off` is the default provider.
The default model alias is `jev-latest`; the concrete returned version is saved
in the artifact. The implementation uses the repository's existing `requests`
dependency against TypeSafe's documented System One endpoint. The official
Python SDK currently adds a second HTTP stack and newer Pydantic requirements,
so it was not added for this narrow integration.

There are no automatic retries or provider fallbacks. Timeouts, authentication
errors, rate limits, overload, transport errors, HTTP errors, oversized bodies,
and malformed answers are reduced to categorical codes. Exception strings and
response bodies are not persisted.

The client has a 5-second connection timeout, a 10-second read-idle timeout,
and checks a 30-second elapsed budget during response consumption. The response
is capped at 100,000 bytes. Choice must match a highest-probability option.
Score must match its probability-weighted level within 0.05; distributions must
sum to one within 0.01. These tolerances allow rounded provider responses.

## Privacy boundary

Only the allowlisted packet fields are rendered into this canonical remote state:

```text
CLAIM
METHOD
OBSERVATIONS
QUANTITATIVE RESULTS
SIMULATION / TOOL EVIDENCE
PEER CRITIQUE
FORMAL LOGIC RESULT
KNOWN LIMITATIONS
SOURCE IDENTIFIERS
HOST VALIDATION STATUS
```

The builder never reads the research library, meeting transcript, private
memory, environment context, or unrelated corpus. Each field is
limited to 4,000 characters and the state to 24,000 characters. Truncation is
marked in the state and metadata and forces human review. If the configured API
key appears in the state, no request is sent and the state body is withheld
from persistence.

A separate boundary guard checks configured credential values and common
credential patterns, including bearer tokens and PEM private keys. It never
adds environment values to the state. Pattern detection cannot recognize every
possible secret: the caller remains responsible for curating a shareable packet.
Sensitive state is replaced with a withheld marker and hash before recording.

TypeSafe documents that adversarial or irrelevant state can influence Jev and
that Jev is not a numerical or scientific verifier. Packet producers must
treat source text as untrusted and keep deterministic validation authoritative.

## Flight recorder and replay

Session artifacts retain grounding turns and add a separate `judgments` array.
Each envelope records the schema and judgment IDs, timestamp, provider and
returned model, question definitions and version, canonical state and SHA-256,
truncation, local validation status, typed answers, distributions, confidence
where the primitive provides it, disposition, policy version, reason codes,
latency, and sanitized provider error status.
An `envelope_hash` covers all recorded envelope fields. Judgments are atomically
checkpointed before workflow promotion, separately from existing grounding.

Illustrative excerpt:

```json
{
  "schema_version": 1,
  "judgment_id": "3f0f...",
  "mode": "live_evaluation",
  "provider": "typesafe",
  "model": "jev-1.13.0",
  "question_set_version": "rain-atomic-1",
  "state_hash": "8d4f...",
  "state_truncation": {"truncated": false, "fields": []},
  "answers": [
    {
      "question_id": "claim_support",
      "type": "choice",
      "answer": "supported",
      "probabilities": {"supported": 0.91, "mixed": 0.04, "unsupported": 0.03, "insufficient_evidence": 0.02},
      "confidence": 0.88
    }
  ],
  "disposition": "PASS",
  "gate_policy_version": "rain-gate-1",
  "reason_codes": ["bounded_support_requirements_met"],
  "provider_error": null,
  "envelope_hash": "2bf1..."
}
```

Replay reads recorded envelopes and verifies both the canonical state hash and
the complete envelope digest. It never constructs a provider or silently
re-evaluates:

```bash
python rain_lab.py judge --replay meeting_archives/session_artifacts/session_<id>.json
python -m james_library.utilities.session_replay --recorded-artifact session_<id>.json
```

The output is labeled `RECORDED JUDGMENT`. Gold-session replay always disables
typed judgment in its chat subprocesses. It rejects `--live-judgment` before
reading inputs, creating outputs, or launching subprocesses because those chat
sessions do not implement the typed promotion boundary. To evaluate again,
explicitly run `rain_lab.py judge --evidence cycle.json` with TypeSafe enabled.
This creates a new judgment rather than rewriting a recorded one.
Offline child environments omit the TypeSafe key. Digests detect accidental
or partial modification, not an attacker who can rewrite both data and digest;
these artifacts are not digitally signed.

Current TypeSafe contracts were checked from the official
[`llms.txt`](https://docs.typesafe.ai/llms.txt),
[`API reference`](https://docs.typesafe.ai/api), and
[`Python SDK`](https://github.com/typesafe-ai/typesafe-sdk-python).
