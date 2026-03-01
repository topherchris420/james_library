# Bounded Agent Adaptation Policy

## Behavior Scope

The runtime allows bounded self-improvement in three surfaces only:

- **Memory adaptation**: context retrieval now prefers explicit memory cues (for example `remember`, `earlier`, `previous`) and uses bounded summarization for recalled entries.
- **Routing adaptation**: per-message model routing honors explicit classification signals and resolves to configured `hint:<route>` when the hint exists in model routes.
- **Tool strategy adaptation**: tool execution uses strict bounds (iteration budget, per-call timeout, bounded retries with deterministic backoff).

## Hard Safety Limits

- Maximum tool-loop iterations are still bounded by `agent.max_tool_iterations`.
- Tool calls have a fixed timeout and bounded retry budget.
- Retry behavior is deterministic and finite.
- Tool failures are explicit (no silent fallback broadening permissions).
- Tool outputs are credential-scrubbed before returning to the model history/logging path.

## Forbidden Autonomous Mutations

The agent does **not** autonomously apply runtime/policy/config/code mutations on restricted paths.

When a tool call proposes a restricted mutation (for example editing `src/*.rs`, config/policy-like targets, or runtime config mutators), execution is blocked and a structured **change request artifact** is emitted in the tool result payload.

## Human Approval Flow

1. Agent proposes a structured change request artifact.
2. Artifact includes: request type, reason, target, tool/arguments proposal, and `requires_human_approval=true`.
3. No mutation is executed automatically.
4. Operator reviews and explicitly approves out-of-band before any real mutation command is run.

## Rollback Notes

If this behavior must be rolled back quickly, revert the commit that introduced bounded adaptation guards in `src/agent/loop_.rs` and this document.

Expected rollback effect:

- Removes explicit change-request blocking logic for restricted tool calls.
- Restores prior memory/context shaping behavior.
- Restores prior tool timeout/retry behavior.

