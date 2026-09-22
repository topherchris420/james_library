# Typed judgment implementation plan

**Goal:** Add an independent, opt-in bounded evaluation layer before discovery promotion.

**Architecture:** A Python judgment package owns immutable contracts, evidence selection,
TypeSafe transport, and deterministic policy. The existing MeetingWorkflow owns promotion.
SessionArtifactWriter records the additional envelope; recorded replay never constructs a provider.

**Tech stack:** Python 3.10+, standard library, existing requests dependency, pytest.

**Spec:** The requested typed judgment layer, with TypeSafe's current HTTP contract
documented in the [official API reference](https://docs.typesafe.ai/api)
and discovered via its llms.txt index.

## Constraints and findings

- Remote access is off by default; TYPESAFE_API_KEY is used only for authentication.
- Preserve peer score, SAT solver, numerical evidence, citations, and public disabled behavior.
- No new dependency, chat provider, persona, comparison adapter, or corpus upload.
- Initial upstream base: 4e1b1c06; rebased onto 00c686af after the upstream update.
  Both conversational entrypoints are separate from the
  five-stage state manager. Source search and graph trace found no callers of its promotion
  gate. Expose a curated-packet `rain_lab.py judge` entrypoint rather than invent trusted
  measurements by parsing prose or change the existing conversational loops.
- The official SDK 0.7.1 introduces httpx2 and higher Pydantic floors. Use existing requests
  against the documented API, with strict answer validation and categorical sanitized errors.
- Score is fractional on [0,3]. Noul has no separate confidence. Never synthesize confidence.
- Formal/numerical results are host supplied evidence channels; model answers cannot set them.

## Task 1: Independent judgment contracts and policy

Create `james_library/judgment/{__init__,contracts,state,gate,typesafe,service}.py`
and `tests/test_judgment.py`, `tests/test_typesafe_judgment.py`.

- [x] Write offline tests for immutable atomic questions and documented response parsing.
- [x] Write state determinism, explicit truncation, privacy and malformed answer tests.
- [x] Implement `ClaimEvidence`, `JudgmentState`, `QuestionSet`, typed answers,
  `JudgmentResult`, `JudgmentProvider`, `DeterministicMockJudgmentProvider`.
- [x] Implement allowlisted state rendering with explicit missing fields, size limits,
  canonical SHA-256 and truncation metadata; exclude entire context/corpus by construction.
- [x] Implement the fixed endpoint client, timeouts, no retries/redirects/fallback,
  and sanitized finite error codes. Test auth/transport/malformed failures without network.
- [x] Implement JudgmentGate with versioned fixed conservative defaults and test each route.

## Task 2: Workflow, flight recorder, and executable boundary

Modify `james_library/launcher/meeting_workflow.py`,
`james_library/launcher/rain_lab.py`, `james_library/utilities/session_artifact.py`,
`james_library/utilities/session_replay.py`; create `james_library/launcher/judgment_cli.py`.
Tests live in `tests/test_judgment_workflow.py` and `tests/test_judgment_artifact.py`.

- [x] Lock score-only promotion and recovery behavior before edits.
- [x] Require an evidence packet matching the current claim/critique for enabled promotion.
- [x] Cache within a cycle, invalidate stale decisions on any setter, and retain all attempts.
- [x] Route REVISE to hypothesis; keep HUMAN_REVIEW/UNAVAILABLE at peer critique.
- [x] Persist envelopes separately from grounding records, including hashes, versions,
  typed answers, uncertainty, local validation, disposition, reasons and safe provider status.
- [x] Add explicit curated JSON packet command through the existing launcher subcommand pattern.
- [x] Add recorded-artifact replay with zero network/subprocess calls; existing live gold
  replay must disable remote judgment. Explicit reevaluation uses `judge --evidence`;
  gold replay rejects unsupported live-judgment requests.
- [x] Verify packet command end to end with a deterministic mock, including failed validation.

## Task 3: Documentation, review, and delivery

- [x] Document workflow diagram, exact default policy/precedence, data boundary,
  configuration, failure handling, artifacts, offline replay and limitations.
- [x] Link feature docs and update applicable command/config references and locale pointers.
- [x] Run focused Python tests, full Ruff, staged Ruff, mypy, full pytest, cargo fmt,
  cargo clippy, cargo test; record unrelated baseline failures precisely.
- [x] Review every changed file, diff scope, and secrets before scoped Lore commits.
- [x] Push only the feature branch, open a PR against main, and leave it unmerged.

Delivery: [PR #407](https://github.com/topherchris420/james_library/pull/407).

## Validation limitation

On the updated base, Rust formatting and Clippy pass. The full Rust test command
reports 4,765 passing, 23 failing, and 4 ignored library tests. All 23 failures
are existing secret-key file operations returning Windows access denied (OS error 5)
in auth/config/security/web-search tests. No Rust source or dependency was changed.
The Python judgment path is independently covered by offline tests.
