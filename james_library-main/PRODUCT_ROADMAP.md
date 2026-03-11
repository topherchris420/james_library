# R.A.I.N. Lab Product Roadmap: Trustworthy Autonomous Research

This roadmap translates the current vision into executable platform work. It is designed to convert the markdown-centric notebook into a grounded, reproducible, policy-governed research operating system.

## North-star outcomes

- Operate on knowledge, not just read it.
- Treat citations and provenance as product primitives.
- Make memory durable, reviewable, and policy-safe.
- Enable replayable research sessions for collaboration and audits.
- Ship ritual workflows that produce repeatable, standardized wins.
- Keep the system secure against prompt injection and tool abuse.
- Optimize for local-first speed, cost, and privacy via model routing.
- Evolve the graph into a discovery engine that finds hidden bridges.
- Grow through a safe tool marketplace with explicit permissions.
- Run autonomous background research jobs that continuously synthesize.

## Pillar 1 — Executable Knowledge ("Compile Library")

### Feature
A `Compile Library` pipeline that turns markdown corpus content into active knowledge artifacts.

### Build artifacts
- **Embeddings + TF-IDF + entity graph** for semantic retrieval and symbolic traversal.
- **Equation index** extracted from inline and block math.
- **Grounded quote spans index** with exact source offsets.
- **Contradiction candidates** generated from claim-level opposition detection.

### Implementation notes
- Add a compile command that scans `*.md` corpus files and produces versioned artifacts under a deterministic output folder.
- Normalize source spans at compile time so runtime answers can reference exact passages without fuzzy matching.
- Add incremental rebuild support keyed by file hash.

## Pillar 2 — Truth Layer (grounding by default)

### Feature
Every agent answer must include:
- confidence score,
- provenance list,
- quoted evidence,
- reproducibility steps (tools called, files read, queries executed).

### Product behaviors
- **Evidence toggle**: expand to exact matched passages.
- **Red badge**: shown when a claim has no grounded evidence.

### Implementation notes
- Add an answer envelope schema with mandatory grounding fields.
- Enforce grounding checks in response assembly.
- Log missing-evidence violations for continuous QA.

## Pillar 3 — Governed Agent Memory

### Feature
Policy-aware memory writes with metadata:
- source type (`paper`, `web`, `user`, `inference`),
- confidence,
- expiry/review date,
- read/write ACL by agent role.

### Supporting tools
- Memory review queue (inbox zero model).
- Memory diff (state evolution over time).
- Memory provenance view (why a memory exists).

### Implementation notes
- Add memory record versioning and review-state transitions.
- Reject writes missing policy fields.
- Build periodic expiry/review sweeps.

## Pillar 4 — Research Flight Recorder

### Feature
Deterministic session replay + exportable artifact bundles containing:
- prompt states,
- tool outputs,
- citation tables,
- final claims.

### Value
- reproducible collaboration,
- publishable research conversation artifacts,
- safety/security auditability.

### Implementation notes
- Emit canonical event logs for each run.
- Add a replay command that reconstructs a session timeline.
- Provide signed export manifests for integrity checking.

## Pillar 5 — Ritual Workflows (one-tap cognition)

### Built-in rituals
- Morning Brief
- Hypothesis Forge
- Adversarial Peer Review
- Experiment Planner
- Patent/novelty scan
- Grant writer
- Build plan generator

### Workflow contract
Each ritual template defines:
- agent selection,
- tool permission set,
- grounding strictness,
- standardized output artifact schema.

## Pillar 6 — Agent Firewall

### Feature
Treat web/corpus text as untrusted by default. Untrusted text must never be allowed to:
- define new instructions,
- trigger additional searches,
- request secrets,
- alter system prompts.

### Implementation notes
- Introduce typed taint metadata on text payloads.
- Add policy engine for tool-call allow/deny with justification.
- Build automated red-team suites for prompt-injection pathways.

## Pillar 7 — Local-first Multi-model Router

### Feature
Broker tasks by capability tier:
- fast local model for routing/extraction,
- stronger model for synthesis,
- deterministic model for formatting/validation,
- optional remote model only with explicit user permission.

### Success metrics
- lower median latency,
- lower token cost,
- higher private/offline completion rate.

## Pillar 8 — Knowledge Hypergraph 2.0

### Feature
Promote discovery queries to first-class UX:
- "Show 5 surprising links between A and B"
- "Which concepts are central but under-cited?"
- "What minimal note set supports this claim?"

### Implementation notes
- Add bridge-scoring metrics (semantic distance + citation support + novelty).
- Add explainable path outputs with evidence spans.

## Pillar 9 — Tool Marketplace

### Feature
Community tools with explicit sandboxed permissions:
- filesystem,
- web,
- python execution,
- network.

### Tool publication requirements
- tests,
- prompt-injection hardening checks,
- reproducibility contract.

## Pillar 10 — Autonomous Research Service

### Feature
Background scheduled jobs (OpenClaw-aligned), e.g.:
- monitor arXiv topics,
- watch patent terms,
- weekly synthesis reports,
- automated artifact generation + notification.

### Positioning
"The lab has a background process that thinks" — always on, always accumulating grounded research value.

## Suggested phased delivery

### Phase 1 (foundation)
- Compile Library artifacts.
- Truth-layer answer envelope + evidence toggle.
- Governed memory schema and write validation.

### Phase 2 (trust + security)
- Agent Firewall taint/policy system.
- Flight Recorder logs + deterministic replay.
- Memory review queue and diff UX.

### Phase 3 (scale + productization)
- Ritual workflow catalog.
- Hypergraph discovery UX.
- Tool Marketplace policy/runtime.
- Autonomous scheduled research jobs.

## Acceptance criteria (platform-level)

- No final claim can be emitted without provenance metadata.
- Any session can be replayed with deterministic claim/citation mapping.
- Any memory item can answer: "who wrote this, from what source, with what confidence, and when should it be reviewed?"
- Untrusted text can never mutate instructions or escalate tool privileges.
- Ritual outputs are standardized and reproducible across reruns.
